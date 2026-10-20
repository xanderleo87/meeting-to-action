import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from conftest import NOTES, FakeBrain
from m2a.api import create_app
from m2a.graph import build_graph
from m2a.memory import InMemoryStore

KEY = {"X-API-Key": "secret"}


def make_client(brain=None, access_key="secret"):
    store = InMemoryStore()
    graph = build_graph(brain or FakeBrain(), store, InMemorySaver())
    return TestClient(create_app(graph, store, access_key=access_key)), store


def test_key_gate():
    c, _ = make_client()
    assert c.post("/runs", json={"notes_text": NOTES}).status_code == 401
    assert c.get("/actions", headers={"X-API-Key": "nope"}).status_code == 401
    assert c.get("/health").status_code == 200  # health stays open for the platform
    open_client, _ = make_client(access_key=None)
    assert open_client.get("/actions").status_code == 200


def test_full_run_approve_and_track_actions():
    c, _ = make_client()
    r = c.post("/runs", json={"notes_text": NOTES}, headers=KEY)
    assert r.status_code == 200
    run = r.json()
    assert run["status"] == "awaiting_review" and run["awaiting_review"] is True
    assert run["meeting"]["title"] == "Weekly sync" and run["followup"]["email"] == "email v1"
    assert run["context"][0]["title"].startswith("Weekly sync")

    # Ask for changes once, then approve.
    r = c.post(f"/runs/{run['run_id']}/review", json={"approved": False, "notes": "shorter"}, headers=KEY)
    assert r.json()["followup"]["email"] == "email v2" and r.json()["revisions"] == 1
    r = c.post(f"/runs/{run['run_id']}/review", json={"approved": True}, headers=KEY)
    assert r.json()["status"] == "approved" and r.json()["meeting_id"] == 1
    assert r.json()["awaiting_review"] is False

    # Reviewing again is refused; the run is still readable.
    assert c.post(f"/runs/{run['run_id']}/review", json={"approved": True}, headers=KEY).status_code == 409
    assert c.get(f"/runs/{run['run_id']}", headers=KEY).json()["status"] == "approved"

    # The action items are now on the open list, oldest due first, with the overdue one flagged.
    acts = c.get("/actions", headers=KEY).json()["actions"]
    assert [a["owner"] for a in acts] == ["Ken", "Paolo", "Maria"]
    assert acts[0]["overdue"] is True
    assert c.post(f"/actions/{acts[0]['id']}/done", headers=KEY).json() == {"ok": True, "id": acts[0]["id"]}
    assert len(c.get("/actions", headers=KEY).json()["actions"]) == 2
    assert len(c.get("/actions?status=done", headers=KEY).json()["actions"]) == 1
    assert c.get("/actions?status=weird", headers=KEY).status_code == 422
    assert c.post("/actions/999/done", headers=KEY).status_code == 404


def test_validation_and_not_found():
    c, _ = make_client()
    assert c.post("/runs", json={"notes_text": "too short"}, headers=KEY).status_code == 422
    assert c.get("/runs/nope", headers=KEY).status_code == 404
    assert c.post("/runs/nope/review", json={"approved": True}, headers=KEY).status_code == 404


def test_claude_api_error_becomes_502():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIStatusError("overloaded", response=httpx.Response(529, request=req), body=None)
    c, _ = make_client(FakeBrain(error=err))
    r = c.post("/runs", json={"notes_text": NOTES}, headers=KEY)
    assert r.status_code == 502 and "APIStatusError" in r.json()["detail"]


def test_home_and_health():
    c, _ = make_client()
    assert c.get("/health").json() == {"ok": True, "db": True}
    r = c.get("/")
    assert r.status_code == 200 and "Meeting to Action" in r.text
