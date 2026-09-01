"""SQLite + FTS5 storage and queries for the ACCC merger cache."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Merger, Nocc, NoccBlock, NoccSection, Questionnaire

# Matches FTS5 operator tokens or special characters that indicate the caller
# has already written a structured FTS5 expression.  When absent the query is
# treated as a plain phrase and wrapped in FTS5 double-quotes.
_FTS5_OPERATOR_RE = re.compile(r'\b(?:OR|AND|NOT|NEAR)\b|["*{(^]')

# Maps --section names to the FTS5 column(s) to restrict the query to.
_SECTION_FTS_COLUMNS: dict[str, str] = {
    "reasons": "determination_reasons",
    "overlap": "determination_overlap",
    "description": "merger_description",
    "parties": "merger_name acquirers_text targets_text",
}

# Maps --section names to the row columns used for regex haystack construction.
_SECTION_REGEX_FIELDS: dict[str, list[str]] = {
    "reasons": ["determination_reasons"],
    "overlap": ["determination_overlap"],
    "description": ["merger_description"],
    "parties": ["merger_name", "acquirers_text", "targets_text"],
}


def _build_fts_query(query: str, section: str | None = None) -> str:
    """Return an FTS5 MATCH expression for *query*, optionally column-scoped.

    The query is passed through as-is so that FTS5 operator syntax (OR, AND,
    NEAR, phrase quotes, etc.) works naturally.  Callers wanting exact phrase
    matching should wrap the query in FTS5 double-quotes themselves, e.g.
    ``'"conglomerate effects"'``.

    If *section* is given, the query is prefixed with an FTS5 column filter
    so only the relevant content column(s) are searched.
    """
    fts_q = query
    if section and section != "all":
        cols = _SECTION_FTS_COLUMNS.get(section)
        if cols:
            # Wrap in parens so the column filter covers the entire expression,
            # not just the first token.
            fts_q = f"{{{cols}}}:({fts_q})"
    return fts_q


def _regex_haystack(row: sqlite3.Row, section: str | None) -> str:
    """Build the text string that a regex pattern should be tested against."""
    if section and section != "all":
        fields = _SECTION_REGEX_FIELDS.get(section, [])
        return "\n".join(row[f] or "" for f in fields if f in row.keys())
    return "\n".join(
        row[f] or ""
        for f in (
            "merger_name",
            "acquirers_text",
            "targets_text",
            "industries_text",
            "merger_description",
            "determination_reasons",
            "determination_overlap",
            "all_determination_text",
        )
        if f in row.keys()
    )


# Sentinel used to mark a missing column (sqlite3.Row doesn't support `in`).
_MISSING = object()


def extract_regex_snippet(
    row: sqlite3.Row,
    pattern: re.Pattern[str],
    section: str | None = None,
    context_chars: int = 150,
) -> str | None:
    """Return a short excerpt around the first match of *pattern* in *row*.

    Returns ``None`` if the pattern does not match the relevant haystack.
    Matches are wrapped with ``⟪`` / ``⟫`` so callers can highlight them.
    """
    haystack = _regex_haystack(row, section)
    m = pattern.search(haystack)
    if not m:
        return None
    start = max(0, m.start() - context_chars)
    end = min(len(haystack), m.end() + context_chars)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(haystack) else ""
    before = haystack[start : m.start()]
    matched = haystack[m.start() : m.end()]
    after = haystack[m.end() : end]
    # Strip leading/trailing whitespace from boundary text
    if prefix:
        before = before.lstrip()
    if suffix:
        after = after.rstrip()
    return f"{prefix}{before}⟪{matched}⟫{after}{suffix}"

CACHE_DIR = Path.home() / ".accc-mergers"
DB_PATH = CACHE_DIR / "db.sqlite"
LAST_SYNC_PATH = CACHE_DIR / "last_sync.txt"
STALE_DAYS = 7

# Bumped whenever the upstream-published SQLite schema changes in a way that
# this CLI can no longer read. The sync flow refuses any manifest whose
# ``schema_version`` doesn't match this constant.
#
# v2 added under_appeal, has_judicial_review and phase_1_estimate_days
# columns to `mergers` (see SearchFilters.under_appeal/has_judicial_review
# and Merger.phase_1_estimate).
SCHEMA_VERSION = 2


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    ensure_cache_dir()
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def read_schema_version(conn: sqlite3.Connection) -> int | None:
    """Return the ``schema_version`` recorded in the DB's ``meta`` table."""
    try:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return None


