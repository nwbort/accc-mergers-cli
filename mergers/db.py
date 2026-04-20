"""SQLite + FTS5 storage and queries for the ACCC merger cache."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Merger, Questionnaire

CACHE_DIR = Path.home() / ".accc-mergers"
DB_PATH = CACHE_DIR / "db.sqlite"
LAST_SYNC_PATH = CACHE_DIR / "last_sync.txt"
STALE_DAYS = 7


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    ensure_cache_dir()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS mergers (
    merger_id TEXT PRIMARY KEY,
    merger_name TEXT,
    status TEXT,
    stage TEXT,
    is_waiver INTEGER,
    acquirers_text TEXT,
    targets_text TEXT,
    industries_text TEXT,
    determination TEXT,
    phase INTEGER,
    notification_date TEXT,
    determination_date TEXT,
    raw_json TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS merger_content USING fts5(
    merger_id UNINDEXED,
    merger_name,
    acquirers_text,
    targets_text,
    industries_text,
    merger_description,
    determination_reasons,
    determination_overlap,
    all_determination_text,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS questionnaires (
    merger_id TEXT PRIMARY KEY,
    deadline TEXT,
    questions_count INTEGER,
    raw_json TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS questionnaire_content USING fts5(
    merger_id UNINDEXED,
    question_number UNINDEXED,
    question_text,
    tokenize = 'porter unicode61'
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS stats (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS industries (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def clear_mergers(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DELETE FROM mergers;
        DELETE FROM merger_content;
        DELETE FROM questionnaires;
        DELETE FROM questionnaire_content;
        """
    )
    conn.commit()


def insert_merger(conn: sqlite3.Connection, merger: Merger) -> None:
    determination = merger.outcome()

    conn.execute(
        """
        INSERT OR REPLACE INTO mergers (
            merger_id, merger_name, status, stage, is_waiver,
            acquirers_text, targets_text, industries_text,
            determination, phase, notification_date, determination_date, raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            merger.merger_id,
            merger.merger_name,
            merger.status,
            merger.stage,
            1 if merger.is_waiver else 0,
            merger.acquirers_text(),
            merger.targets_text(),
            merger.industries_text(),
            determination,
            merger.phase_number(),
            merger.effective_notification_datetime,
            merger.determination_publication_date,
            json.dumps(merger.raw),
        ),
    )
    conn.execute(
        "DELETE FROM merger_content WHERE merger_id = ?", (merger.merger_id,)
    )
    conn.execute(
        """
        INSERT INTO merger_content (
            merger_id, merger_name, acquirers_text, targets_text, industries_text,
            merger_description, determination_reasons, determination_overlap, all_determination_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            merger.merger_id,
            merger.merger_name,
            merger.acquirers_text(),
            merger.targets_text(),
            merger.industries_text(),
            merger.merger_description,
            merger.section_text("Reasons for determination"),
            merger.section_text("Overlap and relationship between the parties"),
            merger.all_determination_text(),
        ),
    )


