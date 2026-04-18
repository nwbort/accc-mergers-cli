"""Typer entry point for the `mergers` CLI."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import db, display, sync
from .db import SearchFilters

app = typer.Typer(
    add_completion=False,
    help="Query the ACCC merger register from your terminal.",
    no_args_is_help=True,
)


def _with_connection():
    conn = db.connect()
    db.init_schema(conn)
    return conn


def _auto_sync_if_needed() -> None:
    if sync.cache_exists():
        age = sync.cache_age_days()
        if age is not None and age > db.STALE_DAYS:
            display.warn_stale_cache(age)
        return

    display.console().print(
        "[cyan]No local cache found. Running initial sync…[/]"
    )
    _run_sync()


def _run_sync(force: bool = False) -> sync.SyncResult:
    c = display.console()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task_id = progress.add_task("Syncing merger data", total=None)
        try:
            result = sync.sync(force=force)
        except sync.SyncError as exc:
            progress.remove_task(task_id)
            c.print(f"[red]Sync failed:[/] {exc}")
            raise typer.Exit(code=1)

    manifest = result.manifest
    if result.changed:
        c.print(
            f"[green]Indexed {result.mergers} mergers "
            f"and {result.questionnaires} questionnaires.[/]"
        )
    else:
        c.print("[green]Local index already up to date.[/]")
    c.print(
        f"[dim]Bundle version {manifest.get('version')} · "
        f"generated {manifest.get('generated_at')}[/]"
    )
    return result


@app.command(name="sync")
def sync_cmd(
    force: bool = typer.Option(
        False, "--force", help="Skip the hash check and re-download + reindex."
    ),
) -> None:
    """Download and index the latest data from GitHub."""
    _run_sync(force=force)


@app.command(name="status")
def status_cmd() -> None:
    """Show the version, generation time and age of the local cache."""
    c = display.console()
    if not sync.cache_exists():
        c.print("[yellow]No local cache. Run `mergers sync` first.[/]")
        raise typer.Exit(code=1)

    manifest = sync.read_cached_manifest()
    conn = _with_connection()
    try:
        merger_count = db.count_mergers(conn)
    finally:
        conn.close()

    age_days = sync.cache_age_days()
    age_display = f"{age_days:.1f} days ago" if age_days is not None else "—"

    if manifest:
        c.print(f"Bundle version: [bold]{manifest.get('version', '—')}[/]")
        c.print(f"Generated at:   {manifest.get('generated_at', '—')}")
        c.print(
            f"Mergers:        {merger_count}"
            + (
                f" (manifest says {manifest['merger_count']})"
                if manifest.get("merger_count") not in (None, merger_count)
                else ""
            )
        )
    else:
        c.print("[yellow]No cached manifest found.[/]")
        c.print(f"Mergers:        {merger_count}")

    c.print(f"Last sync:      {age_display}")


def _parse_filters(
    outcome: str | None,
    industry: str | None,
    phase: int | None,
    waiver: bool | None,
    year: int | None,
    limit: int,
) -> SearchFilters:
    if outcome is not None:
        allowed = {"approved", "denied", "phase2", "pending"}
        if outcome.lower() not in allowed:
            raise typer.BadParameter(
                f"--outcome must be one of {sorted(allowed)}"
            )
    if phase is not None and phase not in (1, 2):
        raise typer.BadParameter("--phase must be 1 or 2")
    return SearchFilters(
        outcome=outcome.lower() if outcome else None,
        industry=industry,
        phase=phase,
        waiver=waiver,
        year=year,
        limit=limit,
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Full-text search query."),
    outcome: Optional[str] = typer.Option(
        None, "--outcome", help="approved | denied | phase2 | pending"
    ),
    industry: Optional[str] = typer.Option(
        None, "--industry", help="Partial industry name match."
    ),
    phase: Optional[int] = typer.Option(
        None, "--phase", help="1 or 2"
    ),
    waiver: Optional[bool] = typer.Option(
        None,
        "--waiver/--no-waiver",
        help="Filter to waivers or notifications only.",
    ),
    year: Optional[int] = typer.Option(
        None, "--year", help="Notification year."
    ),
    limit: int = typer.Option(10, "--limit", help="Max results."),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw JSON."
    ),
) -> None:
    """Full-text search across merger descriptions and determination text."""
    _auto_sync_if_needed()
    filters = _parse_filters(outcome, industry, phase, waiver, year, limit)

    conn = _with_connection()
    try:
        rows = db.search(conn, query, filters)
    finally:
        conn.close()

    if json_output:
        display.print_json([display.row_as_dict(r) for r in rows])
        return

    if not rows:
        display.console().print("[yellow]No results.[/]")
        return

    display.console().print(display.render_results_table(rows))


@app.command()
def show(
    merger_id: str = typer.Argument(..., help="Merger ID, e.g. MN-01016"),
    section: str = typer.Option(
        "all",
        "--section",
        help="all | determination (full determination content) | reasons | overlap | parties",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw merger JSON."
    ),
) -> None:
    """Display full detail on a single merger."""
    _auto_sync_if_needed()

    allowed = {"all", "reasons", "overlap", "parties", "determination"}
    if section not in allowed:
        raise typer.BadParameter(f"--section must be one of {sorted(allowed)}")

    conn = _with_connection()
    try:
        merger = db.get_merger(conn, merger_id)
        questionnaire = db.get_questionnaire(conn, merger_id)
    finally:
        conn.close()

    if not merger:
        display.console().print(
            f"[red]No merger found with ID '{merger_id}'.[/]"
        )
        raise typer.Exit(code=1)

    if json_output:
        display.print_json(merger.raw)
        return

    display.show_merger(merger, questionnaire, section=section)


@app.command(name="list")
def list_cmd(
    outcome: Optional[str] = typer.Option(None, "--outcome"),
    industry: Optional[str] = typer.Option(None, "--industry"),
    phase: Optional[int] = typer.Option(None, "--phase"),
    waiver: Optional[bool] = typer.Option(None, "--waiver/--no-waiver"),
    year: Optional[int] = typer.Option(None, "--year"),
    limit: int = typer.Option(50, "--limit"),
    sort: str = typer.Option(
        "date-desc",
        "--sort",
        help="date-asc | date-desc | name | duration",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Browse mergers with filters, no search query required."""
    _auto_sync_if_needed()
    filters = _parse_filters(outcome, industry, phase, waiver, year, limit)

    allowed_sort = {"date-asc", "date-desc", "name", "duration"}
    if sort not in allowed_sort:
        raise typer.BadParameter(f"--sort must be one of {sorted(allowed_sort)}")

    conn = _with_connection()
    try:
        rows = db.list_mergers(conn, filters, sort=sort)
    finally:
        conn.close()

    if json_output:
        display.print_json([display.row_as_dict(r) for r in rows])
        return

    if not rows:
        display.console().print("[yellow]No mergers match those filters.[/]")
        return

    display.console().print(display.render_results_table(rows))