def get_stats(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT value FROM stats WHERE key = 'stats'").fetchone()
    if not row:
        return None
    return json.loads(row["value"])


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
    has_related: bool | None = None
    acquirer: str | None = None
    target: str | None = None
    under_appeal: bool | None = None
    has_judicial_review: bool | None = None
    limit: int = 10
    section: str | None = None  # restrict search to a content section


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
    if filters.has_related is True:
        extra_where.append(
            "m.related_merger_id IS NOT NULL AND m.related_merger_id != ''"
        )
    elif filters.has_related is False:
        extra_where.append(
            "(m.related_merger_id IS NULL OR m.related_merger_id = '')"
        )
    if filters.acquirer:
        extra_where.append("LOWER(m.acquirers_text) LIKE ?")
        params.append(f"%{filters.acquirer.lower()}%")
    if filters.target:
        extra_where.append("LOWER(m.targets_text) LIKE ?")
        params.append(f"%{filters.target.lower()}%")
    if filters.under_appeal is True:
        extra_where.append("m.under_appeal = 1")
    elif filters.under_appeal is False:
        extra_where.append("m.under_appeal = 0")
    if filters.has_judicial_review is True:
        extra_where.append("m.has_judicial_review = 1")
    elif filters.has_judicial_review is False:
        extra_where.append("m.has_judicial_review = 0")


def search(
    conn: sqlite3.Connection,
    query: str,
    filters: SearchFilters,
    *,
    snippets: bool = False,
) -> list[sqlite3.Row]:
    fts_q = _build_fts_query(query, filters.section)
    extra_where: list[str] = []
    params: list[Any] = [fts_q]
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " AND " + " AND ".join(extra_where)
    snippet_col = (
        ", snippet(merger_content, -1, '⟪', '⟫', '…', 20) AS fts_snippet"
        if snippets
        else ""
    )
    sql = f"""
        SELECT m.*, bm25(merger_content) AS rank{snippet_col}
        FROM merger_content
        JOIN mergers m ON m.merger_id = merger_content.merger_id
        WHERE merger_content MATCH ?{where}
        ORDER BY rank
        LIMIT ?
    """
    params.append(filters.limit)
    return conn.execute(sql, params).fetchall()


def count_search(conn: sqlite3.Connection, query: str, filters: SearchFilters) -> int:
    """Return the total number of FTS matches for *query* (ignores limit)."""
    fts_q = _build_fts_query(query, filters.section)
    extra_where: list[str] = []
    params: list[Any] = [fts_q]
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " AND " + " AND ".join(extra_where)
    sql = f"""
        SELECT COUNT(*) AS n
        FROM merger_content
        JOIN mergers m ON m.merger_id = merger_content.merger_id
        WHERE merger_content MATCH ?{where}
    """
    row = conn.execute(sql, params).fetchone()
    return int(row["n"]) if row else 0


def count_list_mergers(conn: sqlite3.Connection, filters: SearchFilters) -> int:
    """Return the total number of mergers matching *filters* (ignores limit)."""
    extra_where: list[str] = []
    params: list[Any] = []
    _apply_filters(filters, extra_where, params)
    where = ""
    if extra_where:
        where = " WHERE " + " AND ".join(extra_where)
    row = conn.execute(f"SELECT COUNT(*) AS n FROM mergers m{where}", params).fetchone()
    return int(row["n"]) if row else 0


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


_MERGER_ID_RE = re.compile(r"^([A-Z]+)[\s\-_]*(\d+)$")


def normalize_merger_id(merger_id: str) -> str:
    """Accept lowercase variants and flexible separators (e.g. ``mn 01016``,
    ``mn-01016``, ``MN45006``)."""
    cleaned = merger_id.strip().upper()
    match = _MERGER_ID_RE.match(cleaned)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return cleaned.replace(" ", "-")


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
    all_q_raw = row["all_questionnaires_json"]
    all_q = json.loads(all_q_raw) if all_q_raw else []
    return Questionnaire(
        merger_id=merger_id,
        merger_name=merger_name,
        deadline=row["deadline"],
        questions=questions,
        questions_count=row["questions_count"],
        deadline_iso=row["deadline_iso"],
        file_name=row["file_name"],
        all_questionnaires=all_q,
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


def _nocc_from_row(row: sqlite3.Row, merger_name: str | None = None) -> Nocc:
    payload = json.loads(row["raw_json"]) if row["raw_json"] else {}
    sections = [
        NoccSection(
            number=s.get("number"),
            title=s.get("title"),
            blocks=[NoccBlock.from_dict(b) for b in (s.get("blocks") or [])],
        )
        for s in (payload.get("sections") or [])
    ]
    return Nocc(
        merger_id=row["merger_id"],
        matter_id=row["matter_id"],
        date=row["date"],
        date_iso=row["date_iso"],
        document_type=row["document_type"],
        file_name=row["file_name"],
        file_path=row["file_path"],
        sections=sections,
        merger_name=merger_name,
    )


def get_nocc(conn: sqlite3.Connection, merger_id: str) -> Nocc | None:
    merger_id = normalize_merger_id(merger_id)
    row = conn.execute(
        "SELECT * FROM noccs WHERE merger_id = ?", (merger_id,)
    ).fetchone()
    if not row:
        return None
    merger_row = conn.execute(
        "SELECT merger_name FROM mergers WHERE merger_id = ?", (merger_id,)
    ).fetchone()
    merger_name = merger_row["merger_name"] if merger_row else None
    return _nocc_from_row(row, merger_name=merger_name)


def list_noccs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT n.merger_id, n.date, n.date_iso, n.document_type,
               n.file_name, m.merger_name
        FROM noccs n
        LEFT JOIN mergers m ON m.merger_id = n.merger_id
        ORDER BY n.date_iso DESC NULLS LAST, n.merger_id DESC
        """
    ).fetchall()


def search_noccs(
    conn: sqlite3.Connection, query: str, limit: int = 20
) -> list[sqlite3.Row]:
    sql = """
        SELECT nc.merger_id, nc.section_number, nc.section_title,
               nc.block_number, nc.block_text,
               m.merger_name,
               bm25(nocc_content) AS rank
        FROM nocc_content nc
        LEFT JOIN mergers m ON m.merger_id = nc.merger_id
        WHERE nocc_content MATCH ?
        ORDER BY rank
        LIMIT ?
    """
    return conn.execute(sql, (query, limit)).fetchall()


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


STATS_AXES = ("year", "industry", "acquirer", "outcome", "phase")


def stats_by_axis(
    conn: sqlite3.Connection, axis: str, limit: int = 25
) -> list[dict[str, Any]]:
    """Group merger counts by a single axis.

    Returns a list of ``{"key": str, "notifications": int, "waivers": int,
    "approved": int, "phase2": int, "denied": int, "total": int}`` rows,
    sorted by ``total`` desc.  ``industry`` and ``acquirer`` rows are split
    on the semicolon separator used in the source data; a merger that lists
    two industries contributes to both buckets.
    """
    if axis not in STATS_AXES:
        raise ValueError(f"Unknown axis: {axis!r}")

    rows = conn.execute(
        "SELECT notification_date, industries_text, acquirers_text, "
        "determination, phase, is_waiver FROM mergers"
    ).fetchall()

    def _empty() -> dict[str, int]:
        return {
            "notifications": 0,
            "waivers": 0,
            "approved": 0,
            "denied": 0,
            "phase2": 0,
            "total": 0,
        }

    agg: dict[str, dict[str, int]] = {}

    def _bump(key: str, row: sqlite3.Row) -> None:
        entry = agg.setdefault(key, _empty())
        entry["total"] += 1
        if row["is_waiver"]:
            entry["waivers"] += 1
        else:
            entry["notifications"] += 1
        outcome = (row["determination"] or "").lower()
        if outcome == "approved":
            entry["approved"] += 1
        elif outcome in ("denied", "not approved"):
            entry["denied"] += 1
        if row["phase"] == 2:
            entry["phase2"] += 1

    for row in rows:
        if axis == "year":
            nd = row["notification_date"] or ""
            key = nd[:4] if len(nd) >= 4 and nd[:4].isdigit() else "unknown"
            _bump(key, row)
        elif axis == "industry":
            names = [
                n.strip()
                for n in (row["industries_text"] or "").split(";")
                if n.strip()
            ]
            for name in names or ["(unknown)"]:
                _bump(name, row)
        elif axis == "acquirer":
            names = [
                n.strip()
                for n in (row["acquirers_text"] or "").split(";")
                if n.strip()
            ]
            for name in names or ["(unknown)"]:
                _bump(name, row)
        elif axis == "outcome":
            key = row["determination"] or "Pending"
            _bump(key, row)
        elif axis == "phase":
            if row["is_waiver"]:
                key = "Waiver"
            elif row["phase"] is None:
                key = "Unspecified"
            else:
                key = f"Phase {row['phase']}"
            _bump(key, row)

    ordered = sorted(
        agg.items(),
        key=lambda kv: (-kv[1]["total"], kv[0]) if axis != "year" else (kv[0],),
        reverse=(axis == "year"),
    )
    if axis == "year":
        ordered = sorted(agg.items(), key=lambda kv: kv[0], reverse=True)
    return [{"key": k, **v} for k, v in ordered[:limit]]


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


def count_mergers_by_party(
    conn: sqlite3.Connection,
    name: str,
    filters: SearchFilters | None = None,
    role: str | None = None,
) -> int:
    """Return the total number of party-name matches (ignores limit)."""
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
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM mergers m{where}", params
    ).fetchone()
    return int(row["n"]) if row else 0


def related_mergers(
    conn: sqlite3.Connection, merger_id: str
) -> list[sqlite3.Row]:
    """Return mergers linked to ``merger_id`` via ``related_merger``.

    Includes the merger ``merger_id`` itself points at (forward link, e.g.
    a waiver pointing to the notification it was refiled as) and any
    mergers that point back at ``merger_id`` (reverse links). Excludes
    ``merger_id`` itself.
    """
    merger_id = normalize_merger_id(merger_id)
    forward_row = conn.execute(
        "SELECT related_merger_id FROM mergers WHERE merger_id = ?",
        (merger_id,),
    ).fetchone()
    forward_id = (
        forward_row["related_merger_id"]
        if forward_row and forward_row["related_merger_id"]
        else None
    )

    ids: list[str] = []
    if forward_id and forward_id != merger_id:
        ids.append(forward_id)
    reverse_rows = conn.execute(
        "SELECT merger_id FROM mergers WHERE related_merger_id = ?",
        (merger_id,),
    ).fetchall()
    for row in reverse_rows:
        if row["merger_id"] != merger_id and row["merger_id"] not in ids:
            ids.append(row["merger_id"])

    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    sql = f"SELECT * FROM mergers WHERE merger_id IN ({placeholders})"
    rows = conn.execute(sql, ids).fetchall()
    by_id = {row["merger_id"]: row for row in rows}
    return [by_id[i] for i in ids if i in by_id]


def search_regex(
    conn: sqlite3.Connection,
    pattern: re.Pattern[str],
    filters: SearchFilters,
) -> tuple[list[sqlite3.Row], int]:
    """Scan indexed merger text with a Python regex.

    Bypasses FTS — applies structured filters via SQL, then tests the
    compiled pattern against the content columns. Ordering follows
    ``notification_date DESC``.

    Returns ``(limited_results, total_match_count)`` so callers can detect
    truncation without a second scan.
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
        haystack = _regex_haystack(row, filters.section)
        if pattern.search(haystack):
            matches.append(row)
    total = len(matches)
    return matches[: filters.limit], total
