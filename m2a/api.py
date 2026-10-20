"""HTTP surface. Plain `def` routes: FastAPI runs them in a thread pool, so blocking graph calls are fine."""
import secrets
import uuid
from pathlib import Path
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from langgraph.types import Command
from pydantic import BaseModel, Field

from m2a.graph import thread
from m2a.memory import MeetingStore

WEB = Path(__file__).resolve().parent / "web"


class RunIn(BaseModel):
    notes_text: str = Field(min_length=30, max_length=40_000)


class ReviewIn(BaseModel):
    approved: bool
    notes: str = Field(default="", max_length=4_000)


def create_app(graph=None, store: MeetingStore | None = None, health=None, lifespan=None,
               access_key: str | None = None) -> FastAPI:
    """With access_key set, every /runs and /actions route needs a matching X-API-Key header."""
    app = FastAPI(title="Meeting to Action", lifespan=lifespan)
    key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    def require_key(key: str | None = Depends(key_header)) -> None:
        if access_key and not (key and secrets.compare_digest(key, access_key)):
            raise HTTPException(401, "missing or wrong X-API-Key")

    locked = [Depends(require_key)]
    if graph is not None:
        app.state.graph = graph
        app.state.store = store
        app.state.health = health or (lambda: True)

    def view(run_id: str) -> dict:
        st = app.state.graph.get_state(thread(run_id))
        if not st.values:
            raise HTTPException(404, "run not found")
        v = st.values
        return {"run_id": run_id, "status": v.get("status"), "meeting": v.get("meeting"),
                "context": v.get("context", []), "followup": v.get("followup"), "revisions": v.get("revisions", 0),
                "meeting_id": v.get("meeting_id"), "awaiting_review": "human_review" in st.next}

    def run_graph(payload, run_id: str) -> None:
        try:
            app.state.graph.invoke(payload, thread(run_id))
        except anthropic.APIError as e:
            raise HTTPException(502, f"Claude API error: {type(e).__name__}") from e

    @app.post("/runs", dependencies=locked)
    def create_run(body: RunIn):
        run_id = str(uuid.uuid4())
        run_graph({"notes_text": body.notes_text}, run_id)
        return view(run_id)

    @app.post("/runs/{run_id}/review", dependencies=locked)
    def review(run_id: str, body: ReviewIn):
        if not view(run_id)["awaiting_review"]:
            raise HTTPException(409, "run is not waiting for review")
        run_graph(Command(resume={"approved": body.approved, "notes": body.notes}), run_id)
        return view(run_id)

    @app.get("/runs/{run_id}", dependencies=locked)
    def get_run(run_id: str):
        return view(run_id)

    @app.get("/actions", dependencies=locked)
    def actions(status: Literal["open", "done", "all"] = "open"):
        return {"actions": [a.as_dict() for a in app.state.store.list_actions(status)]}

    @app.post("/actions/{action_id}/done", dependencies=locked)
    def done(action_id: int):
        if not app.state.store.mark_done(action_id):
            raise HTTPException(404, "no open action with that id")
        return {"ok": True, "id": action_id}

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(WEB / "index.html")

    @app.get("/health")
    def health():
        return {"ok": True, "db": bool(app.state.health())}

    return app
