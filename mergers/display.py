"""Rich-based terminal output helpers."""

from __future__ import annotations

import datetime as dt
import sys
from typing import Any, Iterable, Sequence

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import Merger, Questionnaire

_console: Console | None = None


def console() -> Console:
    global _console
    if _console is None:
        _console = Console(no_color=not sys.stdout.isatty())
    return _console


OUTCOME_STYLES = {
    "approved": "green",
    "denied": "red",
    "phase 2": "red",
    "phase2": "red",
    "pending": "yellow",
}


def outcome_style(value: str | None) -> str:
    if not value:
        return "yellow"
    key = value.strip().lower()
    for needle, style in OUTCOME_STYLES.items():
        if needle in key:
            return style
    return "white"


def format_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%b %Y")
    except ValueError:
        return value[:10] if len(value) >= 10 else value


def render_row(row: Any) -> Sequence[str]:
    merger_id = row["merger_id"]
    name = row["merger_name"] or ""
    determination = row["determination"] or (
        "Pending" if not row["determination"] else row["determination"]
    )
    phase = (
        f"Phase {row['phase']}"
        if row["phase"]
        else ("Waiver" if row["is_waiver"] else "—")
    )
    industry = (row["industries_text"] or "").split(";")[0].strip() or "—"
    date = format_date(row["notification_date"])
    return (merger_id, name, determination, phase, industry, date)


def render_results_table(
    rows: Iterable[Any], title: str | None = None
) -> Table:
    table = Table(title=title, show_lines=False, expand=True)
    table.add_column("ID", style="bold cyan", no_wrap=True)
    table.add_column("Name", overflow="fold")
    table.add_column("Outcome", no_wrap=True)
    table.add_column("Phase", no_wrap=True)
    table.add_column("Industry", overflow="fold")
    table.add_column("Date", no_wrap=True)
    for row in rows:
        merger_id, name, determination, phase, industry, date = render_row(row)
        table.add_row(
            merger_id,
            name,
            Text(determination or "Pending", style=outcome_style(determination)),
            phase,
            industry,
            date,
        )
    return table


def row_as_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys() if k != "raw_json"}


def show_merger(merger: Merger, questionnaire: Questionnaire | None, section: str = "all") -> None:
    c = console()

    header_lines = [
        f"[bold cyan]{merger.merger_id}[/] — [bold]{merger.merger_name}[/]",
    ]
    determination = merger.outcome() or "Pending"
    header_lines.append(
        f"Status: {merger.status or '—'}   "
        f"Stage: {merger.stage or '—'}   "
        f"Outcome: [{outcome_style(determination)}]{determination}[/]"
    )
    kind = "Waiver" if merger.is_waiver else "Notification"
    header_lines.append(
        f"Type: {kind}   "
        f"Notified: {format_date(merger.effective_notification_datetime)}   "
        f"Determined: {format_date(merger.determination_publication_date)}"
    )
    c.print(Panel("\n".join(header_lines), border_style="cyan"))

    if section in ("all", "parties"):
        _render_parties(merger)

    if section in ("all", "industries"):
        _render_industries(merger)

    if section in ("all", "description"):
        _render_description(merger)

    if section in ("all", "determination", "reasons", "overlap"):
        _render_determination_sections(merger, section)

    if section in ("all", "questionnaire") and questionnaire:
        _render_questionnaire(questionnaire)

    if section == "all":
        _render_comments(merger)


def _render_parties(merger: Merger) -> None:
    c = console()
    table = Table(title="Parties", show_header=True, expand=True)
    table.add_column("Role", style="bold")
    table.add_column("Name", overflow="fold")
    table.add_column("ABN / ACN", no_wrap=True)
    for party in merger.acquirers:
        table.add_row(
            "Acquirer", party.name, party.abn or party.acn or "—"
        )
    for party in merger.targets:
        table.add_row(
            "Target", party.name, party.abn or party.acn or "—"
        )
    if merger.acquirers or merger.targets:
        c.print(table)


def _render_industries(merger: Merger) -> None:
    if not merger.anzsic_codes:
        return
    c = console()
    table = Table(title="Industries (ANZSIC)", show_header=True, expand=True)
    table.add_column("Code", style="bold", no_wrap=True)
    table.add_column("Name", overflow="fold")
    for code in merger.anzsic_codes:
        table.add_row(code.code, code.name)
    c.print(table)


def _render_description(merger: Merger) -> None:
    if not merger.merger_description.strip():
        return
    c = console()
    c.print(Panel(merger.merger_description.strip(), title="Description", border_style="blue"))


def _render_determination_sections(merger: Merger, section: str) -> None:
    sections = merger.determination_sections()
    if not sections:
        return
    c = console()

    filter_map = {
        "reasons": "reasons for determination",
        "overlap": "overlap and relationship between the parties",
    }
    target = filter_map.get(section)

    seen: set[str] = set()
    for s in sections:
        if not s.content.strip():
            continue
        key = s.item.strip().lower()
        if target and key != target:
            continue
        dedup_key = f"{key}::{s.content[:120]}"
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        c.print(Panel(s.content.strip(), title=s.item, border_style="magenta"))


