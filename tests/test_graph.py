from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from conftest import NOTES, FakeBrain
from m2a.graph import build_graph, thread
from m2a.memory import InMemoryStore


def start(brain=None, store=None, **kw):
    brain = brain or FakeBrain()
    store = store or InMemoryStore()
    g = build_graph(brain, store, InMemorySaver(), **kw)
    cfg = thread("run-1")
    g.invoke({"notes_text": NOTES}, cfg)
    return g, cfg, brain, store


def test_runs_until_review_and_pauses():
    g, cfg, _, store = start()
    st = g.get_state(cfg)
    assert st.next == ("human_review",)
    assert st.values["status"] == "awaiting_review"
    assert [a["owner"] for a in st.values["meeting"]["actions"]] == ["Paolo", "Ken", "Maria"]
    assert st.values["context"][0]["relation"].startswith("same quote")
    assert st.values["followup"]["email"] == "email v1"
    assert store.actions == []  # nothing remembered before approval


def test_reject_redrafts_with_notes():
    g, cfg, brain, _ = start()
    g.invoke(Command(resume={"approved": False, "notes": "shorter email"}), cfg)
    st = g.get_state(cfg)
    assert brain.draft_notes == [None, "shorter email"]
    assert st.values["followup"]["email"] == "email v2"
    assert st.values["revisions"] == 1
    assert st.next == ("human_review",)


def test_approve_saves_the_meeting():
    g, cfg, _, store = start()
    g.invoke(Command(resume={"approved": True, "notes": ""}), cfg)
    st = g.get_state(cfg)
    assert st.values["status"] == "approved"
    assert st.values["meeting_id"] == 1
    assert st.next == ()
    assert [a.title for a in store.list_actions()][1] == "Send the revised quote to Riverside Cafe"
    assert store.search("Riverside")  # the meeting is now searchable for the next run


def test_revision_cap_finalizes_without_saving():
    g, cfg, brain, store = start(max_revisions=2)
    for _ in range(2):
        g.invoke(Command(resume={"approved": False, "notes": "again"}), cfg)
    st = g.get_state(cfg)
    assert st.values["status"] == "revision_cap"
    assert st.next == ()
    assert len(brain.draft_notes) == 2
    assert store.actions == [] and store.meetings == []


def test_two_runs_do_not_share_state():
    g = build_graph(FakeBrain(), InMemoryStore(), InMemorySaver())
    g.invoke({"notes_text": NOTES}, thread("a"))
    g.invoke({"notes_text": NOTES}, thread("b"))
    g.invoke(Command(resume={"approved": True, "notes": ""}), thread("a"))
    assert g.get_state(thread("a")).values["status"] == "approved"
    assert g.get_state(thread("b")).values["status"] == "awaiting_review"