def insert_questionnaire(conn: sqlite3.Connection, q: Questionnaire) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO questionnaires (merger_id, deadline, questions_count, raw_json)
        VALUES (?, ?, ?, ?)
        """,
        (q.merger_id, q.deadline, q.questions_count, json.dumps(q.questions)),
    )
    conn.execute(
        "DELETE FROM questionnaire_content WHERE merger_id = ?", (q.merger_id,)
    )
    for question in q.questions:
        number = question.get("number") or question.get("question_number") or ""
        text = (
            question.get("text")
            or question.get("question")
            or question.get("question_text")
            or ""
        )
        conn.execute(
            "INSERT INTO questionnaire_content (merger_id, question_number, question_text) VALUES (?, ?, ?)",
            (q.merger_id, str(number), text),
        )


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_stats(conn: sqlite3.Connection, payload: dict[str, Any]) -> None:
    conn.execute("DELETE FROM stats")
    conn.execute(
        "INSERT INTO stats (key, value) VALUES (?, ?)",
        ("stats", json.dumps(payload)),
    )


def get_stats(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT value FROM stats WHERE key = 'stats'").fetchone()
    if not row:
        return None
    return json.loads(row["value"])


def set_industries(conn: sqlite3.Connection, payload: Any) -> None:
    conn.execute("DELETE FROM industries")
    conn.execute(
        "INSERT INTO industries (key, value) VALUES (?, ?)",
        ("industries", json.dumps(payload)),
    )


def get_industries(conn: sqlite3.Connection) -> Any:
    row = conn.execute(
        "SELECT value FROM industries WHERE key = 'industries'"
    ).fetchone()
    if not row:
        return None
    return json.loads(row["value"])


@dataclass
class SearchFilters:
    outcome: str | None = None
    industry: str | None = None
    phase: int | None = None
    waiver: bool | None = None
    year: int | None = None
    since: str | None = None
    until: str | None = None
    limit: int = 10


def _outcome_where(outcome: str) -> tuple[str, list[Any]]:
    outcome = outcome.lower()
    if outcome == "approved":
        return "LOWER(m.determination) = ?", ["approved"]
    if outcome == "denied":
        return "(LOWER(m.determination) = ? OR LOWER(m.determination) = ?)", ["denied", "not approved"]
    if outcome == "phase2":
        return "m.phase = ?", [2]
    if outcome == "pending":
        return (
            "(m.determination IS NULL OR m.determination = '' OR LOWER(m.status) LIKE ?)",
            ["%pending%"],
        )
    raise ValueError(f"Unknown outcome: {outcome}")


def _apply_filters(
    filters: SearchFilters, extra_where: list[str], params: list[Any]
) -> None:
    if filters.outcome:
        clause, outcome_params = _outcome_where(filters.outcome)
        extra_where.append(clause)
        params.extend(outcome_params)
    if filters.industry:
        extra_where.append("LOWER(m.industries_text) LIKE ?")
        params.append(f"%{filters.industry.lower()}%")
    if filters.phase == 0:
        extra_where.append("m.is_waiver = 1")
    elif filters.phase is not None:
        extra_where.append("m.phase = ?")
        params.append(filters.phase)
    if filters.waiver is True:
        extra_where.append("m.is_waiver = 1")
    elif filters.waiver is False:
        extra_where.append("m.is_waiver = 0")
    if filters.year is not None:
        extra_where.append(
            "CAST(substr(m.notification_date, 1, 4) AS INTEGER) = ?"
        )
        params.append(filters.year)
    if filters.since is not None:
        extra_where.append(
            "m.notification_date IS NOT NULL AND substr(m.notification_date, 1, 10) >= ?"
        )
        params.append(filters.since)
    if filters.until is not None:
        extra_where.append(
            "m.notification_date IS NOT NULL AND substr(m.notification_date, 1, 10) <= ?"
        )
        params.append(filters.until)


def search(
    conn: sqlite3.Connection, query: str, filters: SearchFilters
) -> list[sqlite3.Row]:
    extra_where: list[str] = []
    params: list[Any] = [query]
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " AND " + " AND ".join(extra_where)
    sql = f"""
        SELECT m.*, bm25(merger_content) AS rank
        FROM merger_content
        JOIN mergers m ON m.merger_id = merger_content.merger_id
        WHERE merger_content MATCH ?{where}
        ORDER BY rank
        LIMIT ?
    """
    params.append(filters.limit)
    return conn.execute(sql, params).fetchall()


def list_mergers(
    conn: sqlite3.Connection, filters: SearchFilters, sort: str = "date-desc"
) -> list[sqlite3.Row]:
    extra_where: list[str] = []
    params: list[Any] = []
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " WHERE " + " AND ".join(extra_where)
    order = {
        "date-asc": "m.notification_date ASC",
        "date-desc": "m.notification_date DESC",
        "name": "m.merger_name ASC",
        "duration": (
            "(julianday(m.determination_date) - julianday(m.notification_date)) DESC"
        ),
    }.get(sort, "m.notification_date DESC")
    sql = f"SELECT m.* FROM mergers m{where} ORDER BY {order} LIMIT ?"
    params.append(filters.limit)
    return conn.execute(sql, params).fetchall()


def normalize_merger_id(merger_id: str) -> str:
    """Accept lowercase variants and space separators (e.g. ``mn 01016``)."""
    return merger_id.strip().upper().replace(" ", "-")


def get_merger(conn: sqlite3.Connection, merger_id: str) -> Merger | None:
    merger_id = normalize_merger_id(merger_id)
    row = conn.execute(
        "SELECT raw_json FROM mergers WHERE merger_id = ?", (merger_id,)
    ).fetchone()
    if not row:
        return None
    return Merger.from_dict(json.loads(row["raw_json"]))


def get_questionnaire(
    conn: sqlite3.Connection, merger_id: str
) -> Questionnaire | None:
    merger_id = normalize_merger_id(merger_id)
    row = conn.execute(
        "SELECT * FROM questionnaires WHERE merger_id = ?", (merger_id,)
    ).fetchone()
    if not row:
        return None
    merger_row = conn.execute(
        "SELECT merger_name FROM mergers WHERE merger_id = ?", (merger_id,)
    ).fetchone()
    merger_name = merger_row["merger_name"] if merger_row else None
    questions = json.loads(row["raw_json"])
    return Questionnaire(
        merger_id=merger_id,
        merger_name=merger_name,
        deadline=row["deadline"],
        questions=questions,
        questions_count=row["questions_count"],
    )


def list_questionnaires(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT q.merger_id, q.deadline, q.questions_count, m.merger_name
        FROM questionnaires q
        LEFT JOIN mergers m ON m.merger_id = q.merger_id
        ORDER BY q.deadline DESC NULLS LAST, q.merger_id DESC
        """
    ).fetchall()


