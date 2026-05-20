"""Tests for the interactive ``mergers browse`` TUI."""

from __future__ import annotations

import re

import pytest

from typer.testing import CliRunner

from mergers import db
from mergers.cli import app
from mergers.tui import (
    HelpScreen,
    MergerListItem,
    MergersBrowseApp,
    ParsedQuery,
    build_filters,
    capture_merger_detail,
    fetch_rows,
    parse_filter_input,
    row_label,
)


runner = CliRunner()


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


# ---- parse_filter_input -----------------------------------------------------


def test_parse_filter_input_empty():
    parsed = parse_filter_input("")
    assert parsed == ParsedQuery(query="", kwargs={})


def test_parse_filter_input_pulls_known_keys():
    parsed = parse_filter_input("outcome:approved industry:beverage warehouse")
    assert parsed.kwargs == {"outcome": "approved", "industry": "beverage"}
    assert parsed.query == "warehouse"


def test_parse_filter_input_quoted_values():
    parsed = parse_filter_input('acquirer:"Asahi Holdings" lease')
    assert parsed.kwargs == {"acquirer": "Asahi Holdings"}
    assert parsed.query == "lease"


def test_parse_filter_input_unknown_keys_kept_as_query():
    parsed = parse_filter_input("foo:bar genuine query")
    assert parsed.kwargs == {}
    assert parsed.query == "foo:bar genuine query"


def test_parse_filter_input_handles_unbalanced_quotes():
    # shlex.split raises on the dangling quote; we fall back to whitespace
    # split so the input is still usable.
    parsed = parse_filter_input('target:warehouse "open ended')
    assert parsed.kwargs == {"target": "warehouse"}
    assert '"open' in parsed.query
    assert "ended" in parsed.query


# ---- build_filters ----------------------------------------------------------


def test_build_filters_drops_invalid_outcome():
    filters = build_filters({"outcome": "bogus"})
    assert filters.outcome is None


def test_build_filters_phase_zero_keeps_waiver_semantics():
    filters = build_filters({"phase": "0"})
    assert filters.phase == 0


def test_build_filters_waiver_truthy():
    assert build_filters({"waiver": "yes"}).waiver is True
    assert build_filters({"waiver": "no"}).waiver is False
    assert build_filters({"waiver": "maybe"}).waiver is None


def test_build_filters_year_invalid_dropped():
    assert build_filters({"year": "not-a-year"}).year is None
    assert build_filters({"year": "2025"}).year == 2025


# ---- fetch_rows + row_label -------------------------------------------------


def test_fetch_rows_list_path(populated_db):
    conn = db.connect()
    try:
        rows, total, snippets = fetch_rows(conn, ParsedQuery(query="", kwargs={}))
    finally:
        conn.close()
    assert total == 4
    assert {r["merger_id"] for r in rows} == {
        "MN-01016",
        "MN-01017",
        "MN-01018",
        "MN-01019",
    }
    assert snippets == {}


def test_fetch_rows_with_filter(populated_db):
    conn = db.connect()
    try:
        rows, total, _ = fetch_rows(
            conn, ParsedQuery(query="", kwargs={"outcome": "approved"})
        )
    finally:
        conn.close()
    determinations = {(r["determination"] or "").lower() for r in rows}
    assert determinations == {"approved"}
    assert total == len(rows)


def test_fetch_rows_search_path_populates_snippets(populated_db):
    conn = db.connect()
    try:
        rows, total, snippets = fetch_rows(
            conn, ParsedQuery(query="warehouse", kwargs={})
        )
    finally:
        conn.close()
    assert total >= 1
    assert any("warehouse" in (s or "").lower() for s in snippets.values())


def test_row_label_includes_id_and_outcome(populated_db):
    conn = db.connect()
    try:
        rows, _, _ = fetch_rows(conn, ParsedQuery(query="", kwargs={}))
        row = next(r for r in rows if r["merger_id"] == "MN-01016")
        label = row_label(row)
    finally:
        conn.close()
    plain = label.plain
    assert "MN-01016" in plain
    assert "Asahi" in plain
    assert "Approved" in plain


