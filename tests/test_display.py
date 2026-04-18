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
    assert "Parties" in output
    assert "Questionnaire" in output


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


def test_cli_stats(populated_db):
    result = runner.invoke(app, ["stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["totals"]["total_mergers"] == 3
