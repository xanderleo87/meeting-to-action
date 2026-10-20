"""LangGraph workflow: extract -> recall -> draft -> human_review -> save (or redraft).

The review node interrupts the graph. State lives in the checkpointer (Postgres in production), so a
run survives a restart and resumes exactly at the review when the organiser answers. Only the save
node writes to memory, and only after approval: nothing a reviewer rejected is ever remembered."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from m2a.brain import Brain
from m2a.memory import MeetingStore
from m2a.schemas import ContextHit, FollowUp, MeetingDigest


class MeetingState(TypedDict, total=False):
    notes_text: str
    meeting: dict | None
    context: list[dict]
    followup: dict | None
    review_notes: str | None
    revisions: int
    status: str
    meeting_id: int | None


def thread(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def build_graph(brain: Brain, store: MeetingStore, checkpointer, max_revisions: int = 3):
    def extract(s: MeetingState):
        d = brain.extract(s["notes_text"])
        return {"meeting": d.model_dump(), "revisions": 0, "review_notes": None, "status": "extracting",
                "meeting_id": None}

    def recall(s: MeetingState):
        hits = brain.recall(MeetingDigest(**s["meeting"]))
        return {"context": [h.model_dump() for h in hits]}

    def draft(s: MeetingState):
        fu = brain.draft(MeetingDigest(**s["meeting"]), [ContextHit(**c) for c in s.get("context", [])],
                         s.get("review_notes"))
        return {"followup": fu.model_dump(), "status": "awaiting_review"}

    def human_review(s: MeetingState):
        # Nothing before interrupt() has side effects: the node re-runs from the top on resume.
        decision = interrupt({"meeting": s["meeting"], "followup": s["followup"]})
        if decision.get("approved"):
            return {"status": "approved"}
        return {"status": "extracting", "review_notes": decision.get("notes") or None,
                "revisions": s.get("revisions", 0) + 1}

    def after_review(s: MeetingState) -> str:
        if s["status"] == "approved" or s["revisions"] >= max_revisions:
            return "save"
        return "draft"

    def save(s: MeetingState):
        if s["status"] != "approved":
            return {"status": "revision_cap"}
        meeting_id = store.save_meeting(MeetingDigest(**s["meeting"]), FollowUp(**s["followup"]))
        return {"status": "approved", "meeting_id": meeting_id}

    g = StateGraph(MeetingState)
    for name, fn in [("extract", extract), ("recall", recall), ("draft", draft),
                     ("human_review", human_review), ("save", save)]:
        g.add_node(name, fn)
    g.add_edge(START, "extract")
    g.add_edge("extract", "recall")
    g.add_edge("recall", "draft")
    g.add_edge("draft", "human_review")
    g.add_conditional_edges("human_review", after_review, {"save": "save", "draft": "draft"})
    g.add_edge("save", END)
    return g.compile(checkpointer=checkpointer)
