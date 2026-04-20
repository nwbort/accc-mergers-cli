"""Tests for search, filters, and industry helpers."""

from __future__ import annotations

import re

from mergers import db
from mergers.db import SearchFilters


def _ids(rows):
    return [r["merger_id"] for r in rows]


def test_search_finds_relevant_merger(populated_db):
    conn = db.connect()
    try:
        rows = db.search(conn, "warehouse beverage", SearchFilters(limit=10))
    finally:
        conn.close()
    assert "MN-01016" in _ids(rows)


def test_search_filter_outcome_approved(populated_db):
    conn = db.connect()
    try:
        rows = db.search(
            conn,
            "warehouse OR fuel OR pharmaceutical",
            SearchFilters(outcome="approved", limit=10),
        )
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01016" in ids
    assert "MN-01019" in ids
    assert "MN-01017" not in ids


def test_search_filter_industry(populated_db):
    conn = db.connect()
    try:
        rows = db.search(
            conn,
            "acquisition OR lease OR portfolio",
            SearchFilters(industry="fuel", limit=10),
        )
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01019"]


def test_search_filter_phase_two(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(phase=2, limit=10))
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01017"]


def test_search_filter_waiver(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(waiver=True, limit=10))
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01019"]


def test_search_filter_year(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(year=2024, limit=10))
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01019"]


def test_list_sort_name(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(limit=10), sort="name")
    finally:
        conn.close()
    ids = _ids(rows)
    assert ids[0] == "MN-01019"  # "Ampol" < "Asahi" < "PharmaCo"


def test_industry_breakdown_counts(populated_db):
    conn = db.connect()
    try:
        rows = db.industry_breakdown(conn)
    finally:
        conn.close()
    by_name = {r["industry"]: r for r in rows}
    assert by_name["Beverage Manufacturing"]["approved"] == 1
    assert by_name["Fuel Retailing"]["waivers"] == 1
    assert by_name["Pharmaceutical Product Manufacturing"]["phase2"] == 1


def test_get_merger_accepts_lowercase_and_space(populated_db):
    conn = db.connect()
    try:
        assert db.get_merger(conn, "mn-01016").merger_id == "MN-01016"
        assert db.get_merger(conn, "mn 01016").merger_id == "MN-01016"
        assert db.get_merger(conn, "  MN 01016  ").merger_id == "MN-01016"
    finally:
        conn.close()


def test_get_questionnaire_accepts_lowercase_and_space(populated_db):
    conn = db.connect()
    try:
        assert db.get_questionnaire(conn, "mn-01016").merger_id == "MN-01016"
        assert db.get_questionnaire(conn, "mn 01016").merger_id == "MN-01016"
    finally:
        conn.close()


def test_search_filter_since(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(
            conn, SearchFilters(since="2025-01-01", limit=10)
        )
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01016" in ids
    assert "MN-01017" in ids
    assert "MN-01019" not in ids  # 2024 notification is excluded


def test_search_filter_until(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(
            conn, SearchFilters(until="2025-06-01", limit=10)
        )
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01019" in ids   # 2024-11-11 is before cutoff
    assert "MN-01017" in ids   # 2025-05-01 is before cutoff
    assert "MN-01016" not in ids  # 2025-08-15 is after cutoff


def test_search_filter_since_and_until(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(
            conn,
            SearchFilters(since="2025-01-01", until="2025-06-01", limit=10),
        )
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01017" in ids
    assert "MN-01018" in ids  # 2025-03-10 is within range
    assert "MN-01016" not in ids
    assert "MN-01019" not in ids


def test_search_regex_matches(populated_db):
    conn = db.connect()
    try:
        pattern = re.compile(r"oncology", re.IGNORECASE)
        rows = db.search_regex(conn, pattern, SearchFilters(limit=10))
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01017"]


def test_search_regex_respects_filters(populated_db):
    conn = db.connect()
    try:
        pattern = re.compile(r".+", re.IGNORECASE)
        rows = db.search_regex(
            conn, pattern, SearchFilters(outcome="approved", limit=10)
        )
    finally:
        conn.close()
    ids = set(_ids(rows))
    assert ids == {"MN-01016", "MN-01019"}


def test_mergers_by_party_matches_either_role(populated_db):
    conn = db.connect()
    try:
        rows = db.mergers_by_party(conn, "asahi")
    finally:
        conn.close()
    assert _ids(rows) == ["MN-01016"]


def test_mergers_by_party_role_filter(populated_db):
    conn = db.connect()
    try:
        # PharmaCo is the acquirer; GenericsRUs is the target.
        acquirer_rows = db.mergers_by_party(conn, "pharmaco", role="acquirer")
        target_rows = db.mergers_by_party(conn, "pharmaco", role="target")
    finally:
        conn.close()
    assert _ids(acquirer_rows) == ["MN-01017"]
    assert target_rows == []


def test_search_filter_outcome_denied_matches_not_approved(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(outcome="denied", limit=10))
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01018" in ids


def test_search_filter_outcome_denied_excludes_approved(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(outcome="denied", limit=10))
    finally:
        conn.close()
    ids = _ids(rows)
    assert "MN-01016" not in ids
    assert "MN-01019" not in ids
    assert "MN-01017" not in ids


def test_search_filter_outcome_approved_excludes_not_approved(populated_db):
    conn = db.connect()
    try:
        rows = db.list_mergers(conn, SearchFilters(outcome="approved", limit=10))
    finally:
        conn.close()
    assert "MN-01018" not in _ids(rows)


def test_search_questions(populated_db):
    conn = db.connect()
    try:
        rows = db.search_questions(conn, "geographic market")
    finally:
        conn.close()
    assert any("geographic" in (r["question_text"] or "").lower() for r in rows)
    assert rows[0]["merger_id"] == "MN-01016"
