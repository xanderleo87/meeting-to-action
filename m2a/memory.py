"""Meeting memory: every approved meeting is kept, so the next one can be read against it.

Two stores with one interface. The in-memory one runs the tests and a laptop without Postgres.
The Postgres one keeps three tables: searchable notes (full-text, generated tsvector + GIN index),
meetings, and action items that stay open until somebody marks them done."""
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Protocol

from psycopg_pool import ConnectionPool

from m2a.schemas import FollowUp, MeetingDigest

MEMORY_DIR = Path(__file__).resolve().parent.parent / "memory"


@dataclass(frozen=True)
class Note:
    meeting: str
    held_on: str
    title: str
    body: str


@dataclass
class Action:
    id: int
    meeting_id: int | None
    meeting: str
    title: str
    owner: str
    due: str
    status: str = "open"
    overdue: bool = field(default=False)

    def as_dict(self) -> dict:
        return {"id": self.id, "meeting_id": self.meeting_id, "meeting": self.meeting, "title": self.title,
                "owner": self.owner, "due": self.due, "status": self.status, "overdue": self.overdue}


class MeetingStore(Protocol):
    def search(self, query: str, k: int = 4) -> list[Note]: ...
    def save_meeting(self, digest: MeetingDigest, followup: FollowUp) -> int: ...
    def list_actions(self, status: str = "open") -> list[Action]: ...
    def mark_done(self, action_id: int) -> bool: ...


def load_markdown(folder: Path) -> list[Note]:
    """One note per `## ` section. The H1 is the meeting name; a `Held on: YYYY-MM-DD` line gives the date."""
    notes: list[Note] = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        meeting = m.group(1).strip() if m else path.stem
        d = re.search(r"^Held on:\s*(\d{4}-\d{2}-\d{2})", text, re.M)
        held_on = d.group(1) if d else ""
        for sec in re.split(r"^##\s+", text, flags=re.M)[1:]:
            title, _, body = sec.partition("\n")
            if body.strip():
                notes.append(Note(meeting, held_on, title.strip(), body.strip()))
    return notes


def digest_notes(digest: MeetingDigest, followup: FollowUp) -> list[Note]:
    """How an approved meeting is written into memory: three searchable sections."""
    head = f"{digest.title} ({digest.held_on})"
    out = [Note(head, digest.held_on, "Summary", digest.summary + "\nAttendees: " + ", ".join(digest.attendees))]
    if digest.decisions:
        out.append(Note(head, digest.held_on, "Decisions",
                        "\n".join(f"- {d.what}" + (f" (because {d.why})" if d.why else "") for d in digest.decisions)))
    if digest.actions:
        out.append(Note(head, digest.held_on, "Action items",
                        "\n".join(f"- {a.owner}: {a.title}" + (f" by {a.due}" if a.due else "") for a in digest.actions)))
    if digest.open_questions:
        out.append(Note(head, digest.held_on, "Open questions", "\n".join(f"- {q}" for q in digest.open_questions)))
    return out


def _overdue(due: str, status: str, today: date | None = None) -> bool:
    return bool(due) and status == "open" and date.fromisoformat(due) < (today or date.today())


class InMemoryStore:
    """Keyword overlap scoring. Good enough for tests and for running without Postgres."""

    def __init__(self, notes: Iterable[Note] = ()):
        self.notes = list(notes)
        self.actions: list[Action] = []
        self.meetings: list[dict] = []

    def search(self, query: str, k: int = 4) -> list[Note]:
        words = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2}
        if not words:
            return []
        scored = []
        for n in self.notes:
            hay = f"{n.meeting} {n.title} {n.body}".lower()
            score = sum(hay.count(w) for w in words)
            if score:
                scored.append((score, n))
        scored.sort(key=lambda s: -s[0])
        return [n for _, n in scored[:k]]

    def save_meeting(self, digest: MeetingDigest, followup: FollowUp) -> int:
        meeting_id = len(self.meetings) + 1
        self.meetings.append({"id": meeting_id, "title": digest.title, "held_on": digest.held_on})
        self.notes.extend(digest_notes(digest, followup))
        for a in digest.actions:
            self.actions.append(Action(len(self.actions) + 1, meeting_id, digest.title, a.title, a.owner, a.due))
        return meeting_id

    def list_actions(self, status: str = "open") -> list[Action]:
        rows = [a for a in self.actions if status == "all" or a.status == status]
        for a in rows:
            a.overdue = _overdue(a.due, a.status)
        return sorted(rows, key=lambda a: (a.due or "9999", a.id))

    def mark_done(self, action_id: int) -> bool:
        for a in self.actions:
            if a.id == action_id and a.status == "open":
                a.status = "done"
                return True
        return False


SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
  id         serial PRIMARY KEY,
  title      text NOT NULL,
  held_on    date,
  summary    text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS notes (
  id      serial PRIMARY KEY,
  source  text NOT NULL DEFAULT 'run',
  meeting text NOT NULL,
  held_on text NOT NULL DEFAULT '',
  title   text NOT NULL,
  body    text NOT NULL,
  tsv     tsvector GENERATED ALWAYS AS
          (to_tsvector('english', meeting || ' ' || title || ' ' || body)) STORED
);
CREATE INDEX IF NOT EXISTS notes_tsv ON notes USING GIN (tsv);
CREATE TABLE IF NOT EXISTS actions (
  id         serial PRIMARY KEY,
  meeting_id int REFERENCES meetings(id) ON DELETE SET NULL,
  meeting    text NOT NULL,
  title      text NOT NULL,
  owner      text NOT NULL DEFAULT 'unassigned',
  due        date,
  status     text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
SEARCH = """
SELECT meeting, held_on, title, body FROM notes, websearch_to_tsquery('english', %(q)s) q
WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC, id DESC LIMIT %(k)s
"""
SEARCH_OR = """
SELECT meeting, held_on, title, body FROM notes, to_tsquery('english', %(q)s) q
WHERE tsv @@ q ORDER BY ts_rank_cd(tsv, q) DESC, id DESC LIMIT %(k)s
"""


def make_pool(url: str) -> ConnectionPool:
    return ConnectionPool(url, min_size=1, max_size=4, kwargs={"autocommit": True}, open=True)


class PostgresStore:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool

    def setup(self) -> None:
        with self.pool.connection() as c:
            c.execute(SCHEMA)

    def replace_seed(self, notes: Iterable[Note]) -> int:
        """Reload the example past meetings. Meetings saved from real runs are left alone."""
        rows = [("seed", n.meeting, n.held_on, n.title, n.body) for n in notes]
        with self.pool.connection() as c:
            c.execute("DELETE FROM notes WHERE source = 'seed'")
            with c.cursor() as cur:
                cur.executemany("INSERT INTO notes (source, meeting, held_on, title, body) VALUES (%s, %s, %s, %s, %s)", rows)
        return len(rows)

    def search(self, query: str, k: int = 4) -> list[Note]:
        with self.pool.connection() as c:
            rows = c.execute(SEARCH, {"q": query, "k": k}).fetchall()
            if not rows:
                terms = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2]
                if terms:
                    rows = c.execute(SEARCH_OR, {"q": " | ".join(terms), "k": k}).fetchall()
        return [Note(*r) for r in rows]

    def save_meeting(self, digest: MeetingDigest, followup: FollowUp) -> int:
        with self.pool.connection() as c:
            meeting_id = c.execute(
                "INSERT INTO meetings (title, held_on, summary) VALUES (%s, %s, %s) RETURNING id",
                (digest.title, digest.held_on, digest.summary)).fetchone()[0]
            with c.cursor() as cur:
                cur.executemany("INSERT INTO notes (source, meeting, held_on, title, body) VALUES ('run', %s, %s, %s, %s)",
                                [(n.meeting, n.held_on, n.title, n.body) for n in digest_notes(digest, followup)])
                cur.executemany("INSERT INTO actions (meeting_id, meeting, title, owner, due) VALUES (%s, %s, %s, %s, %s)",
                                [(meeting_id, digest.title, a.title, a.owner, a.due or None) for a in digest.actions])
        return meeting_id

    def list_actions(self, status: str = "open") -> list[Action]:
        where = "" if status == "all" else "WHERE status = %(s)s"
        sql = f"SELECT id, meeting_id, meeting, title, owner, due, status FROM actions {where} ORDER BY due NULLS LAST, id"
        with self.pool.connection() as c:
            rows = c.execute(sql, {"s": status}).fetchall()
        out = []
        for id_, mid, meeting, title, owner, due, st in rows:
            due_s = due.isoformat() if due else ""
            out.append(Action(id_, mid, meeting, title, owner, due_s, st, _overdue(due_s, st)))
        return out

    def mark_done(self, action_id: int) -> bool:
        with self.pool.connection() as c:
            return c.execute("UPDATE actions SET status = 'done' WHERE id = %s AND status = 'open'",
                             (action_id,)).rowcount == 1

    def ping(self) -> bool:
        try:
            with self.pool.connection() as c:
                return c.execute("SELECT 1").fetchone()[0] == 1
        except Exception:
            return False
