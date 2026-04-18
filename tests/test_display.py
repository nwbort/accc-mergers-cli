"""Tests for display helpers and CLI integration."""

from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from mergers import db, display
from mergers.cli import app
from mergers.models import Merger


runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_format_date_handles_iso():
    assert display.format_date("2025-09-12T00:00:00+10:00") == "Sep 2025"


def test_format_date_none():
    assert display.format_date(None) == "—"


def test_outcome_style_colours():
    assert display.outcome_style("Approved") == "green"
    assert display.outcome_style("Denied") == "red"
    assert display.outcome_style("Pending review") == "yellow"


def test_show_merger_contains_sections(populated_db, capsys):
    conn = db.connect()
    try:
        merger = db.get_merger(conn, "MN-01016")
        q = db.get_questionnaire(conn, "MN-01016")
    finally:
        conn.close()
    assert isinstance(merger, Merger)
    display.show_merger(merger, q, section="all")
    output = _strip_ansi(capsys.readouterr().out)
    assert "MN-01016" in output
    assert "Reasons for determination" in output
    assert "sufficient alternative logistics providers" in output
    assert "Parties" in output
    assert "Questionnaire" in output
    assert "routine clearance" in output


def test_cli_search_json(populated_db):
    result = runner.invoke(
        app, ["search", "warehouse beverage", "--json", "--limit", "5"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert any(r["merger_id"] == "MN-01016" for r in payload)


def test_cli_show_json(populated_db):
    result = runner.invoke(app, ["show", "MN-01016", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["merger_id"] == "MN-01016"


def test_cli_show_unknown_id(populated_db):
    result = runner.invoke(app, ["show", "MN-99999"])
    assert result.exit_code != 0


def test_cli_list_phase2(populated_db):
    result = runner.invoke(app, ["list", "--phase", "2", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["merger_id"] for r in payload] == ["MN-01017"]


def test_cli_industries_json(populated_db):
    result = runner.invoke(app, ["industries", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert any(r["industry"] == "Fuel Retailing" for r in payload)


def test_cli_questions_for_merger(populated_db):
    result = runner.invoke(app, ["questions", "MN-01016", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["questions_count"] == 3
    assert payload["merger_id"] == "MN-01016"


def test_cli_questions_search(populated_db):
    result = runner.invoke(
        app, ["questions", "--search", "geographic market", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload
    assert payload[0]["merger_id"] == "MN-01016"


def test_phase2_pending_db_determination_is_null(populated_db):
    """MN-01017 is in Phase 2 with no final result — DB determination must be NULL."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT determination FROM mergers WHERE merger_id = 'MN-01017'"
        ).fetchone()
    finally:
        conn.close()
    assert row["determination"] is None


def test_outcome_phase2_no_determination_is_none():
    """In Phase 2 with only a phase_1 referral → outcome() is None (Pending)."""
    from mergers.models import Merger
    m = Merger(
        merger_id="TEST-002",
        merger_name="Test",
        stage="Phase 2",
        phase_1_determination="Phase 2 referral",
        phase_2_determination=None,
        accc_determination=None,
    )
    assert m.outcome() is None


def test_outcome_phase2_cleared_returns_determination():
    """In Phase 2 with a phase_2_determination → outcome() returns that determination."""
    from mergers.models import Merger
    for result in ("Approved", "Denied"):
        m = Merger(
            merger_id="TEST-003",
            merger_name="Test",
            stage="Phase 2",
            phase_1_determination="Phase 2 referral",
            phase_2_determination=result,
            accc_determination=None,
        )
        assert m.outcome() == result


def test_outcome_phase1_referred_to_phase2_preserves_determination():
    """A phase 1 merger that was referred but NOT yet in phase 2 keeps its determination."""
    from mergers.models import Merger
    m = Merger(
        merger_id="TEST-001",
        merger_name="Test",
        stage="Phase 1",
        phase_1_determination="Referred to Phase 2",
    )
    assert m.outcome() == "Referred to Phase 2"


def test_cli_stats(populated_db):
    result = runner.invoke(app, ["stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["totals"]["total_mergers"] == 3


def test_cli_status_reports_version_and_counts(populated_db):
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Bundle version" in output
    assert "Generated at" in output
    assert "Mergers" in output
    assert "3" in output


def test_cli_status_without_cache(temp_cache):
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    assert "No local cache" in _strip_ansi(result.stdout)
