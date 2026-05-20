"""Textual-based interactive browser for the merger register.

Launched by ``mergers browse``. Renders a list-on-left / detail-on-right
layout backed by the same ``db.search`` / ``db.list_mergers`` paths used
by the non-interactive CLI, so filter semantics stay in lockstep.
"""

from __future__ import annotations

import shlex
import webbrowser
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Iterator

from rich.console import Console
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from . import db, display, sync
from .db import SearchFilters

_FYI_BASE_URL = "https://mergers.fyi/mergers"
_LIST_LIMIT = 200
_CAPTURE_WIDTH = 100

_FILTER_KEYS = {
    "outcome",
    "industry",
    "acquirer",
    "target",
    "phase",
    "year",
    "since",
    "until",
    "waiver",
    "section",
}


@dataclass
class ParsedQuery:
    """Result of splitting a filter-input string into FTS query + kwargs."""

    query: str
    kwargs: dict[str, str]


def parse_filter_input(text: str) -> ParsedQuery:
    """Split ``outcome:approved year:2025 beverage`` into query and kwargs.

    Tokens of the form ``key:value`` where ``key`` is a recognised filter
    are pulled out; everything else is concatenated into the free-text
    query. Quotes are respected via ``shlex``.
    """
    text = (text or "").strip()
    if not text:
        return ParsedQuery(query="", kwargs={})
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    kwargs: dict[str, str] = {}
    query_parts: list[str] = []
    for tok in tokens:
        if ":" in tok:
            key, _, value = tok.partition(":")
            key_norm = key.strip().lower()
            value = value.strip()
            if key_norm in _FILTER_KEYS and value:
                kwargs[key_norm] = value
                continue
        query_parts.append(tok)
    return ParsedQuery(query=" ".join(query_parts), kwargs=kwargs)


def build_filters(kwargs: dict[str, str], limit: int = _LIST_LIMIT) -> SearchFilters:
    """Turn the kwargs from ``parse_filter_input`` into a ``SearchFilters``."""
    outcome = kwargs.get("outcome")
    if outcome:
        outcome = outcome.lower()
        if outcome not in {"approved", "denied", "phase2", "pending"}:
            outcome = None

    phase: int | None = None
    if "phase" in kwargs:
        try:
            phase_val = int(kwargs["phase"])
            if phase_val in (0, 1, 2):
                phase = phase_val
        except ValueError:
            phase = None

    year: int | None = None
    if "year" in kwargs:
        try:
            year = int(kwargs["year"])
        except ValueError:
            year = None

    waiver: bool | None = None
    if "waiver" in kwargs:
        lower = kwargs["waiver"].lower()
        if lower in {"true", "yes", "1", "y", "on"}:
            waiver = True
        elif lower in {"false", "no", "0", "n", "off"}:
            waiver = False

    section = kwargs.get("section")
    if section and section not in {"reasons", "overlap", "description", "parties"}:
        section = None

    return SearchFilters(
        outcome=outcome,
        industry=kwargs.get("industry"),
        phase=phase,
        waiver=waiver,
        year=year,
        since=kwargs.get("since"),
        until=kwargs.get("until"),
        acquirer=kwargs.get("acquirer"),
        target=kwargs.get("target"),
        limit=limit,
        section=section,
    )


def row_label(row: Any, snippet: str | None = None) -> Text:
    """Render the one-line label (plus optional snippet) shown in the list."""
    merger_id = row["merger_id"]
    name = row["merger_name"] or ""
    determination = row["determination"] or "Pending"
    style = display.outcome_style(determination)
    date = display.format_date(row["notification_date"])

    label = Text()
    label.append(f"{merger_id}  ", style="bold cyan")
    label.append(name)
    label.append("  ")
    label.append(determination, style=style)
    label.append(f"  {date}", style="dim")

    if snippet:
        label.append("\n  ")
        label.append_text(
            Text.from_markup(
                f"[dim italic]{display._render_snippet_markup(snippet)}[/]"
            )
        )
    return label


@contextmanager
def _override_console(new_console: Console) -> Iterator[None]:
    """Swap ``display._console`` so the existing renderers write to ours."""
    original = display._console
    display._console = new_console
    try:
        yield
    finally:
        display._console = original