@app.command()
def questions(
    merger_id: Optional[str] = typer.Argument(
        None, help="Merger ID. Omit to list mergers with questionnaires."
    ),
    search_text: Optional[str] = typer.Option(
        None,
        "--search",
        help="Search question text across all mergers.",
    ),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Browse questionnaire questions."""
    _auto_sync_if_needed()
    conn = _with_connection()
    try:
        if search_text:
            rows = db.search_questions(conn, search_text, limit=limit)
            if json_output:
                display.print_json([dict(r) for r in rows])
                return
            if not rows:
                display.console().print("[yellow]No matching questions.[/]")
                return
            display.show_question_matches(rows)
            return

        if merger_id:
            q = db.get_questionnaire(conn, merger_id)
            if not q:
                display.console().print(
                    f"[yellow]No questionnaire for {merger_id}.[/]"
                )
                raise typer.Exit(code=1)
            if json_output:
                display.print_json(asdict(q))
                return
            merger = db.get_merger(conn, merger_id)
            display.console().print(
                f"[bold cyan]{q.merger_id}[/] — "
                f"[bold]{merger.merger_name if merger else q.merger_name or ''}[/]"
            )
            display.console().print(
                f"Deadline: {q.deadline or '—'}  |  {q.questions_count} questions\n"
            )
            for i, question in enumerate(q.questions, start=1):
                number = (
                    question.get("number")
                    or question.get("question_number")
                    or i
                )
                text = (
                    question.get("text")
                    or question.get("question")
                    or question.get("question_text")
                    or ""
                )
                display.console().print(f"[bold]{number}.[/] {text.strip()}\n")
            return

        rows = db.list_questionnaires(conn)
        if json_output:
            display.print_json([dict(r) for r in rows])
            return
        if not rows:
            display.console().print("[yellow]No questionnaires cached.[/]")
            return
        display.show_questionnaire_list(rows)
    finally:
        conn.close()


@app.command()
def industries(
    show: Optional[str] = typer.Option(
        None,
        "--show",
        help="Show mergers within the given industry (partial name match).",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show a breakdown of merger activity by industry."""
    _auto_sync_if_needed()
    conn = _with_connection()
    try:
        if show:
            rows = db.mergers_by_industry(conn, show)
            if json_output:
                display.print_json([display.row_as_dict(r) for r in rows])
                return
            if not rows:
                display.console().print(
                    f"[yellow]No mergers found for industry '{show}'.[/]"
                )
                return
            display.console().print(
                display.render_results_table(
                    rows, title=f"Mergers in '{show}'"
                )
            )
            return

        breakdown = db.industry_breakdown(conn)
    finally:
        conn.close()

    if json_output:
        display.print_json(breakdown)
        return

    if not breakdown:
        display.console().print("[yellow]No industry data cached.[/]")
        return

    display.show_industry_table(breakdown)


@app.command()
def stats(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Print summary statistics from the cached stats.json."""
    _auto_sync_if_needed()
    conn = _with_connection()
    try:
        payload = db.get_stats(conn)
    finally:
        conn.close()

    if json_output:
        display.print_json(payload or {})
        return

    display.show_stats(payload or {})


def main() -> None:
    app()


if __name__ == "__main__":
    main()
