from datetime import date

from m2a.schemas import ActionItem, FollowUp, MeetingDigest, Reminder


def test_due_dates_are_iso_or_blank():
    assert ActionItem(title="Send quote", due="2026-10-23").due == "2026-10-23"
    assert ActionItem(title="Send quote", due="Thursday").due == ""
    assert ActionItem(title="Send quote", due=" 2026-10-23 ").due == "2026-10-23"
    assert ActionItem(title="Send quote").owner == "unassigned"


def test_meeting_date_falls_back_to_today():
    d = MeetingDigest(title="Sync", held_on="sometime last week", summary="s")
    assert d.held_on == date.today().isoformat()
    assert d.actions == [] and d.decisions == []


def test_followup_round_trips_json():
    fu = FollowUp(subject="s", email="e", chat_summary="c", reminders=[Reminder(action="a", owner="o", remind_on="bad")])
    again = FollowUp.model_validate_json(fu.model_dump_json())
    assert again.reminders[0].remind_on == ""
