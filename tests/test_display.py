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


def test_cli_list_phase0_means_waivers(populated_db):
    result = runner.invoke(app, ["list", "--phase", "0", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["merger_id"] for r in payload] == ["MN-01019"]


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
    assert "4" in output


def test_cli_status_without_cache(temp_cache):
    result = runner.invoke(app, ["status"])
    assert result.exit_code != 0
    assert "No local cache" in _strip_ansi(result.stdout)


def test_cli_timeline_renders_events(populated_db):
    result = runner.invoke(app, ["timeline", "MN-01016"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "MN-01016" in output
    assert "Timeline" in output
    assert "Notification" in output
    assert "Determination" in output


def test_cli_timeline_json(populated_db):
    result = runner.invoke(app, ["timeline", "MN-01016", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["merger_id"] == "MN-01016"
    assert payload["notification_date"]
    assert payload["events"]
    labels = [e["label"] for e in payload["events"]]
    assert any("Notification" in label for label in labels)


def test_cli_timeline_unknown_id(populated_db):
    result = runner.invoke(app, ["timeline", "MN-99999"])
    assert result.exit_code != 0


def test_timeline_extension_not_labelled_as_determination():
    """An 'extend the Phase 1 determination period' event is an extension, not a determination.

    Regression for MN-01019, where the 2025-11-06 period-extension event was
    mis-labelled as 'Phase 1 determination' because the title contains that
    substring. The actual Phase 1 decision came later (referral to Phase 2).
    """
    from mergers.models import Event, Merger
    m = Merger(
        merger_id="MN-01019",
        merger_name="Ampol – EG Australia",
        stage="Phase 2",
        effective_notification_datetime="2025-10-10T12:00:00Z",
        events=[
            Event(
                event_date="2025-11-06T12:00:00Z",
                title=(
                    "ACCC decided to extend the Phase 1 determination period "
                    "following receipt of extension request from Ampol, to "
                    "allow Ampol to provide additional information."
                ),
            ),
            Event(
                event_date="2026-01-20T12:00:00Z",
                title="ACCC decided notification is subject to Phase 2 review",
            ),
        ],
    )
    events = display.timeline_events(m)
    by_date = {e["date"][:10]: e["label"] for e in events}
    assert by_date["2025-11-06"] == "Phase 1 period extended"
    assert by_date["2026-01-20"] == "Referred to Phase 2"


def test_cli_party_finds_acquirer(populated_db):
    result = runner.invoke(app, ["party", "asahi", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["merger_id"] for r in payload] == ["MN-01016"]


def test_cli_party_role_filter(populated_db):
    # PharmaCo is only an acquirer; searching as target returns nothing.
    result = runner.invoke(
        app, ["party", "pharmaco", "--role", "target", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_cli_search_since_until(populated_db):
    result = runner.invoke(
        app,
        [
            "search",
            "acquisition OR lease OR portfolio OR fuel",
            "--since",
            "2025-01-01",
            "--until",
            "2025-06-30",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    ids = [r["merger_id"] for r in payload]
    assert "MN-01017" in ids
    assert "MN-01019" not in ids  # 2024 notification is excluded


def test_cli_search_rejects_bad_date(populated_db):
    result = runner.invoke(
        app, ["search", "warehouse", "--since", "yesterday"]
    )
    assert result.exit_code != 0
    assert "--since" in _strip_ansi(result.output)


def test_cli_search_regex(populated_db):
    result = runner.invoke(
        app, ["search", r"oncolog\w+", "--regex", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["merger_id"] for r in payload] == ["MN-01017"]


def test_cli_search_rejects_invalid_regex(populated_db):
    result = runner.invoke(app, ["search", "(unterminated", "--regex"])
    assert result.exit_code != 0
    assert "Invalid regex" in _strip_ansi(result.output)


def test_cli_install_completion_flag_exists():
    """add_completion=True exposes --install-completion on the root app."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--install-completion" in _strip_ansi(result.stdout)


def test_cli_questions_single_version_no_hint(populated_db):
    result = runner.invoke(app, ["questions", "MN-01016"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "questionnaire versions" not in output


def test_cli_questions_multi_version_shows_hint(populated_db):
    result = runner.invoke(app, ["questions", "MN-01017"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "2 questionnaire versions" in output
    assert "--all" in output


def test_cli_questions_version_number(populated_db):
    result = runner.invoke(app, ["questions", "MN-01017", "2"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    # Version 2 has the earlier deadline
    assert "2025-05-15" in output or "15 May 2025" in output
    assert "version 2 of 2" in output


def test_cli_questions_all_flag_renders_both(populated_db):
    result = runner.invoke(app, ["questions", "MN-01017", "--all"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Version 1 of 2" in output
    assert "Version 2 of 2" in output


def test_cli_questions_version_out_of_range(populated_db):
    result = runner.invoke(app, ["questions", "MN-01017", "99"])
    assert result.exit_code != 0
    assert "out of range" in _strip_ansi(result.stdout)


def test_cli_show_includes_related_merger(populated_db):
    result = runner.invoke(app, ["show", "MN-01019"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Refiled as" in output
    assert "MN-01016" in output


def test_cli_related_lists_forward_link(populated_db):
    result = runner.invoke(app, ["related", "MN-01019", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["related_merger"]["merger_id"] == "MN-01016"
    assert payload["related_merger"]["relationship"] == "refiled_as"
    assert [r["merger_id"] for r in payload["related"]] == ["MN-01016"]


def test_cli_related_lists_reverse_link(populated_db):
    result = runner.invoke(app, ["related", "MN-01016", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    # MN-01016 doesn't itself point anywhere, but MN-01019 points back at it.
    assert payload["related_merger"] is None
    assert [r["merger_id"] for r in payload["related"]] == ["MN-01019"]


def test_cli_related_unknown_id(populated_db):
    result = runner.invoke(app, ["related", "MN-99999"])
    assert result.exit_code != 0


def test_cli_list_has_related_filter(populated_db):
    result = runner.invoke(app, ["list", "--has-related", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["merger_id"] for r in payload] == ["MN-01019"]


def test_cli_noccs_for_merger(populated_db):
    result = runner.invoke(app, ["noccs", "MN-01017", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["merger_id"] == "MN-01017"
    assert payload["date_iso"] == "2026-03-01"
    assert payload["sections"][0]["title"] == "Introduction"


def test_cli_noccs_list(populated_db):
    result = runner.invoke(app, ["noccs", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert any(r["merger_id"] == "MN-01017" for r in payload)


def test_cli_noccs_search(populated_db):
    result = runner.invoke(app, ["noccs", "--search", "Phase 2 review", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload
    assert payload[0]["merger_id"] == "MN-01017"


def test_cli_noccs_unknown_merger(populated_db):
    result = runner.invoke(app, ["noccs", "MN-99999"])
    assert result.exit_code != 0


def test_cli_noccs_renders_text(populated_db):
    result = runner.invoke(app, ["noccs", "MN-01017"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Introduction" in output
    assert "Phase 2 review" in output
    assert "The acquirer" in output


def test_cli_show_includes_nocc_section(populated_db):
    result = runner.invoke(app, ["show", "MN-01017", "--section", "nocc"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Notice of Competition Concerns" in output
    assert "Introduction" in output


def test_cli_questions_shows_section_headers(populated_db):
    result = runner.invoke(app, ["questions", "MN-01016"])
    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.stdout)
    assert "Questions for all respondents" in output