def search_questions(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[sqlite3.Row]:
    sql = """
        SELECT qc.merger_id, qc.question_number, qc.question_text,
               m.merger_name,
               bm25(questionnaire_content) AS rank
        FROM questionnaire_content qc
        LEFT JOIN mergers m ON m.merger_id = qc.merger_id
        WHERE questionnaire_content MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    return conn.execute(sql, (query, limit)).fetchall()


def industry_breakdown(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT industries_text, is_waiver, determination, phase FROM mergers"
    ).fetchall()
    agg: dict[str, dict[str, int]] = {}
    for row in rows:
        names = [
            n.strip()
            for n in (row["industries_text"] or "").split(";")
            if n.strip()
        ]
        for name in names:
            entry = agg.setdefault(
                name,
                {"notifications": 0, "waivers": 0, "approved": 0, "phase2": 0},
            )
            if row["is_waiver"]:
                entry["waivers"] += 1
            else:
                entry["notifications"] += 1
            if (row["determination"] or "").lower() == "approved":
                entry["approved"] += 1
            if row["phase"] == 2:
                entry["phase2"] += 1
    return [
        {"industry": name, **counts}
        for name, counts in sorted(
            agg.items(),
            key=lambda kv: kv[1]["notifications"] + kv[1]["waivers"],
            reverse=True,
        )
    ]


def mergers_by_industry(
    conn: sqlite3.Connection, industry: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT * FROM mergers
        WHERE LOWER(industries_text) LIKE ?
        ORDER BY notification_date DESC
        """,
        (f"%{industry.lower()}%",),
    ).fetchall()


def count_mergers(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM mergers").fetchone()
    return int(row["n"]) if row else 0


def iter_all_mergers(conn: sqlite3.Connection) -> Iterable[Merger]:
    for row in conn.execute("SELECT raw_json FROM mergers"):
        yield Merger.from_dict(json.loads(row["raw_json"]))


def mergers_by_party(
    conn: sqlite3.Connection,
    name: str,
    filters: SearchFilters | None = None,
    role: str | None = None,
) -> list[sqlite3.Row]:
    """Return mergers where the acquirer or target name contains ``name``.

    ``role`` may be "acquirer", "target", or ``None`` for either side.
    """
    filters = filters or SearchFilters(limit=100)
    extra_where: list[str] = []
    params: list[Any] = []
    _apply_filters(filters, extra_where, params)

    needle = f"%{name.lower()}%"
    if role == "acquirer":
        extra_where.append("LOWER(m.acquirers_text) LIKE ?")
        params.append(needle)
    elif role == "target":
        extra_where.append("LOWER(m.targets_text) LIKE ?")
        params.append(needle)
    else:
        extra_where.append(
            "(LOWER(m.acquirers_text) LIKE ? OR LOWER(m.targets_text) LIKE ?)"
        )
        params.extend([needle, needle])

    where = " WHERE " + " AND ".join(extra_where)
    sql = (
        f"SELECT m.* FROM mergers m{where} "
        "ORDER BY m.notification_date DESC LIMIT ?"
    )
    params.append(filters.limit)
    return conn.execute(sql, params).fetchall()


def search_regex(
    conn: sqlite3.Connection,
    pattern: re.Pattern[str],
    filters: SearchFilters,
) -> list[sqlite3.Row]:
    """Scan indexed merger text with a Python regex.

    Bypasses FTS — applies structured filters via SQL, then tests the
    compiled pattern against the content columns. Ordering follows
    ``notification_date DESC``.
    """
    extra_where: list[str] = []
    params: list[Any] = []
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " WHERE " + " AND ".join(extra_where)
    sql = f"""
        SELECT m.*, mc.merger_description, mc.determination_reasons,
               mc.determination_overlap, mc.all_determination_text
        FROM mergers m
        LEFT JOIN merger_content mc ON mc.merger_id = m.merger_id
        {where}
        ORDER BY m.notification_date DESC
    """
    rows = conn.execute(sql, params).fetchall()

    matches: list[sqlite3.Row] = []
    for row in rows:
        haystack_parts = [
            row["merger_name"] or "",
            row["acquirers_text"] or "",
            row["targets_text"] or "",
            row["industries_text"] or "",
            row["merger_description"] or "",
            row["determination_reasons"] or "",
            row["determination_overlap"] or "",
            row["all_determination_text"] or "",
        ]
        haystack = "\n".join(haystack_parts)
        if pattern.search(haystack):
            matches.append(row)
            if len(matches) >= filters.limit:
                break
    return matches
