"""Rich-based terminal output helpers."""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import sys
from typing import Any, Iterable, Sequence

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import Event, Merger, Nocc, Questionnaire

_console: Console | None = None


def console() -> Console:
    global _console
    if _console is None:
        _console = Console(no_color=not sys.stdout.isatty())
    return _console


# First match wins, so "not approved" has to come before "approved".
OUTCOME_STYLES = {
    "not approved": "red",
    "approved": "green",
    "ceased": "magenta",
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


_EXPORT_COLUMNS: Sequence[tuple[str, str]] = (
    ("merger_id", "ID"),
    ("merger_name", "Name"),
    ("determination", "Outcome"),
    ("phase", "Phase"),
    ("is_waiver", "Waiver"),
    ("industries_text", "Industries"),
    ("acquirers_text", "Acquirers"),
    ("targets_text", "Targets"),
    ("notification_date", "Notified"),
    ("determination_date", "Determined"),
    ("under_appeal", "Under appeal"),
    ("has_judicial_review", "Judicial review"),
    ("under_judicial_review", "Under judicial review"),
)


def _export_cell(row: Any, key: str) -> str:
    if key not in row.keys():
        return ""
    value = row[key]
    if value is None:
        return ""
    if key in ("is_waiver", "under_appeal", "has_judicial_review", "under_judicial_review"):
        return "yes" if value else "no"
    if key == "phase":
        return f"Phase {value}" if value else ""
    if key in ("notification_date", "determination_date") and isinstance(value, str):
        return value[:10]
    return str(value)


def render_results_csv(rows: Iterable[Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([header for _, header in _EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([_export_cell(row, key) for key, _ in _EXPORT_COLUMNS])
    return buf.getvalue()


def _md_escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_results_markdown(rows: Iterable[Any], title: str | None = None) -> str:
    headers = [header for _, header in _EXPORT_COLUMNS]
    lines: list[str] = []
    if title:
        lines.append(f"## {title}")
        lines.append("")
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        cells = [_md_escape(_export_cell(row, key)) for key, _ in _EXPORT_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def show_stats_by_axis(axis: str, buckets: list[dict[str, Any]]) -> None:
    c = console()
    titles = {
        "year": "Year",
        "industry": "Industry",
        "acquirer": "Acquirer",
        "outcome": "Outcome",
        "phase": "Phase",
    }
    table = Table(title=f"Mergers by {axis}", show_lines=False, expand=True)
    table.add_column(titles.get(axis, axis), overflow="fold")
    table.add_column("Total", justify="right", no_wrap=True)
    table.add_column("Notifications", justify="right", no_wrap=True)
    table.add_column("Waivers", justify="right", no_wrap=True)
    table.add_column("Approved", justify="right", no_wrap=True)
    table.add_column("Denied", justify="right", no_wrap=True)
    table.add_column("Phase 2", justify="right", no_wrap=True)
    for entry in buckets:
        table.add_row(
            str(entry["key"]),
            str(entry["total"]),
            str(entry["notifications"]),
            str(entry["waivers"]),
            str(entry["approved"]),
            str(entry["denied"]),
            str(entry["phase2"]),
        )
    c.print(table)


def row_as_dict(row: Any) -> dict[str, Any]:
    return {k: row[k] for k in row.keys() if k != "raw_json"}


_RELATIONSHIP_LABELS: dict[str, str] = {
    "refiled_as": "Refiled as",
    "refiled_from": "Refiled from",
    "related_to": "Related to",
}


def _relationship_label(value: str | None) -> str:
    if not value:
        return "Related"
    key = value.strip().lower()
    if key in _RELATIONSHIP_LABELS:
        return _RELATIONSHIP_LABELS[key]
    return value.replace("_", " ").strip().capitalize() or "Related"


def show_merger(
    merger: Merger,
    questionnaire: Questionnaire | None,
    section: str = "all",
    nocc: Nocc | None = None,
) -> None:
    c = console()

    header_lines = [
        f"[bold cyan]{merger.merger_id}[/] — [bold]{merger.merger_name}[/]",
    ]
    outcome = merger.outcome_text()
    header_lines.append(
        f"Status: {merger.status or '—'}   "
        f"Stage: {merger.stage or '—'}   "
        f"Outcome: [{outcome_style(merger.outcome())}]{outcome}[/]"
    )
    kind = "Waiver" if merger.is_waiver else "Notification"
    header_lines.append(
        f"Type: {kind}   "
        f"Notified: {format_date(merger.effective_notification_datetime)}   "
        f"Determined: {format_date(merger.determination_publication_date)}"
    )
    if merger.is_ceased() and merger.ceased_date:
        header_lines.append(
            f"[magenta]Assessment ceased:[/] {_format_event_date(merger.ceased_date)}"
        )
    if merger.related_merger:
        rel = merger.related_merger
        label = _relationship_label(rel.relationship)
        name = rel.merger_name or ""
        suffix = f" — {name}" if name else ""
        header_lines.append(
            f"[magenta]{label}:[/] [bold cyan]{rel.merger_id}[/]{suffix}"
        )
    if merger.public_benefit_in_progress or merger.public_benefits_determination:
        header_lines.append(_public_benefit_summary(merger))
    appeals = merger.tribunal_appeals()
    if appeals:
        style = "red" if merger.under_appeal else "dim"
        tag = "Under appeal" if merger.under_appeal else "Appeal"
        summary = merger.appeal or appeals[0]
        header_lines.append(f"[{style}]{tag}:[/] {_appeal_summary(summary)}")
    reviews = merger.federal_court_reviews()
    if reviews:
        style = "red" if merger.under_judicial_review else "dim"
        tag = "Under judicial review" if merger.under_judicial_review else "Judicial review"
        header_lines.append(
            f"[{style}]{tag}:[/] "
            + "; ".join(_judicial_review_summary(r) for r in reviews)
        )
    if merger.phase_1_estimate:
        header_lines.append(f"[dim]{_phase_1_estimate_summary(merger.phase_1_estimate)}[/]")
    pre = _pre_notification_text(merger.pre_notification_summary)
    if pre:
        header_lines.append(f"[dim]{pre}[/]")
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

    if section in ("all", "nocc") and nocc:
        _render_nocc(nocc)

    if section in ("all", "appeal") and (
        merger.tribunal_appeals() or merger.federal_court_reviews()
    ):
        _render_appeal(merger)

    if section == "all":
        _render_foi(merger)
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
    c = console()

    filter_map = {
        "reasons": "reasons for determination",
        "overlap": "overlap and relationship between the parties",
    }
    target = filter_map.get(section)

    rendered = False
    if sections:
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
            rendered = True

    if not rendered and section == "reasons":
        all_text = merger.all_determination_text()
        if all_text:
            c.print(Panel(all_text.strip(), title="Determination (full text)", border_style="magenta"))
            c.print(
                f"[dim]Note: no structured 'Reasons for determination' available; "
                f"showing full determination text.[/]"
            )
        else:
            c.print(
                f"[yellow]No reasons text available for this merger. "
                f"Try `mergers show {merger.merger_id}` to see the full record.[/]"
            )


_MISSING = object()


def _render_questionnaire(q: Questionnaire) -> None:
    c = console()
    lines = [
        f"[bold]Deadline:[/] {q.deadline or '—'}   [bold]Questions:[/] {q.questions_count}"
    ]
    if q.file_name:
        lines.append(f"[bold]File:[/] {q.file_name}")
    if len(q.all_questionnaires) > 1:
        lines.append(f"[dim]{len(q.all_questionnaires)} questionnaire versions on record[/]")

    current_section: object = _MISSING
    for i, question in enumerate(q.questions, start=1):
        number = question.get("number") or question.get("question_number") or i
        text = (
            question.get("text")
            or question.get("question")
            or question.get("question_text")
            or ""
        )
        section = question.get("section")
        if section != current_section:
            current_section = section
            if section:
                lines.append(f"\n[bold underline]{section}[/]")
        lines.append(f"\n[bold]{number}.[/] {text.strip()}")
    c.print(Panel("\n".join(lines), title="Questionnaire", border_style="yellow"))


def _render_nocc(nocc: Nocc) -> None:
    c = console()
    header_bits: list[str] = []
    if nocc.document_type:
        header_bits.append(f"[bold]{nocc.document_type}[/]")
    if nocc.date:
        header_bits.append(f"[bold]Date:[/] {nocc.date}")
    if nocc.file_name:
        header_bits.append(f"[bold]File:[/] {nocc.file_name}")
    lines: list[str] = []
    if header_bits:
        lines.append("   ".join(header_bits))

    for s in nocc.sections:
        if lines:
            lines.append("")
        title_parts = [
            p for p in [s.number, s.title] if p and str(p).strip()
        ]
        if title_parts:
            lines.append(f"[bold underline]{' '.join(title_parts)}[/]")
        for block in s.blocks:
            text = (block.text or "").strip()
            if not text:
                continue
            if block.type == "heading":
                lines.append(f"\n[bold]{text}[/]")
            elif block.number:
                lines.append(f"\n[bold]{block.number}.[/] {text}")
            else:
                lines.append(f"\n{text}")
    c.print(
        Panel(
            "\n".join(lines) if lines else "(no content)",
            title="Notice of Competition Concerns",
            border_style="red",
        )
    )


# Mirror the site's constants/appeal.js and constants/judicialReview.js.
APPEAL_TYPE_LABELS: dict[str, str] = {
    "party_denial": "Appeal against refusal",
    "party_conditional_clearance": "Appeal against conditional clearance",
    "third_party_clearance": "Third party appeal against clearance",
}

APPEAL_OUTCOME_LABELS: dict[str, str] = {
    "affirmed": "ACCC decision affirmed",
    "set_aside": "ACCC decision set aside",
    "varied": "ACCC decision varied",
    "withdrawn": "Appeal withdrawn",
    "dismissed": "Appeal dismissed",
}

JUDICIAL_REVIEW_OUTCOME_LABELS: dict[str, str] = {
    "withdrawn": "Review discontinued",
    "dismissed": "Application dismissed",
    "set_aside": "ACCC decision set aside",
}


def _appeal_type_label(value: str | None) -> str | None:
    if not value:
        return None
    return APPEAL_TYPE_LABELS.get(value, value.replace("_", " ").capitalize())


def _appeal_state(appeal: dict[str, Any]) -> str:
    if appeal.get("status") != "concluded":
        return "Current"
    return APPEAL_OUTCOME_LABELS.get(appeal.get("outcome") or "", "Concluded")


def judicial_review_state(review: dict[str, Any]) -> str:
    """How a Federal Court review stands: "Ongoing", or its outcome."""
    if review.get("status") != "concluded":
        return "Ongoing"
    return JUDICIAL_REVIEW_OUTCOME_LABELS.get(review.get("outcome") or "", "Concluded")


def _appeal_summary(appeal: dict[str, Any]) -> str:
    bits = [
        b
        for b in [
            appeal.get("tribunal_number"),
            _appeal_type_label(appeal.get("appeal_type")),
            appeal.get("appellant"),
        ]
        if b
    ]
    text = " — ".join(bits) if bits else "(no tribunal number recorded)"
    return f"{text} ({_appeal_state(appeal).lower()})"


def _judicial_review_summary(review: dict[str, Any]) -> str:
    bits = [
        b
        for b in [review.get("case_number"), review.get("applicant")]
        if b
    ]
    text = " — ".join(bits) if bits else "(no case number recorded)"
    return f"{text} ({judicial_review_state(review).lower()})"


def _public_benefit_summary(merger: Merger) -> str:
    if merger.public_benefits_determination:
        return (
            f"[bold]Public benefit determination:[/] {merger.public_benefits_determination}"
        )
    bits = ["[yellow]Public benefit application under assessment[/]"]
    if merger.phase_2_determination:
        bits.append(f"Phase 2 determination: {merger.phase_2_determination}")
    if merger.public_benefit_application_date:
        bits.append(f"applied {_format_event_date(merger.public_benefit_application_date)}")
    return " · ".join(bits)


_PRE_NOTIFICATION_KIND_TEXT: dict[str, str] = {
    "around": "began around",
    "after": "began after",
    "before": "began before",
}


def _pre_notification_text(summary: dict[str, Any] | None) -> str | None:
    """One line for the condensed pre-notification estimate, as the site reads it.

    ``kind`` says how to read ``start_date``: ``around`` (bracketed), ``after``
    (only the earliest start is known), ``before`` (only the latest), or
    ``none`` (no pre-notification period detectable).
    """
    if not summary:
        return None
    kind = summary.get("kind")
    confidence = summary.get("confidence")
    conf = f" ({confidence} confidence)" if confidence else ""
    if kind == "none":
        return f"Estimated pre-notification: none detected{conf}"
    start = summary.get("start_date")
    phrase = _PRE_NOTIFICATION_KIND_TEXT.get(kind or "")
    if not start or not phrase:
        return None
    return f"Estimated pre-notification {phrase} {_format_event_date(start)}{conf}"


def _phase_1_estimate_summary(estimate: dict[str, Any]) -> str:
    days = estimate.get("expected_business_days")
    if days is None:
        return "Estimated phase 1 duration: unavailable"
    rng = estimate.get("range_business_days")
    range_text = f" (typically {rng[0]}–{rng[1]} business days)" if isinstance(rng, list) and len(rng) == 2 else ""
    basis = estimate.get("basis")
    basis_text = f", based on {basis} history" if basis else ""
    return f"Estimated phase 1 duration at filing: {days} business days{range_text}{basis_text}"


def _render_appeal(merger: Merger) -> None:
    c = console()
    lines: list[str] = []

    for a in merger.tribunal_appeals():
        if lines:
            lines.append("")
        lines.append("[bold underline]Australian Competition Tribunal appeal[/]")
        hearing = a.get("hearing_date")
        if hearing and a.get("hearing_end_date") and a["hearing_end_date"] != hearing:
            hearing = (
                f"{_format_event_date(hearing)} – {_format_event_date(a['hearing_end_date'])}"
            )
        elif hearing:
            hearing = _format_event_date(hearing)
        rows = [
            ("Tribunal number", a.get("tribunal_number")),
            ("Type", _appeal_type_label(a.get("appeal_type"))),
            ("Appellant", a.get("appellant")),
            ("Status", _appeal_state(a)),
            ("Effective determination", a.get("effective_determination")),
            ("Filed", _format_event_date(a.get("filed_date")) if a.get("filed_date") else None),
            ("Hearing", hearing),
            (
                "Concluded",
                _format_event_date(a.get("concluded_date")) if a.get("concluded_date") else None,
            ),
            ("Tribunal URL", a.get("tribunal_url")),
        ]
        for label, value in rows:
            if value:
                lines.append(f"[bold]{label}:[/] {value}")
        documents = sorted(
            (d for d in (a.get("documents") or []) if isinstance(d, dict)),
            key=lambda d: str(d.get("date") or ""),
            reverse=True,
        )
        if documents:
            lines.append("")
            lines.append(f"[bold]Documents ({len(documents)}):[/]")
            for doc in documents:
                name = (
                    doc.get("description")
                    or doc.get("title")
                    or doc.get("file_name")
                    or "(untitled)"
                )
                by = doc.get("filed_by")
                if by and by != "-":
                    name = f"{name} ({by})"
                date = _format_event_date(doc.get("date")) if doc.get("date") else ""
                prefix = f"{date}  " if date else ""
                lines.append(f"  • {prefix}{name}")

    for jr in merger.federal_court_reviews():
        if lines:
            lines.append("")
        lines.append("[bold underline]Federal Court judicial review[/]")
        for label, value in (
            ("Case number", jr.get("case_number")),
            ("Court", jr.get("court")),
            ("Applicant", jr.get("applicant")),
            ("Status", judicial_review_state(jr)),
            ("Filed", _format_event_date(jr.get("filed_date")) if jr.get("filed_date") else None),
            (
                "Concluded",
                _format_event_date(jr.get("concluded_date")) if jr.get("concluded_date") else None,
            ),
            ("Next hearing", _next_hearing_text(jr)),
            ("Case URL", jr.get("case_url")),
        ):
            if value:
                lines.append(f"[bold]{label}:[/] {value}")

    if not lines:
        return
    c.print(Panel("\n".join(lines), title="Appeal / judicial review", border_style="red"))


def _next_hearing_text(review: dict[str, Any], today: dt.date | None = None) -> str | None:
    """The review's next hearing someone attends (not chambers/administrative)."""
    today = today or dt.date.today()
    upcoming = []
    for listing in review.get("listings") or []:
        if not isinstance(listing, dict) or not listing.get("hearing"):
            continue
        try:
            day = dt.date.fromisoformat(str(listing.get("date"))[:10])
        except ValueError:
            continue
        if day >= today:
            upcoming.append((day, listing))
    if not upcoming:
        return None
    day, listing = min(upcoming, key=lambda x: x[0])
    bits = [day.strftime("%d %b %Y")]
    if listing.get("time"):
        bits.append(str(listing["time"]))
    if listing.get("reason"):
        bits.append(f"— {listing['reason']}")
    return " ".join(bits)


def _render_foi(merger: Merger) -> None:
    if not merger.foi_disclosures:
        return
    c = console()
    lines = []
    for f in merger.foi_disclosures:
        bits = [f.get("reference") or "FOI release"]
        if f.get("published_date"):
            bits.append(_format_event_date(f["published_date"]))
        if f.get("document_count"):
            bits.append(f"{f['document_count']} documents")
        lines.append("[bold]" + " · ".join(bits) + "[/]")
        if f.get("description"):
            lines.append(f["description"])
        if f.get("url"):
            lines.append(f"[dim]{f['url']}[/]")
    c.print(Panel("\n".join(lines), title="FOI disclosures", border_style="blue"))


def show_nocc_list(rows: Iterable[Any]) -> None:
    c = console()
    table = Table(title="Notices of Competition Concerns", expand=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Name", overflow="fold")
    table.add_column("Date", no_wrap=True)
    table.add_column("Document type", overflow="fold")
    for row in rows:
        table.add_row(
            row["merger_id"],
            row["merger_name"] or "",
            row["date"] or "—",
            row["document_type"] or "—",
        )
    c.print(table)


def show_nocc_matches(rows: Iterable[Any]) -> None:
    c = console()
    table = Table(title="Matching NOCC paragraphs", expand=True)
    table.add_column("ID", style="bold cyan")
    table.add_column("Merger", overflow="fold")
    table.add_column("§", no_wrap=True)
    table.add_column("Excerpt", overflow="fold")
    for row in rows:
        ref = row["block_number"] or row["section_number"] or ""
        table.add_row(
            row["merger_id"],
            row["merger_name"] or "",
            str(ref),
            row["block_text"] or "",
        )
    c.print(table)


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


def show_questionnaire_version(data: dict[str, Any]) -> None:
    """Render questions from a questionnaire data dict (primary or a version entry)."""
    c = console()
    deadline = data.get("deadline") or "—"
    count = data.get("questions_count") or len(data.get("questions") or [])
    header = f"Deadline: {deadline}  |  {count} questions"
    if data.get("file_name"):
        header += f"  |  {data['file_name']}"
    c.print(header)
    c.print()
    current_section: object = _MISSING
    for i, question in enumerate(data.get("questions") or [], start=1):
        number = question.get("number") or question.get("question_number") or i
        text = (
            question.get("text")
            or question.get("question")
            or question.get("question_text")
            or ""
        )
        section = question.get("section")
        if section != current_section:
            current_section = section
            if section:
                c.print(f"[bold underline]{section}[/]\n")
        c.print(f"[bold]{number}.[/] {text.strip()}\n")


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


def _fmt_num(value: Any, places: int = 1) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{places}f}"
    return str(value)


def _counts_table(title: str, counts: dict[str, Any]) -> Table:
    table = Table(title=title, expand=True)
    table.add_column("Value", overflow="fold")
    table.add_column("Count", justify="right")
    for key, value in sorted(counts.items(), key=lambda kv: -(kv[1] or 0)):
        table.add_row(str(key), str(value))
    return table


def show_stats(stats: dict[str, Any]) -> None:
    """Render the upstream stats.json (the numbers on mergers.fyi's dashboard)."""
    c = console()
    if not stats:
        c.print("[yellow]No stats available. Run `mergers sync` first.[/]")
        return

    table = Table(title="Totals", expand=True)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    for key, label in (
        ("total_mergers", "Notifications"),
        ("total_waivers", "Waiver applications"),
        ("total_conditional_approvals", "Approved with conditions"),
    ):
        if key in stats:
            table.add_row(label, str(stats[key]))
    clearance = stats.get("clearance_rate") or {}
    if clearance:
        table.add_row(
            "Clearance rate",
            f"{_fmt_num((clearance.get('rate') or 0) * 100)}% "
            f"({clearance.get('cleared', '—')} of {clearance.get('total', '—')})",
        )
    c.print(table)

    durations = [
        ("Phase 1 (notifications)", stats.get("phase_duration")),
        ("Waivers", stats.get("waiver_duration")),
    ]
    if any(isinstance(d, dict) for _, d in durations):
        table = Table(title="Time to determination", expand=True)
        table.add_column("Matter", style="bold")
        table.add_column("Median (business days)", justify="right")
        table.add_column("Average (business days)", justify="right")
        table.add_column("Median (calendar days)", justify="right")
        table.add_column("Average (calendar days)", justify="right")
        for label, d in durations:
            if not isinstance(d, dict):
                continue
            table.add_row(
                label,
                _fmt_num(d.get("median_business_days")),
                _fmt_num(d.get("average_business_days")),
                _fmt_num(d.get("median_days")),
                _fmt_num(d.get("average_days")),
            )
        c.print(table)
        percentiles = (stats.get("phase_duration") or {}).get("percentiles") or {}
        if percentiles:
            bits = []
            for key, entry in percentiles.items():
                if not isinstance(entry, dict):
                    continue
                day = key.replace("day", "")
                bits.append(f"{_fmt_num(entry.get('percentage'))}% by business day {day}")
            if bits:
                c.print(f"[dim]Phase 1 determinations: {', '.join(bits)}.[/]")

    for key, title in (
        ("by_status", "By status"),
        ("by_determination", "Phase 1 determinations"),
        ("by_phase_2_determination", "Phase 2 determinations"),
        ("by_waiver_determination", "Waiver determinations"),
    ):
        counts = stats.get(key)
        if isinstance(counts, dict) and counts:
            c.print(_counts_table(title, counts))

    top = stats.get("top_industries")
    if isinstance(top, list) and top:
        table = Table(title="Top industries", expand=True)
        table.add_column("Industry", overflow="fold")
        table.add_column("Count", justify="right")
        for entry in top[:10]:
            if isinstance(entry, dict):
                table.add_row(str(entry.get("name") or "—"), str(entry.get("count") or "—"))
        c.print(table)

    recent = stats.get("recent_determinations")
    if isinstance(recent, list) and recent:
        table = Table(title="Recent determinations", expand=True)
        table.add_column("ID", style="bold cyan")
        table.add_column("Name", overflow="fold")
        table.add_column("Outcome")
        table.add_column("Date", no_wrap=True)
        for entry in recent[:10]:
            if not isinstance(entry, dict):
                continue
            outcome = entry.get("determination") or "—"
            if outcome == "Approved" and entry.get("has_conditions"):
                outcome = "Approved with conditions"
            table.add_row(
                str(entry.get("merger_id") or ""),
                str(entry.get("merger_name") or ""),
                Text(outcome, style=outcome_style(outcome)),
                _format_event_date(entry.get("determination_date")),
            )
        c.print(table)


def _parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_event_date(value: str | None) -> str:
    if not value:
        return "—"
    parsed = _parse_iso(value)
    if parsed is not None:
        return parsed.strftime("%d %b %Y")
    return value[:10] if len(value) >= 10 else value


def _days_between(a: str | None, b: str | None) -> int | None:
    start = _parse_iso(a)
    end = _parse_iso(b)
    if not start or not end:
        return None
    return (end.date() - start.date()).days


_EVENT_LABELS: dict[str, str] = {
    "notification": "Notification lodged",
    "determination": "Determination issued",
    "phase_1": "Phase 1 determination",
    "phase_1_determination": "Phase 1 determination",
    "phase_2": "Phase 2 determination",
    "phase_2_determination": "Phase 2 determination",
    "phase_2_referral": "Referred to Phase 2",
    "referral": "Referred to Phase 2",
    "waiver": "Waiver determination",
    "waiver_granted": "Waiver granted",
    "waiver_denied": "Waiver denied",
    "public_register": "Public register updated",
    "public_register_update": "Public register updated",
    "submission": "Submission received",
    "consultation": "Consultation opened",
    "consultation_closed": "Consultation closed",
    "withdrawn": "Notification withdrawn",
    "opposed": "ACCC opposed",
    "not_opposed": "ACCC did not oppose",
}


# Ordered patterns used to classify free-form event titles from the register.
# The first match wins, so keep more specific phrases above generic ones.
_TITLE_PATTERNS: list[tuple[str, str]] = [
    ("phase 2 review", "Referred to Phase 2"),
    ("phase 2 notice", "Phase 2 notice issued"),
    ("extend the phase 1", "Phase 1 period extended"),
    ("extend the phase 2", "Phase 2 period extended"),
    ("phase 1 determination period", "Phase 1 period extended"),
    ("phase 2 determination period", "Phase 2 period extended"),
    ("phase 2 determination", "Phase 2 determination"),
    ("phase 1 determination", "Phase 1 determination"),
    ("not have an effective notification", "Notification ruled incomplete"),
    ("materially incomplete", "Notification ruled incomplete"),
    ("effective notification date", "Effective notification confirmed"),
    ("merger notified", "Merger notified to ACCC"),
    ("notification withdrawn", "Notification withdrawn"),
    ("third party questionnaire", "Third-party questionnaire"),
    ("questionnaire", "Questionnaire published"),
    ("submission", "Submission received"),
    ("statement of issues", "Statement of issues"),
    ("undertaking", "Undertaking lodged"),
    ("waiver granted", "Waiver granted"),
    ("waiver denied", "Waiver denied"),
    ("waiver", "Waiver update"),
    ("determination", "Determination issued"),
    ("public register", "Public register updated"),
]


def _label_from_title(title: str) -> str:
    lowered = title.lower()
    for needle, label in _TITLE_PATTERNS:
        if needle in lowered:
            return label
    # Keep short titles intact; truncate long legalese to a single clause.
    cleaned = title.strip().rstrip(".")
    if len(cleaned) <= 60:
        return cleaned
    first_clause = cleaned.split(",")[0].split(".")[0]
    return first_clause[:60].rstrip() + "…"


def _humanize_event_label(
    event_type: str | None, title: str | None = None
) -> str:
    if event_type:
        key = event_type.strip().lower().replace(" ", "_")
        if key in _EVENT_LABELS:
            return _EVENT_LABELS[key]
        pretty = event_type.replace("_", " ").strip()
        if pretty:
            return pretty[:1].upper() + pretty[1:]
    if title:
        return _label_from_title(title)
    return "Milestone"


_EXTENSION_RE = re.compile(r"extended by (\d+)\s+business day", re.IGNORECASE)
_EXTENSION_REASON_RE = re.compile(r"following\s+(.*)$", re.IGNORECASE)


def _extension_label(title: str) -> tuple[str, str] | None:
    """(label, reason) for a timeline-extension notice, else None.

    Same reading as the upstream extensions output and the site's
    timelineExtensions.js (pinned there by fixtures/extension-title-cases.json).
    """
    # Older "ACCC decided to extend the Phase 1 determination period" notices
    # fall through to _TITLE_PATTERNS, which name the phase.
    if "extended by" not in (title or "").lower():
        return None
    match = _EXTENSION_RE.search(title)
    label = (
        f"Timeline extended (+{match.group(1)} business day{'s' if match.group(1) != '1' else ''})"
        if match
        else "Timeline extended"
    )
    reason = _EXTENSION_REASON_RE.search(title)
    detail = re.sub(r"\s+", " ", reason.group(1)).strip().rstrip(".") if reason else ""
    return label, detail


def _classify_event(event: Event) -> tuple[str, str]:
    """(label, detail) for one register event, using the pipeline's own flags first."""
    raw = event.raw
    title = event.title or ""
    base_title = raw.get("title") or title
    if raw.get("is_appeal"):
        # display_title already reads "Tribunal appeal – …" / "Federal Court – …".
        detail_bits = [
            b
            for b in (
                raw.get("court_outcome"),
                raw.get("appeal_filed_by") if raw.get("appeal_filed_by") not in (None, "-") else None,
                raw.get("tribunal_number") or raw.get("case_number"),
            )
            if b
        ]
        return (raw.get("appeal_base_title") or title or "Review event", " · ".join(detail_bits))
    if raw.get("is_determination_event"):
        return (title or "Determination issued", base_title if base_title != title else "")
    if raw.get("is_questionnaire_event") or "questionnaire" in base_title.lower():
        return ("Questionnaire published", base_title)
    extension = _extension_label(base_title)
    if extension:
        return extension
    label = _humanize_event_label(event.event_type, title)
    detail = event.description or (title if label != title else "")
    return label, detail or ""


def timeline_events(merger: Merger) -> list[dict[str, Any]]:
    """Flatten a merger's timeline into sortable event records.

    Combines the notification date, determination publication date, and
    any events carried in ``merger.events``, de-duplicating entries that
    share the same date and type. An FOI release's documents collapse into one
    row per release date. Returns records with ``date``, ``label``, and
    optional ``description`` keys sorted chronologically.
    """
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def _add(date: str | None, label: str, description: str | None = None) -> None:
        if not date:
            return
        key = (date[:10], label.lower())
        if key in seen:
            return
        seen.add(key)
        records.append(
            {"date": date, "label": label, "description": description or ""}
        )

    notification_label = (
        "Waiver application lodged" if merger.is_waiver else "Notification lodged"
    )
    _add(merger.effective_notification_datetime, notification_label)

    foi_by_day: dict[str, list[Event]] = {}
    determination_days: set[str] = set()
    for event in merger.events:
        if not event.event_date:
            continue
        if event.raw.get("is_foi"):
            foi_by_day.setdefault(event.event_date[:10], []).append(event)
            continue
        if event.raw.get("is_determination_event"):
            determination_days.add(event.event_date[:10])
        label, detail = _classify_event(event)
        _add(event.event_date, label, detail)

    for day, events in foi_by_day.items():
        refs = sorted({e.raw.get("foi_reference") for e in events if e.raw.get("foi_reference")})
        n = len(events)
        _add(
            events[0].event_date,
            f"FOI release ({n} document{'s' if n != 1 else ''})",
            ", ".join(refs),
        )

    if merger.is_ceased() and merger.ceased_date and not any(
        "ceased" in (e.title or "").lower()
        for e in merger.events
        if (e.event_date or "")[:10] == merger.ceased_date[:10]
    ):
        _add(merger.ceased_date, "Assessment ceased")
    pub = merger.determination_publication_date
    if pub and pub[:10] not in determination_days:
        _add(pub, "Determination published")

    records.sort(key=lambda r: (r["date"] or "")[:10])
    return records


def upcoming_dates(merger: Merger, today: dt.date | None = None) -> list[dict[str, Any]]:
    """Dated milestones still to come: statutory deadline, public benefit dates, hearings."""
    today = today or dt.date.today()
    out: list[dict[str, Any]] = []

    def _add(date: str | None, label: str) -> None:
        parsed = _parse_iso(date) if date else None
        if parsed is None:
            try:
                parsed_day = dt.date.fromisoformat(str(date)[:10]) if date else None
            except ValueError:
                parsed_day = None
        else:
            parsed_day = parsed.date()
        if parsed_day and parsed_day >= today:
            out.append({"date": str(date), "label": label})

    live = merger.outcome() is None and not merger.is_ceased()
    if live:
        _add(merger.public_benefit_response_date, "Public benefit responses / remedy offer due")
        _add(merger.end_of_determination_period, "Determination due (statutory deadline)")
    for a in merger.tribunal_appeals():
        if a.get("status") != "concluded" and a.get("hearing_date"):
            _add(a["hearing_date"], f"Tribunal hearing ({a.get('tribunal_number') or 'appeal'})")
    for jr in merger.federal_court_reviews():
        if jr.get("status") == "concluded":
            continue
        for listing in jr.get("listings") or []:
            if isinstance(listing, dict) and listing.get("hearing") and listing.get("date"):
                reason = listing.get("reason") or "hearing"
                _add(listing["date"], f"Federal Court {reason.lower()} ({jr.get('case_number') or 'review'})")
    out.sort(key=lambda r: r["date"][:10])
    return out


def show_timeline(merger: Merger, show_detail: bool = False) -> None:
    c = console()
    header = (
        f"[bold cyan]{merger.merger_id}[/] — [bold]{merger.merger_name}[/]\n"
        f"Stage: {merger.stage or '—'}   "
        f"Outcome: [{outcome_style(merger.outcome())}]{merger.outcome_text()}[/]"
    )
    c.print(Panel(header, border_style="cyan"))

    events = timeline_events(merger)
    if not events:
        c.print("[yellow]No dated events recorded for this merger.[/]")
        return

    table = Table(title="Timeline", expand=True)
    table.add_column("Date", no_wrap=True, style="bold")
    table.add_column("Event", no_wrap=True)
    table.add_column("Days from notification", justify="right", no_wrap=True)
    if show_detail:
        table.add_column("Detail", overflow="fold")

    notification_date = merger.effective_notification_datetime
    for event in events:
        delta = _days_between(notification_date, event["date"])
        delta_display = "—" if delta is None else ("0" if delta == 0 else f"+{delta}")
        row = [
            _format_event_date(event["date"]),
            event["label"],
            delta_display,
        ]
        if show_detail:
            row.append(event["description"] or "")
        table.add_row(*row)
    c.print(table)

    end = merger.determination_publication_date
    end_label = "determination"
    if merger.is_ceased() and merger.ceased_date:
        end, end_label = merger.ceased_date, "assessment ceased"
    total_days = _days_between(merger.effective_notification_datetime, end)
    if total_days is not None:
        c.print(
            f"[dim]Total duration:[/] notification → {end_label} = "
            f"{total_days} days"
        )

    upcoming = upcoming_dates(merger)
    if upcoming:
        c.print("[bold]Upcoming:[/]")
        for item in upcoming:
            c.print(f"  {_format_event_date(item['date'])}  {item['label']}")


def warn_stale_cache(age_days: float) -> None:
    c = console()
    c.print(
        f"[yellow]Warning:[/] local cache is {age_days:.1f} days old — "
        "run `mergers sync` to refresh."
    )


def _render_snippet_markup(raw: str) -> str:
    """Convert a snippet string with ⟪…⟫ match markers to Rich markup.

    Any Rich-special characters in the surrounding text are escaped so they
    are displayed literally.
    """
    from rich.markup import escape

    open_m, close_m = "⟪", "⟫"
    parts = raw.split(open_m)
    result = escape(parts[0])
    for part in parts[1:]:
        inside_out = part.split(close_m, 1)
        if len(inside_out) == 2:
            result += f"[bold]{escape(inside_out[0])}[/bold]{escape(inside_out[1])}"
        else:
            result += f"[bold]{escape(inside_out[0])}[/bold]"
    return result


def render_results_with_snippets(
    rows: list[Any],
    snippets: dict[str, str | None],
) -> None:
    """Print each result as a brief text block with an optional excerpt below it."""
    c = console()
    for row in rows:
        merger_id, name, determination, _phase, _industry, date = render_row(row)
        style = outcome_style(determination)
        c.print(
            f"  [bold cyan]{merger_id}[/]  {name}  "
            f"[{style}]{determination or 'Pending'}[/]  [dim]{date}[/]"
        )
        snip = snippets.get(row["merger_id"])
        if snip:
            c.print(f"  [dim italic]{_render_snippet_markup(snip)}[/]")
        c.print()


def print_json(payload: Any) -> None:
    console().print_json(data=payload, default=str)