def capture_merger_detail(
    merger_id: str, conn=None, *, width: int = _CAPTURE_WIDTH
) -> Text:
    """Render the full ``show_merger`` output for *merger_id* as a Rich Text.

    Reuses the existing display helpers so the TUI's detail pane stays in
    sync with ``mergers show``. Returns an empty Text if the merger or
    connection is unavailable.
    """
    if conn is None:
        return Text("")
    merger = db.get_merger(conn, merger_id)
    if merger is None:
        return Text(f"Merger {merger_id} not found.", style="red")
    questionnaire = db.get_questionnaire(conn, merger_id)
    nocc = db.get_nocc(conn, merger_id)

    buf = StringIO()
    capture_console = Console(
        file=buf,
        force_terminal=True,
        color_system="truecolor",
        width=width,
    )
    with _override_console(capture_console):
        display.show_merger(merger, questionnaire, section="all", nocc=nocc)
    return Text.from_ansi(buf.getvalue())


def fetch_rows(
    conn,
    parsed: ParsedQuery,
    *,
    limit: int = _LIST_LIMIT,
) -> tuple[list[Any], int, dict[str, str | None]]:
    """Run the query path appropriate for *parsed* and return rows + total.

    Returns ``(rows, total_match_count, snippets_by_id)``. ``snippets`` is
    populated only when there is a free-text query.
    """
    filters = build_filters(parsed.kwargs, limit=limit)
    snippets: dict[str, str | None] = {}
    if parsed.query:
        rows = db.search(conn, parsed.query, filters, snippets=True)
        total = db.count_search(conn, parsed.query, filters)
        for row in rows:
            snip = row["fts_snippet"] if "fts_snippet" in row.keys() else None
            snippets[row["merger_id"]] = snip
    else:
        rows = db.list_mergers(conn, filters, sort="date-desc")
        total = db.count_list_mergers(conn, filters)
    return rows, total, snippets


HELP_TEXT = """\
[bold]ACCC Mergers — Interactive Browser[/]

[bold]Navigation[/]
  ↑ / ↓       Move through the result list
  PgUp/PgDn   Scroll the detail pane
  Tab         Switch focus between list and filter input
  /           Focus the filter input
  Esc         Return focus from filter input to list

[bold]Filter syntax[/] (type into the filter input)
  free text             Full-text search across descriptions and reasons
  outcome:approved      Filter by outcome (approved|denied|phase2|pending)
  industry:beverage     Partial ANZSIC industry match
  acquirer:asahi        Acquirer name contains
  target:warehouse      Target name contains
  phase:1               1, 2, or 0 (waivers)
  year:2025             Notification year
  since:2025-01-01      Notified on or after
  until:2025-12-31      Notified on or before
  waiver:true|false     Waivers only / notifications only

Combine freely, e.g. [bold]outcome:approved industry:beverage warehouse[/].

[bold]Actions[/]
  o           Open the highlighted merger on mergers.fyi
  shift+o     Open the original ACCC register page
  ?           Toggle this help screen
  q           Quit

Press [bold]?[/] or [bold]Esc[/] to close this help.
"""


