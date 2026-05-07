"""Typer entry point for the `mergers` CLI."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import db, display, sync
from .db import SearchFilters


def _format_local_timestamp(generated_at: str | None) -> str:
    if not generated_at:
        return "—"
    try:
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError:
        return generated_at
    local = dt.astimezone()
    tz_name = local.strftime("%Z") or local.strftime("%z")
    return f"{local.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}".rstrip()


app = typer.Typer(
    add_completion=True,
    help="Query the ACCC merger register from your terminal.",
    no_args_is_help=True,
)


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_iso_date(value: str | None, flag: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not _ISO_DATE_RE.match(value):
        raise typer.BadParameter(
            f"{flag} must be an ISO date (YYYY-MM-DD), got '{value}'"
        )
    return value


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


def _run_sync(force: bool = False, verbose: bool = False) -> sync.SyncResult:
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
        c.print(
            f"[dim]Bundle version {manifest.get('version')} · "
            f"generated {manifest.get('generated_at')}[/]"
        )
    else:
        local_ts = _format_local_timestamp(manifest.get("generated_at"))
        c.print(f"[green]Data up to date (last update {local_ts})[/]")
        if verbose:
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
    verbose: bool = typer.Option(
        False, "--verbose", help="Show bundle version and UTC timestamp."
    ),
) -> None:
    """Download and index the latest data from GitHub."""
    _run_sync(force=force, verbose=verbose)


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


_SEARCH_SECTIONS = {"all", "reasons", "overlap", "description", "parties"}


def _parse_filters(
    outcome: str | None,
    industry: str | None,
    phase: int | None,
    waiver: bool | None,
    year: int | None,
    limit: int,
    since: str | None = None,
    until: str | None = None,
    has_related: bool | None = None,
    section: str | None = None,
) -> SearchFilters:
    if outcome is not None:
        allowed = {"approved", "denied", "phase2", "pending"}
        if outcome.lower() not in allowed:
            raise typer.BadParameter(
                f"--outcome must be one of {sorted(allowed)}"
            )
    if phase is not None and phase not in (0, 1, 2):
        raise typer.BadParameter("--phase must be 0 (waivers), 1, or 2")
    since = _validate_iso_date(since, "--since")
    until = _validate_iso_date(until, "--until")
    if since and until and since > until:
        raise typer.BadParameter("--since must be on or before --until")
    if section is not None and section not in _SEARCH_SECTIONS:
        raise typer.BadParameter(
            f"--section must be one of {sorted(_SEARCH_SECTIONS)}"
        )
    return SearchFilters(
        outcome=outcome.lower() if outcome else None,
        industry=industry,
        phase=phase,
        waiver=waiver,
        year=year,
        since=since,
        until=until,
        has_related=has_related,
        limit=limit,
        section=section if section and section != "all" else None,
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Full-text search query, or regex if --regex is set."),
    outcome: Optional[str] = typer.Option(
        None, "--outcome", help="approved | denied | phase2 | pending"
    ),
    industry: Optional[str] = typer.Option(
        None, "--industry", help="Partial industry name match."
    ),
    phase: Optional[int] = typer.Option(
        None, "--phase", help="0 (waivers), 1, or 2"
    ),
    waiver: Optional[bool] = typer.Option(
        None,
        "--waiver/--no-waiver",
        help="Filter to waivers or notifications only.",
    ),
    year: Optional[int] = typer.Option(
        None, "--year", help="Notification year."
    ),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only include mergers notified on or after this date (YYYY-MM-DD).",
    ),
    until: Optional[str] = typer.Option(
        None,
        "--until",
        help="Only include mergers notified on or before this date (YYYY-MM-DD).",
    ),
    regex: bool = typer.Option(
        False,
        "--regex",
        help="Interpret the query as a Python regex instead of an FTS query.",
    ),
    has_related: Optional[bool] = typer.Option(
        None,
        "--has-related/--no-related",
        help="Only include mergers that have (or do not have) a related merger.",
    ),
    limit: int = typer.Option(10, "--limit", help="Max results."),
    snippets: bool = typer.Option(
        False,
        "--snippets",
        help="Print a short excerpt showing where the query matches in each result.",
    ),
    section: Optional[str] = typer.Option(
        None,
        "--section",
        help=(
            "Restrict the search to a specific content section: "
            "all | reasons | overlap | description | parties"
        ),
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw JSON."
    ),
) -> None:
    """Full-text search across merger descriptions and determination text."""
    _auto_sync_if_needed()
    filters = _parse_filters(
        outcome,
        industry,
        phase,
        waiver,
        year,
        limit,
        since=since,
        until=until,
        has_related=has_related,
        section=section,
    )

    conn = _with_connection()
    try:
        if regex:
            try:
                pattern = re.compile(query, re.IGNORECASE | re.DOTALL)
            except re.error as exc:
                raise typer.BadParameter(f"Invalid regex: {exc}")
            rows, total = db.search_regex(conn, pattern, filters)
        else:
            rows = db.search(conn, query, filters, snippets=snippets)
            total = db.count_search(conn, query, filters)
    finally:
        conn.close()

    if json_output:
        result_list = [display.row_as_dict(r) for r in rows]
        if snippets:
            for i, row in enumerate(rows):
                if regex:
                    snip = db.extract_regex_snippet(row, pattern, filters.section)
                else:
                    snip = row["fts_snippet"] if "fts_snippet" in row.keys() else None
                result_list[i]["snippets"] = [snip] if snip else []
        display.print_json({"total_matches": total, "results": result_list})
        return

    if not rows:
        display.console().print("[yellow]No results.[/]")
        return

    c = display.console()
    if snippets:
        snip_map: dict[str, str | None] = {}
        for row in rows:
            if regex:
                snip_map[row["merger_id"]] = db.extract_regex_snippet(
                    row, pattern, filters.section
                )
            else:
                val = row["fts_snippet"] if "fts_snippet" in row.keys() else None
                snip_map[row["merger_id"]] = val
        display.render_results_with_snippets(rows, snip_map)
    else:
        c.print(display.render_results_table(rows))

    shown = len(rows)
    if total > shown:
        c.print(
            f"[dim]Showing {shown} of {total} results. Use --limit to see more.[/]"
        )
    else:
        c.print(f"[dim]{shown} result{'s' if shown != 1 else ''}.[/]")


@app.command()
def show(
    merger_id: str = typer.Argument(
        ..., help="Merger ID, e.g. MN-01016 (also accepts 'mn 01016', 'MN01016')."
    ),
    section: str = typer.Option(
        "all",
        "--section",
        help=(
            "all | determination (full determination content) | reasons | overlap"
            " | parties | industries | description | questionnaire | nocc"
        ),
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw merger JSON."
    ),
) -> None:
    """Display full detail on a single merger."""
    _auto_sync_if_needed()

    allowed = {
        "all",
        "reasons",
        "overlap",
        "parties",
        "industries",
        "determination",
        "description",
        "questionnaire",
        "nocc",
    }
    if section not in allowed:
        raise typer.BadParameter(f"--section must be one of {sorted(allowed)}")

    conn = _with_connection()
    try:
        merger = db.get_merger(conn, merger_id)
        questionnaire = db.get_questionnaire(conn, merger_id)
        nocc = db.get_nocc(conn, merger_id)
    finally:
        conn.close()

    if not merger:
        display.console().print(
            f"[red]No merger found with ID '{merger_id}'.[/]"
        )
        raise typer.Exit(code=1)

    if json_output:
        payload = dict(merger.raw)
        # Augment with computed text fields that may be absent from the raw bundle.
        payload["all_determination_text"] = merger.all_determination_text()
        payload["determination_reasons"] = (
            merger.section_text("Reasons for determination")
            or merger.all_determination_text()
        )
        display.print_json(payload)
        return

    display.show_merger(merger, questionnaire, section=section, nocc=nocc)


@app.command()
def timeline(
    merger_id: str = typer.Argument(
        ..., help="Merger ID, e.g. MN-01016 (also accepts 'mn 01016', 'MN01016')."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output the timeline as JSON."
    ),
    detail: bool = typer.Option(
        False, "--detail", help="Show the detail column for each event."
    ),
) -> None:
    """Show a chronological timeline for a single merger."""
    _auto_sync_if_needed()

    conn = _with_connection()
    try:
        merger = db.get_merger(conn, merger_id)
    finally:
        conn.close()

    if not merger:
        display.console().print(
            f"[red]No merger found with ID '{merger_id}'.[/]"
        )
        raise typer.Exit(code=1)

    events = display.timeline_events(merger)

    if json_output:
        display.print_json(
            {
                "merger_id": merger.merger_id,
                "merger_name": merger.merger_name,
                "stage": merger.stage,
                "outcome": merger.outcome(),
                "notification_date": merger.effective_notification_datetime,
                "determination_date": merger.determination_publication_date,
                "events": events,
            }
        )
        return

    display.show_timeline(merger, show_detail=detail)


@app.command()
def related(
    merger_id: str = typer.Argument(
        ..., help="Merger ID, e.g. WA-01087 (also accepts 'wa 01087')."
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Output raw JSON."
    ),
) -> None:
    """Show mergers linked via the 'related merger' field (e.g. waiver refiled as notification)."""
    _auto_sync_if_needed()

    conn = _with_connection()
    try:
        merger = db.get_merger(conn, merger_id)
        rows = db.related_mergers(conn, merger_id)
    finally:
        conn.close()

    if not merger:
        display.console().print(
            f"[red]No merger found with ID '{merger_id}'.[/]"
        )
        raise typer.Exit(code=1)

    if json_output:
        payload = {
            "merger_id": merger.merger_id,
            "merger_name": merger.merger_name,
            "related_merger": (
                {
                    "merger_id": merger.related_merger.merger_id,
                    "relationship": merger.related_merger.relationship,
                    "merger_name": merger.related_merger.merger_name,
                }
                if merger.related_merger
                else None
            ),
            "related": [display.row_as_dict(r) for r in rows],
        }
        display.print_json(payload)
        return

    c = display.console()
    c.print(
        f"[bold cyan]{merger.merger_id}[/] — [bold]{merger.merger_name}[/]"
    )
    if merger.related_merger:
        rel = merger.related_merger
        label = display._relationship_label(rel.relationship)
        suffix = f" — {rel.merger_name}" if rel.merger_name else ""
        c.print(
            f"[magenta]{label}:[/] [bold cyan]{rel.merger_id}[/]{suffix}"
        )

    if not rows:
        c.print("[yellow]No related mergers found.[/]")
        return

    c.print(
        display.render_results_table(
            rows, title=f"Mergers related to {merger.merger_id}"
        )
    )


@app.command()
def party(
    name: str = typer.Argument(
        ..., help="Party name (partial match, case-insensitive)."
    ),
    role: Optional[str] = typer.Option(
        None,
        "--role",
        help="Restrict to 'acquirer' or 'target'; default searches both.",
    ),
    outcome: Optional[str] = typer.Option(None, "--outcome"),
    industry: Optional[str] = typer.Option(None, "--industry"),
    phase: Optional[int] = typer.Option(None, "--phase"),
    waiver: Optional[bool] = typer.Option(None, "--waiver/--no-waiver"),
    year: Optional[int] = typer.Option(None, "--year"),
    since: Optional[str] = typer.Option(None, "--since"),
    until: Optional[str] = typer.Option(None, "--until"),
    has_related: Optional[bool] = typer.Option(
        None, "--has-related/--no-related"
    ),
    limit: int = typer.Option(50, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """List mergers involving a given acquirer or target."""
    _auto_sync_if_needed()

    if role is not None and role.lower() not in {"acquirer", "target"}:
        raise typer.BadParameter("--role must be 'acquirer' or 'target'")

    filters = _parse_filters(
        outcome,
        industry,
        phase,
        waiver,
        year,
        limit,
        since=since,
        until=until,
        has_related=has_related,
    )

    role_norm = role.lower() if role else None
    conn = _with_connection()
    try:
        rows = db.mergers_by_party(conn, name, filters=filters, role=role_norm)
        total = db.count_mergers_by_party(conn, name, filters=filters, role=role_norm)
    finally:
        conn.close()

    if json_output:
        display.print_json({"total_matches": total, "results": [display.row_as_dict(r) for r in rows]})
        return

    if not rows:
        display.console().print(
            f"[yellow]No mergers found for party '{name}'.[/]"
        )
        return

    c = display.console()
    c.print(display.render_results_table(rows, title=f"Mergers involving '{name}'"))
    shown = len(rows)
    if total > shown:
        c.print(f"[dim]Showing {shown} of {total} results. Use --limit to see more.[/]")
    else:
        c.print(f"[dim]{shown} result{'s' if shown != 1 else ''}.[/]")


@app.command(name="list")
def list_cmd(
    outcome: Optional[str] = typer.Option(None, "--outcome"),
    industry: Optional[str] = typer.Option(None, "--industry"),
    phase: Optional[int] = typer.Option(
        None, "--phase", help="0 (waivers), 1, or 2"
    ),
    waiver: Optional[bool] = typer.Option(None, "--waiver/--no-waiver"),
    year: Optional[int] = typer.Option(None, "--year"),
    since: Optional[str] = typer.Option(
        None, "--since", help="Notified on or after (YYYY-MM-DD)."
    ),
    until: Optional[str] = typer.Option(
        None, "--until", help="Notified on or before (YYYY-MM-DD)."
    ),
    has_related: Optional[bool] = typer.Option(
        None,
        "--has-related/--no-related",
        help="Only include mergers that have (or do not have) a related merger.",
    ),
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
    filters = _parse_filters(
        outcome,
        industry,
        phase,
        waiver,
        year,
        limit,
        since=since,
        until=until,
        has_related=has_related,
    )

    allowed_sort = {"date-asc", "date-desc", "name", "duration"}
    if sort not in allowed_sort:
        raise typer.BadParameter(f"--sort must be one of {sorted(allowed_sort)}")

    conn = _with_connection()
    try:
        rows = db.list_mergers(conn, filters, sort=sort)
        total = db.count_list_mergers(conn, filters)
    finally:
        conn.close()

    if json_output:
        display.print_json({"total_matches": total, "results": [display.row_as_dict(r) for r in rows]})
        return

    if not rows:
        display.console().print("[yellow]No mergers match those filters.[/]")
        return

    c = display.console()
    c.print(display.render_results_table(rows))
    shown = len(rows)
    if total > shown:
        c.print(f"[dim]Showing {shown} of {total} results. Use --limit to see more.[/]")
    else:
        c.print(f"[dim]{shown} result{'s' if shown != 1 else ''}.[/]")


@app.command()
def questions(
    merger_id: Optional[str] = typer.Argument(
        None, help="Merger ID. Omit to list mergers with questionnaires."
    ),
    version: Optional[int] = typer.Argument(
        None, help="Questionnaire version number (1 = latest). Omit for latest."
    ),
    search_text: Optional[str] = typer.Option(
        None,
        "--search",
        help="Search question text across all mergers.",
    ),
    show_all: bool = typer.Option(
        False, "--all", help="Show all questionnaire versions."
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
            name = merger.merger_name if merger else q.merger_name or ""
            c = display.console()

            # Build a uniform list of version dicts.
            # all_questionnaires is populated when the bundle contains multiple
            # versions; otherwise the primary fields form the sole version.
            if q.all_questionnaires:
                versions = q.all_questionnaires
            else:
                versions = [
                    {
                        "deadline": q.deadline,
                        "deadline_iso": q.deadline_iso,
                        "file_name": q.file_name,
                        "questions": q.questions,
                        "questions_count": q.questions_count,
                    }
                ]
            total = len(versions)

            c.print(f"[bold cyan]{q.merger_id}[/] — [bold]{name}[/]")
            if total > 1:
                hint = (
                    f"  ·  use `mergers questions {q.merger_id} 2` or `--all`"
                    " to view others"
                )
                c.print(f"[dim]{total} questionnaire versions{hint}[/]")
            c.print()

            if version is not None and (version < 1 or version > total):
                c.print(
                    f"[red]Version {version} out of range "
                    f"(1–{total} available).[/]"
                )
                raise typer.Exit(code=1)

            if show_all:
                for i, v in enumerate(versions, start=1):
                    label = f"Version {i} of {total}"
                    if i == 1:
                        label += " · latest"
                    c.rule(f"[bold]{label}[/]")
                    c.print()
                    display.show_questionnaire_version(v)
                return

            idx = (version - 1) if version is not None else 0
            if total > 1:
                label = f"version {idx + 1} of {total}"
                if idx == 0:
                    label += " · latest"
                c.print(f"[dim]{label}[/]\n")
            display.show_questionnaire_version(versions[idx])
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
def noccs(
    merger_id: Optional[str] = typer.Argument(
        None, help="Merger ID. Omit to list mergers with NOCCs."
    ),
    search_text: Optional[str] = typer.Option(
        None,
        "--search",
        help="Full-text search across NOCC paragraph text.",
    ),
    limit: int = typer.Option(20, "--limit"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Browse Notices of Competition Concerns (NOCCs) issued in Phase 2."""
    _auto_sync_if_needed()
    conn = _with_connection()
    try:
        if search_text:
            rows = db.search_noccs(conn, search_text, limit=limit)
            if json_output:
                display.print_json([dict(r) for r in rows])
                return
            if not rows:
                display.console().print("[yellow]No matching NOCC paragraphs.[/]")
                return
            display.show_nocc_matches(rows)
            return

        if merger_id:
            n = db.get_nocc(conn, merger_id)
            if not n:
                display.console().print(
                    f"[yellow]No NOCC for {merger_id}.[/]"
                )
                raise typer.Exit(code=1)
            if json_output:
                display.print_json(
                    {
                        "merger_id": n.merger_id,
                        "merger_name": n.merger_name,
                        "matter_id": n.matter_id,
                        "date": n.date,
                        "date_iso": n.date_iso,
                        "document_type": n.document_type,
                        "file_name": n.file_name,
                        "file_path": n.file_path,
                        "sections": [
                            {
                                "number": s.number,
                                "title": s.title,
                                "blocks": [
                                    {
                                        "number": b.number,
                                        "text": b.text,
                                        "type": b.type,
                                    }
                                    for b in s.blocks
                                ],
                            }
                            for s in n.sections
                        ],
                    }
                )
                return

            c = display.console()
            name = n.merger_name or ""
            c.print(f"[bold cyan]{n.merger_id}[/] — [bold]{name}[/]")
            c.print()
            display._render_nocc(n)
            return

        rows = db.list_noccs(conn)
        if json_output:
            display.print_json([dict(r) for r in rows])
            return
        if not rows:
            display.console().print("[yellow]No NOCCs cached.[/]")
            return
        display.show_nocc_list(rows)
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
