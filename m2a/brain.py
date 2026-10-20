"""The thinking part: a LangChain chat model plus one tool. Knows nothing about graphs or HTTP."""
from datetime import date
from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from m2a.schemas import ContextHit, FollowUp, MeetingDigest

EXTRACT_SYSTEM = (
    "You read raw meeting notes: typed minutes, a transcript, a chat log, a voice-note dump. "
    "Sort what was said into decisions, action items and open questions.\n"
    "Rules:\n"
    "1. A decision is something actually settled. 'We should look at X' is an open question, not a decision.\n"
    "2. An action item has one owner, named as written in the notes. If nobody was named, owner is 'unassigned'. "
    "Title starts with a verb and says the deliverable in plain words.\n"
    "3. Dates: resolve 'Friday', 'next week', 'end of month' against the meeting date. The meeting date is the one "
    "stated in the notes; if none is stated it is today, {today}. Leave due empty when no deadline was given.\n"
    "4. Never invent people, dates or commitments that are not in the notes. Keep the team's own words for "
    "projects, clients and documents.\n"
    "5. summary: two plain sentences a person who missed the meeting would thank you for.")

RECALL_SYSTEM = (
    "You check this meeting against earlier ones. Call search_past_meetings with short keyword queries: one per "
    "action item (the deliverable), one per decision topic, one per person who owns something. Try a synonym "
    "when nothing comes back. Then call ContextList with only the hits that matter now, for example: the same "
    "item was promised at an earlier meeting and is still open; an earlier decision conflicts with today's; a "
    "person already carries several open items. Quote the snippet and say in one clause why it matters. "
    "Return an empty list rather than a stretch.")

DRAFT_SYSTEM = (
    "You write the follow-up the organiser sends after a meeting. From the digest and what earlier meetings "
    "said, produce:\n"
    "1. subject: short and specific, with the meeting name and date.\n"
    "2. email: under 200 words to the attendees. One line of thanks, then 'What we decided' as short bullets, "
    "then 'Who does what' as 'Name: deliverable, by date', then open questions if any, then one closing line "
    "saying when the next check-in is if the notes mention it. If an item was already promised at an earlier "
    "meeting, say so plainly and kindly ('still open from the 7 October sync'). Plain and warm, no hype, full "
    "words, never shorthand like 'u' or 'pls'. Use the names as written.\n"
    "3. chat_summary: the same in three short lines for a WhatsApp or Slack group, no greeting.\n"
    "4. reminders: one per action item that has a due date. remind_on is two days before the due date, or the "
    "due date itself when it is within two days of today ({today}). Nothing for undated items.\n"
    "If the organiser reviewed an earlier draft and asked for changes, their notes win over these rules.")


class ContextList(BaseModel):
    hits: list[ContextHit]


class Brain(Protocol):
    def extract(self, notes_text: str) -> MeetingDigest: ...
    def recall(self, digest: MeetingDigest) -> list[ContextHit]: ...
    def draft(self, digest: MeetingDigest, context: list[ContextHit], notes: str | None) -> FollowUp: ...


def _tool_call(message, name: str) -> dict | None:
    return next((c for c in getattr(message, "tool_calls", []) or [] if c["name"] == name), None)


def _digest_text(d: MeetingDigest) -> str:
    lines = [f"Meeting: {d.title} on {d.held_on}", f"Attendees: {', '.join(d.attendees) or 'not stated'}", "",
             "Decisions:"] + ([f"- {x.what}" for x in d.decisions] or ["- none"])
    lines += ["", "Action items:"] + ([f"- {a.owner}: {a.title}" + (f" (by {a.due})" if a.due else "") for a in d.actions] or ["- none"])
    lines += ["", "Open questions:"] + ([f"- {q}" for q in d.open_questions] or ["- none"])
    return "\n".join(lines)


class LangChainBrain:
    def __init__(self, llm: BaseChatModel, search_tool: BaseTool, max_rounds: int = 4):
        self.llm = llm
        self.search_tool = search_tool
        self.max_rounds = max_rounds

    def _structured(self, schema: type[BaseModel], messages: list) -> BaseModel:
        """Structured output as JSON valid against the schema (no forced tool_choice)."""
        return self.llm.with_structured_output(schema, method="json_schema").invoke(messages)

    def extract(self, notes_text: str) -> MeetingDigest:
        system = EXTRACT_SYSTEM.format(today=date.today().isoformat())
        return self._structured(MeetingDigest, [SystemMessage(system), HumanMessage(notes_text)])

    def recall(self, digest: MeetingDigest) -> list[ContextHit]:
        bound = self.llm.bind_tools([self.search_tool, ContextList])
        ask = _digest_text(digest)
        messages = [SystemMessage(RECALL_SYSTEM), HumanMessage(ask)]
        found: list[str] = []
        for _ in range(self.max_rounds):
            reply = bound.invoke(messages)
            messages.append(reply)
            submitted = _tool_call(reply, "ContextList")
            if submitted:
                return ContextList.model_validate(submitted["args"]).hits
            searches = [c for c in reply.tool_calls if c["name"] == self.search_tool.name]
            if not searches:
                break
            for c in searches:
                result = self.search_tool.invoke(c["args"])
                found.append(f"search_past_meetings({c['args'].get('query', '')!r}):\n{result}")
                messages.append(ToolMessage(result, tool_call_id=c["id"]))
        # Fresh transcript with the results as text, then a structured answer.
        text = ask + ("\n\nSearch results:\n" + "\n\n".join(found) if found else "\n\n(no search results)")
        return self._structured(ContextList, [SystemMessage(RECALL_SYSTEM), HumanMessage(text)]).hits

    def draft(self, digest: MeetingDigest, context: list[ContextHit], notes: str | None) -> FollowUp:
        body = ["Meeting digest:", digest.model_dump_json(indent=1), "", "From earlier meetings:"]
        body += [f"- {h.title}: {h.snippet} ({h.relation})" for h in context] or ["- nothing relevant"]
        if notes:
            body += ["", "The organiser reviewed the previous draft and asked for changes:", notes]
        system = DRAFT_SYSTEM.format(today=date.today().isoformat())
        return self._structured(FollowUp, [SystemMessage(system), HumanMessage("\n".join(body))])
