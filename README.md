# Meeting to Action

Paste what was said in a meeting. Get the decisions, who does what by when, and the follow-up email,
drafted against your earlier meetings and waiting for your approval. Approved meetings are remembered,
so a promise made two weeks ago shows up in this week's follow-up as "still open".

Built by [Alexander III Empleo](https://github.com/xanderleo87) with **LangGraph, LangChain, Claude,
Postgres, FastAPI and Terraform**. Every run pauses for a human before anything is saved.

## What happens on a run

```
notes ──> extract ──> recall ──> draft ──> human_review ──> save ──> END
                                   ^            │ "ask for changes" (up to 3 times)
                                   └────────────┘
```

| Step | What it does | Where the code is |
|------|--------------|-------------------|
| extract | Claude turns raw notes into a typed digest: decisions, action items with owner and ISO due date, open questions. Dates like "Thursday" are resolved against the meeting date. | `m2a/brain.py` `extract`, `m2a/schemas.py` |
| recall | A LangChain tool loop. Claude calls `search_past_meetings` (Postgres full-text search) with short queries, then submits only the hits that matter: carry-overs, conflicting decisions, overloaded owners. | `m2a/brain.py` `recall`, `m2a/tools.py`, `m2a/memory.py` |
| draft | Follow-up email under 200 words, a three-line chat version, and reminder dates two days before each deadline. | `m2a/brain.py` `draft` |
| human_review | `interrupt()`. The graph stops and the state is checkpointed in Postgres. The organiser approves or asks for changes; a restart in between loses nothing. | `m2a/graph.py` |
| save | Only after approval: the meeting is written to memory and its action items go on the open list. Rejected drafts are never remembered. | `m2a/graph.py`, `m2a/memory.py` |

The structured steps use `with_structured_output(method="json_schema")`, so every Claude answer is
validated against the Pydantic model before the graph sees it.

## API

All routes except `/health` need the `X-API-Key` header when `APP_ACCESS_KEY` is set.

| Route | Purpose |
|-------|---------|
| `POST /runs` `{notes_text}` | Run extract, recall and draft; returns the run paused at review |
| `POST /runs/{id}/review` `{approved, notes}` | Approve (saves) or ask for changes (redrafts with your notes) |
| `GET /runs/{id}` | Current state of a run |
| `GET /actions?status=open\|done\|all` | Action items across every approved meeting, overdue flagged |
| `POST /actions/{id}/done` | Tick one off |
| `GET /` | The web page |
| `GET /health` | `{"ok": true, "db": true}` |

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                                   # 22 tests, no network, no database
```

Local stack with Terraform (Docker Desktop running):

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars         # put your Claude key in
terraform init && terraform apply
# app at http://localhost:8090, Postgres on 127.0.0.1:5434
```

Railway: the repo ships a `Dockerfile` and `railway.json` (health check on `/health`). Set
`ANTHROPIC_API_KEY`, `DATABASE_URL` (reference the Postgres plugin), `CLAUDE_MODEL` and optionally
`APP_ACCESS_KEY` on the service.

## Layout

```
m2a/
  schemas.py   typed shapes: MeetingDigest, ActionItem, FollowUp, ContextHit
  brain.py     the three Claude steps and their prompts
  tools.py     search_past_meetings (LangChain StructuredTool)
  memory.py    MeetingStore: in-memory for tests, Postgres (tsvector + GIN) in production
  graph.py     the LangGraph workflow with the interrupt
  api.py       FastAPI routes and the X-API-Key gate
  main.py      production wiring: pool, PostgresSaver, ChatAnthropic
  web/         the single-page front end
memory/        example past meetings seeded on start (real runs are kept separately)
samples/       example notes to paste
infra/         Terraform: Postgres + app containers on the local Docker engine
tests/         22 tests with a scripted fake model and a fake brain
```

## Try it with your own meeting

Any notes work: a Zoom summary, a WhatsApp thread, a transcript, five lines typed from memory. Press
"Load example notes" on the page to see a run where one action item has already been promised at two
earlier meetings.
