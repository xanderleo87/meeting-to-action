import json
from datetime import date, timedelta

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from m2a.memory import MEMORY_DIR, InMemoryStore, load_markdown
from m2a.schemas import ActionItem, ContextHit, Decision, FollowUp, MeetingDigest, Reminder

TODAY = date.today()
NEXT_WEEK = (TODAY + timedelta(days=7)).isoformat()
LAST_WEEK = (TODAY - timedelta(days=7)).isoformat()

NOTES = ("Weekly sync, present Maria, Paolo, Ana, Ken. Paolo still owes the revised quote to Riverside Cafe, "
         "will send it Thursday. We went with homepage option B. Ken to switch the contact form inbox by tomorrow.")

DIGEST = MeetingDigest(
    title="Weekly sync", held_on=TODAY.isoformat(), attendees=["Maria", "Paolo", "Ana", "Ken"],
    summary="Riverside quote is still owed and homepage option B was chosen. The contact form inbox moves tomorrow.",
    decisions=[Decision(what="Riverside Cafe homepage uses option B", why="the photos are their strongest asset")],
    actions=[ActionItem(title="Send the revised quote to Riverside Cafe", owner="Paolo", due=NEXT_WEEK),
             ActionItem(title="Switch the contact form to the hello@ inbox", owner="Ken", due=LAST_WEEK),
             ActionItem(title="Bring hosting fee numbers", owner="Maria")],
    open_questions=["Whether the hosting fee changes in January"])

HIT = ContextHit(title="Weekly sync (2026-10-14) / Action items",
                 snippet="Paolo: send the revised quote to Riverside Cafe by 2026-10-17 (carried over)",
                 relation="same quote promised twice before and still open")


class FakeToolModel(GenericFakeChatModel):
    """Scripted chat model that accepts bind_tools and records every call."""
    bound: list = Field(default_factory=list)
    seen: list = Field(default_factory=list)
    structured: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        self.bound.append(([getattr(t, "name", getattr(t, "__name__", t)) for t in tools], kwargs))
        return self

    def invoke(self, input, config=None, **kwargs):
        self.seen.append(list(input))
        return super().invoke(input, config, **kwargs)

    def with_structured_output(self, schema, *, method="function_calling", **kwargs):
        """Mimic json_schema structured output: the scripted reply text is the schema's JSON."""
        self.structured.append((schema.__name__, method))
        return RunnableLambda(lambda msgs: schema.model_validate_json(self.invoke(msgs).content))


def call(name, args, id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": id}])


def answer(args):
    return AIMessage(content=json.dumps(args))


class FakeBrain:
    """Deterministic brain for graph and API tests."""

    def __init__(self, error: Exception | None = None):
        self.error = error
        self.draft_notes = []

    def extract(self, notes_text):
        if self.error:
            raise self.error
        return DIGEST

    def recall(self, digest):
        return [HIT]

    def draft(self, digest, context, notes):
        self.draft_notes.append(notes)
        v = len(self.draft_notes)
        return FollowUp(subject=f"Weekly sync {TODAY.isoformat()} v{v}", email=f"email v{v}", chat_summary=f"chat v{v}",
                        reminders=[Reminder(action="Send the revised quote", owner="Paolo",
                                            remind_on=(TODAY + timedelta(days=5)).isoformat())])


@pytest.fixture
def store():
    return InMemoryStore(load_markdown(MEMORY_DIR))