def _render_questionnaire(q: Questionnaire) -> None:
    c = console()
    lines = [
        f"[bold]Deadline:[/] {q.deadline or '—'}   "
        f"[bold]Questions:[/] {q.questions_count}"
    ]
    for i, question in enumerate(q.questions, start=1):
        number = question.get("number") or question.get("question_number") or i
        text = (
            question.get("text")
            or question.get("question")
            or question.get("question_text")
            or ""
        )
        lines.append(f"\n[bold]{number}.[/] {text.strip()}")
    c.print(Panel("\n".join(lines), title="Questionnaire", border_style="yellow"))


def _render_comments(merger: Merger) -> None:
    if not merger.comments:
        return
    c = console()
    parts: list[str] = []
    for comment in merger.comments:
        tag_text = ""
        if comment.tags:
            tag_text = "  " + " ".join(f"[dim][{t}][/]" for t in comment.tags)
        parts.append(f"{comment.text.strip()}{tag_text}")
    c.print(Panel("\n\n".join(parts), title="Commentary", border_style="green"))


def show_questionnaire_list(rows: Iterable[Any]) -> None:
    c = console()
    table = Table(title="Mergers with questionnaires", expand=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Name", overflow="fold")
    table.add_column("Deadline", no_wrap=True)
    table.add_column("Questions", justify="right", no_wrap=True)
    for row in rows:
        table.add_row(
            row["merger_id"],
            row["merger_name"] or "",
            row["deadline"] or "—",
            str(row["questions_count"] or 0),
        )
    c.print(table)


def show_question_matches(rows: Iterable[Any]) -> None:
    c = console()
    table = Table(title="Matching questions", expand=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Merger", overflow="fold")
    table.add_column("#", no_wrap=True)
    table.add_column("Question", overflow="fold")
    for row in rows:
        table.add_row(
            row["merger_id"],
            row["merger_name"] or "",
            row["question_number"] or "",
            row["question_text"] or "",
        )
    c.print(table)


def show_industry_table(rows: list[dict[str, Any]]) -> None:
    c = console()
    table = Table(title="Merger activity by industry", expand=True)
    table.add_column("Industry", overflow="fold")
    table.add_column("Notifications", justify="right")
    table.add_column("Waivers", justify="right")
    table.add_column("Approved", justify="right")
    table.add_column("Phase 2", justify="right")
    for row in rows:
        table.add_row(
            row["industry"],
            str(row["notifications"]),
            str(row["waivers"]),
            str(row["approved"]),
            str(row["phase2"]),
        )
    c.print(table)


def show_stats(stats: dict[str, Any]) -> None:
    c = console()
    if not stats:
        c.print("[yellow]No stats available. Run `mergers sync` first.[/]")
        return

    totals = stats.get("totals") or stats.get("summary") or {}
    if totals:
        table = Table(title="Totals", expand=True)
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")
        for key, value in totals.items():
            table.add_row(str(key), str(value))
        c.print(table)

    durations = stats.get("phase_durations") or stats.get("durations")
    if durations:
        table = Table(title="Phase duration (days)", expand=True)
        table.add_column("Phase", style="bold")
        table.add_column("Average", justify="right")
        table.add_column("Median", justify="right")
        if isinstance(durations, dict):
            for phase, payload in durations.items():
                if isinstance(payload, dict):
                    table.add_row(
                        str(phase),
                        str(payload.get("average") or payload.get("avg") or "—"),
                        str(payload.get("median") or "—"),
                    )
                else:
                    table.add_row(str(phase), str(payload), "—")
        c.print(table)

    top = stats.get("top_industries") or stats.get("industries")
    if isinstance(top, list):
        table = Table(title="Top industries", expand=True)
        table.add_column("Industry", overflow="fold")
        table.add_column("Count", justify="right")
        for entry in top[:10]:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("industry") or "—"
                count = entry.get("count") or entry.get("total") or "—"
                table.add_row(str(name), str(count))
        c.print(table)

    recent = stats.get("recent_determinations") or stats.get("recent")
    if isinstance(recent, list):
        table = Table(title="Recent determinations", expand=True)
        table.add_column("ID", style="bold cyan")
        table.add_column("Name", overflow="fold")
        table.add_column("Outcome")
        table.add_column("Date", no_wrap=True)
        for entry in recent[:10]:
            if not isinstance(entry, dict):
                continue
            table.add_row(
                str(entry.get("merger_id") or ""),
                str(entry.get("merger_name") or ""),
                str(entry.get("determination") or entry.get("outcome") or "—"),
                format_date(entry.get("date") or entry.get("determination_date")),
            )
        c.print(table)


def warn_stale_cache(age_days: float) -> None:
    c = console()
    c.print(
        f"[yellow]Warning:[/] local cache is {age_days:.1f} days old — "
        "run `mergers sync` to refresh."
    )


def print_json(payload: Any) -> None:
    console().print_json(data=payload, default=str)
