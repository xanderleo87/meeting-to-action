"""Production entry point: `uvicorn m2a.main:app`. Postgres for memory + checkpoints, Claude via LangChain."""
from contextlib import asynccontextmanager

from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.postgres import PostgresSaver

from m2a.api import create_app
from m2a.brain import LangChainBrain
from m2a.config import load_settings
from m2a.graph import build_graph
from m2a.memory import MEMORY_DIR, PostgresStore, load_markdown, make_pool
from m2a.tools import make_search_tool


@asynccontextmanager
async def lifespan(app):
    settings = load_settings()
    if not settings.database_url or not settings.anthropic_api_key:
        raise RuntimeError("DATABASE_URL and ANTHROPIC_API_KEY must be set")
    pool = make_pool(settings.database_url)
    store = PostgresStore(pool)
    store.setup()
    store.replace_seed(load_markdown(MEMORY_DIR))
    saver = PostgresSaver(pool)
    saver.setup()
    llm = ChatAnthropic(model=settings.claude_model, api_key=settings.anthropic_api_key,
                        max_tokens=4096, max_retries=2)
    app.state.graph = build_graph(LangChainBrain(llm, make_search_tool(store)), store, saver)
    app.state.store = store
    app.state.health = store.ping
    yield
    pool.close()


app = create_app(lifespan=lifespan, access_key=load_settings().access_key)
