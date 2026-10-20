"""Typed shapes that cross the boundaries: Claude structured output in, HTTP JSON out."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _iso_or_blank(v: str) -> str:
    try:
        return date.fromisoformat(v.strip()).isoformat()
    except (ValueError, AttributeError):
        return ""


class ActionItem(BaseModel):
    """One thing somebody agreed to do."""
    title: str = Field(description="Verb first, one line, in plain words: 'Send the revised quote to Maria'")
    owner: str = Field(default="unassigned", description="First name as written in the notes, or 'unassigned'")
    due: str = Field(default="", description="ISO date (YYYY-MM-DD) if a deadline was given or clearly implied, else empty")
    note: str = Field(default="", description="Detail the owner needs, one clause, or empty")

    @field_validator("due")
    @classmethod
    def _due(cls, v: str) -> str:
        return _iso_or_blank(v)


class Decision(BaseModel):
    what: str = Field(description="What was decided, one sentence")
    why: str = Field(default="", description="The reason given, if any")


class MeetingDigest(BaseModel):
    """What the notes actually said, sorted into the four things people need afterwards."""
    title: str = Field(description="Short meeting name, from the notes or inferred: 'Weekly ops sync'")
    held_on: str = Field(description="ISO date (YYYY-MM-DD) the meeting took place; today's date if the notes do not say")
    attendees: list[str] = Field(default_factory=list, description="First names as written")
    summary: str = Field(description="The meeting in two plain sentences")
    decisions: list[Decision] = Field(default_factory=list, description="Only things actually settled")
    actions: list[ActionItem] = Field(default_factory=list, description="Every commitment, one per owner")
    open_questions: list[str] = Field(default_factory=list, description="Raised but not settled")

    @field_validator("held_on")
    @classmethod
    def _held(cls, v: str) -> str:
        return _iso_or_blank(v) or date.today().isoformat()


class ContextHit(BaseModel):
    """Something from a past meeting that bears on this one."""
    title: str
    snippet: str
    relation: str = Field(description="Why it matters now, one clause: 'same item was promised on 7 Oct'")


class Reminder(BaseModel):
    action: str
    owner: str
    remind_on: str = Field(description="ISO date to nudge the owner, normally two days before the due date")

    @field_validator("remind_on")
    @classmethod
    def _rem(cls, v: str) -> str:
        return _iso_or_blank(v)


class FollowUp(BaseModel):
    """What the organiser reviews before anything goes out."""
    subject: str = Field(description="Email subject line")
    email: str = Field(description="Follow-up email to attendees, under 200 words, plain and warm, full words")
    chat_summary: str = Field(description="Three short lines for a WhatsApp or Slack group")
    reminders: list[Reminder] = Field(default_factory=list, description="One per dated action item")


class ReviewDecision(BaseModel):
    approved: bool
    notes: str = ""


Status = Literal["extracting", "awaiting_review", "approved", "revision_cap"]
