from conftest import DIGEST, LAST_WEEK, NEXT_WEEK, FakeBrain
from m2a.memory import MEMORY_DIR, InMemoryStore, digest_notes, load_markdown


def test_markdown_seeds_have_meeting_and_date():
    notes = load_markdown(MEMORY_DIR)
    assert len(notes) >= 6
    first = notes[0]
    assert first.meeting == "Weekly sync" and first.held_on == "2026-10-07"
    assert {n.title for n in notes} >= {"Summary", "Decisions", "Action items", "Open questions"}


def test_search_finds_the_carried_over_quote(store):
    hits = store.search("Riverside quote Paolo")
    assert hits and "quote to Riverside Cafe" in hits[0].body
    assert store.search("") == []


def test_save_meeting_adds_notes_and_actions(store):
    before = len(store.notes)
    fu = FakeBrain().draft(DIGEST, [], None)
    mid = store.save_meeting(DIGEST, fu)
    assert mid == 1
    assert len(store.notes) == before + 4
    assert any(n.meeting.startswith("Weekly sync (") for n in store.search("hosting fee numbers"))
    actions = store.list_actions()
    assert [a.owner for a in actions] == ["Ken", "Paolo", "Maria"]  # by due date, undated last
    assert actions[0].due == LAST_WEEK and actions[0].overdue is True
    assert actions[1].due == NEXT_WEEK and actions[1].overdue is False
    assert actions[2].due == "" and actions[2].overdue is False


def test_mark_done_moves_an_action(store):
    store.save_meeting(DIGEST, FakeBrain().draft(DIGEST, [], None))
    assert store.mark_done(1) is True
    assert store.mark_done(1) is False
    assert store.mark_done(99) is False
    assert [a.id for a in store.list_actions("open")] == [2, 3]
    assert [a.id for a in store.list_actions("done")] == [1]
    assert len(store.list_actions("all")) == 3


def test_digest_notes_format():
    notes = digest_notes(DIGEST, FakeBrain().draft(DIGEST, [], None))
    titles = [n.title for n in notes]
    assert titles == ["Summary", "Decisions", "Action items", "Open questions"]
    assert "- Paolo: Send the revised quote to Riverside Cafe by " + NEXT_WEEK in notes[2].body
    assert "(because the photos are their strongest asset)" in notes[1].body