class HelpScreen(ModalScreen[None]):
    """Modal help overlay."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Close"),
        Binding("q", "app.pop_screen", "Close"),
        Binding("question_mark", "app.pop_screen", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > #help-panel {
        width: 72;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(HELP_TEXT, id="help-panel")


class MergerListItem(ListItem):
    """List entry carrying a merger_id payload."""

    def __init__(self, merger_id: str, label: Text) -> None:
        super().__init__(Label(label))
        self.merger_id = merger_id


class MergersBrowseApp(App):
    """Interactive merger register browser."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #main {
        height: 1fr;
    }
    #left {
        width: 45%;
        border-right: solid $primary-darken-2;
    }
    #right {
        width: 55%;
        padding: 0 1;
    }
    #filter {
        border: tall $primary-darken-2;
        margin: 0;
    }
    #status {
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 1;
    }
    ListView {
        height: 1fr;
    }
    #detail {
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "toggle_help", "Help"),
        Binding("slash", "focus_filter", "Filter"),
        Binding("o", "open_browser('fyi')", "Open"),
        Binding("shift+o", "open_browser('accc')", "Open (ACCC)"),
        Binding("escape", "focus_list", show=False),
    ]

    status_text: reactive[str] = reactive("Loading…")

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._db_path = db_path
        self._conn = None
        self._rows: list[Any] = []
        self._row_by_id: dict[str, Any] = {}

    # ---- lifecycle -------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Input(
                    placeholder=(
                        "Filter (e.g. outcome:approved industry:beverage). "
                        "Press / to focus, ? for help."
                    ),
                    id="filter",
                )
                yield ListView(id="results")
            with VerticalScroll(id="right"):
                yield Static("Select a merger to view detail.", id="detail")
        yield Static(self.status_text, id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "ACCC Mergers"
        self.sub_title = "Interactive browser"
        self._conn = db.connect(self._db_path)
        self._refresh_results("")
        list_view = self.query_one("#results", ListView)
        list_view.focus()

    def on_unmount(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ---- list / detail wiring -------------------------------------------

    def _refresh_results(self, filter_text: str) -> None:
        if self._conn is None:
            return
        parsed = parse_filter_input(filter_text)
        try:
            rows, total, snippets = fetch_rows(self._conn, parsed)
        except Exception as exc:
            self._set_status(f"[red]Query error:[/] {exc}")
            return
        self._rows = list(rows)
        self._row_by_id = {row["merger_id"]: row for row in self._rows}

        list_view = self.query_one("#results", ListView)
        list_view.clear()
        for row in self._rows:
            snip = snippets.get(row["merger_id"])
            list_view.append(MergerListItem(row["merger_id"], row_label(row, snip)))

        if self._rows:
            list_view.index = 0
            self._show_detail(self._rows[0]["merger_id"])
        else:
            self.query_one("#detail", Static).update(
                "[yellow]No results match those filters.[/]"
            )

        bits = [f"{len(self._rows)} shown of {total} match"]
        age = sync.cache_age_days()
        if age is not None:
            bits.append(f"cache {age:.1f}d old")
        if parsed.kwargs:
            bits.append(
                "filters: " + " ".join(f"{k}={v}" for k, v in parsed.kwargs.items())
            )
        if parsed.query:
            bits.append(f'query: "{parsed.query}"')
        self._set_status("  ·  ".join(bits))

    def _show_detail(self, merger_id: str) -> None:
        detail = self.query_one("#detail", Static)
        rendered = capture_merger_detail(merger_id, conn=self._conn)
        detail.update(rendered)
        scroller = self.query_one("#right", VerticalScroll)
        scroller.scroll_home(animate=False)

    def _set_status(self, message: str) -> None:
        self.status_text = message
        try:
            self.query_one("#status", Static).update(message)
        except Exception:
            pass

    # ---- events ---------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._refresh_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter":
            self.query_one("#results", ListView).focus()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if isinstance(item, MergerListItem):
            self._show_detail(item.merger_id)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item = event.item
        if isinstance(item, MergerListItem):
            self._show_detail(item.merger_id)

    # ---- actions --------------------------------------------------------

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_focus_list(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#results", ListView).focus()

    def action_toggle_help(self) -> None:
        if isinstance(self.screen, HelpScreen):
            self.pop_screen()
        else:
            self.push_screen(HelpScreen())

    def action_open_browser(self, target: str = "fyi") -> None:
        current = self._current_merger_id()
        if not current:
            self._set_status("[yellow]No merger selected to open.[/]")
            return
        normalized = db.normalize_merger_id(current)
        if target == "accc":
            row = self._row_by_id.get(current)
            url = None
            if row is not None and "url" in row.keys():
                url = row["url"]
            if not url and self._conn is not None:
                merger = db.get_merger(self._conn, current)
                if merger is not None:
                    url = merger.raw.get("url")
            if not url:
                self._set_status(f"[red]No ACCC URL recorded for {normalized}.[/]")
                return
        else:
            url = f"{_FYI_BASE_URL}/{normalized}"

        try:
            webbrowser.open(url, new=2)
            self._set_status(f"Opened {url}")
        except Exception as exc:
            self._set_status(f"[red]Could not open browser:[/] {exc}")

    def _current_merger_id(self) -> str | None:
        list_view = self.query_one("#results", ListView)
        item = list_view.highlighted_child
        if isinstance(item, MergerListItem):
            return item.merger_id
        return None


def run(db_path: Path | None = None) -> None:
    """Launch the interactive browser. Returns when the user quits."""
    MergersBrowseApp(db_path=db_path).run()
