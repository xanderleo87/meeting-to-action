from datetime import date

from langchain_core.messages import AIMessage

from conftest import DIGEST, HIT, NOTES, FakeToolModel, answer, call
from m2a.brain import LangChainBrain
from m2a.tools import make_search_tool


def brain(replies, store):
    llm = FakeToolModel(messages=iter(replies))
    return LangChainBrain(llm, make_search_tool(store)), llm


def test_extract_uses_json_schema_and_todays_date(store):
    b, llm = brain([answer(DIGEST.model_dump())], store)
    d = b.extract(NOTES)
    assert d.actions[0].owner == "Paolo"
    assert llm.structured == [("MeetingDigest", "json_schema")]
    system, human = llm.seen[0]
    assert date.today().isoformat() in system.content and human.content == NOTES


def test_recall_runs_the_search_tool_then_submits(store):
    b, llm = brain([call("search_past_meetings", {"query": "Riverside quote"}),
                    call("ContextList", {"hits": [HIT.model_dump()]}, id="c2")], store)
    hits = b.recall(DIGEST)
    assert hits == [HIT]
    assert llm.bound[0][0] == ["search_past_meetings", "ContextList"]
    tool_msg = llm.seen[1][-1]
    assert tool_msg.type == "tool" and "quote to Riverside Cafe" in tool_msg.content


def test_recall_falls_back_to_structured_answer_when_model_stops_calling_tools(store):
    b, llm = brain([call("search_past_meetings", {"query": "hosting fee"}),
                    AIMessage(content="done"),  # no tool call, no ContextList: loop stops
                    answer({"hits": [HIT.model_dump()]})], store)
    hits = b.recall(DIGEST)
    assert hits == [HIT]
    assert llm.structured == [("ContextList", "json_schema")]
    assert "search_past_meetings('hosting fee')" in llm.seen[-1][-1].content


def test_draft_passes_context_and_reviewer_notes(store):
    fu = {"subject": "s", "email": "e", "chat_summary": "c", "reminders": []}
    b, llm = brain([answer(fu)], store)
    out = b.draft(DIGEST, [HIT], "mention the Safari bug first")
    assert out.subject == "s"
    human = llm.seen[0][1].content
    assert "same quote promised twice" in human and "mention the Safari bug first" in human
    assert date.today().isoformat() in llm.seen[0][0].content
