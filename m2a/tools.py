"""LangChain tools the model may call. One tool: search past meetings."""
from langchain_core.tools import StructuredTool

from m2a.memory import MeetingStore


def make_search_tool(store: MeetingStore, k: int = 4) -> StructuredTool:
    def search_past_meetings(query: str) -> str:
        """Search earlier meetings: their decisions, action items and open questions. Use short keyword
        queries (a person's name, a project, a deliverable) and try a synonym if nothing comes back."""
        hits = store.search(query, k=k)
        if not hits:
            return "No earlier meeting mentions that."
        return "\n\n".join(f"[{h.meeting} / {h.title}]\n{h.body}" for h in hits)

    return StructuredTool.from_function(search_past_meetings, name="search_past_meetings")