def test_row_label_includes_snippet_when_provided(populated_db):
    conn = db.connect()
    try:
        rows, _, snippets = fetch_rows(
            conn, ParsedQuery(query="warehouse", kwargs={})
        )
        row = rows[0]
        label = row_label(row, snippets.get(row["merger_id"]))
    finally:
        conn.close()
    assert "\n" in label.plain  # snippet rendered on its own line
    assert "warehouse" in label.plain.lower()


# ---- capture_merger_detail --------------------------------------------------


def test_capture_merger_detail_renders_sections(populated_db):
    conn = db.connect()
    try:
        text = capture_merger_detail("MN-01016", conn=conn)
    finally:
        conn.close()
    plain = _strip_ansi(text.plain)
    assert "MN-01016" in plain
    assert "Asahi" in plain
    assert "Parties" in plain
    assert "Description" in plain
    assert "Reasons for determination" in plain or "Determination" in plain


def test_capture_merger_detail_unknown_id(populated_db):
    conn = db.connect()
    try:
        text = capture_merger_detail("MN-99999", conn=conn)
    finally:
        conn.close()
    assert "not found" in text.plain.lower()


def test_capture_merger_detail_no_connection():
    text = capture_merger_detail("MN-01016", conn=None)
    assert text.plain == ""


# ---- browse CLI command -----------------------------------------------------


def test_browse_command_errors_without_textual(populated_db, monkeypatch):
    """If ``textual`` cannot be imported, ``browse`` should exit non-zero
    with an actionable message instead of crashing.

    Simulated by injecting a sentinel into ``sys.modules`` so that
    ``from . import tui`` raises ``ImportError`` without us having to
    actually uninstall textual.
    """
    import sys
    import mergers as mergers_pkg

    # `from . import tui` first checks the package's namespace, then
    # sys.modules. Remove both so the import resolves to a None sentinel
    # and raises ImportError, mimicking textual not being installed.
    monkeypatch.delitem(sys.modules, "mergers.tui", raising=False)
    monkeypatch.setitem(sys.modules, "mergers.tui", None)
    monkeypatch.delattr(mergers_pkg, "tui", raising=False)

    result = runner.invoke(app, ["browse"])
    assert result.exit_code == 1
    assert "interactive browser requires" in result.output.lower()


# ---- Textual Pilot integration ---------------------------------------------


@pytest.mark.asyncio
async def test_browse_app_populates_and_filters(populated_db):
    """End-to-end smoke test using Textual's Pilot harness."""
    app_instance = MergersBrowseApp()
    async with app_instance.run_test() as pilot:
        await pilot.pause()
        list_view = app_instance.query_one("#results")
        assert len(list_view.children) == 4

        # Type a filter that should narrow to one row.
        filter_input = app_instance.query_one("#filter")
        filter_input.focus()
        await pilot.pause()
        # Setting the value via the widget triggers the Changed event.
        filter_input.value = "outcome:phase2"
        await pilot.pause()

        # Only MN-01017 is in Phase 2 in the fixtures.
        ids = [
            child.merger_id
            for child in list_view.children
            if isinstance(child, MergerListItem)
        ]
        assert ids == ["MN-01017"]


@pytest.mark.asyncio
async def test_browse_app_help_screen_toggle(populated_db):
    app_instance = MergersBrowseApp()
    async with app_instance.run_test() as pilot:
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app_instance.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app_instance.screen, HelpScreen)


@pytest.mark.asyncio
async def test_browse_app_detail_updates_on_highlight(populated_db):
    app_instance = MergersBrowseApp()
    async with app_instance.run_test() as pilot:
        await pilot.pause()
        list_view = app_instance.query_one("#results")
        list_view.index = 1  # second row
        await pilot.pause()
        detail = app_instance.query_one("#detail")
        rendered = detail.render()
        plain = _strip_ansi(rendered.plain if hasattr(rendered, "plain") else str(rendered))
        assert "MN-" in plain
