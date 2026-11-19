"""Records shaped like the upstream register as it stands now (schema v3).

Covers the fields and states the main repo added after the CLI first learned
about appeals: ceased assessments, conditional clearances, the public benefit
phase, multiple Tribunal matters, per-file Federal Court reviews, FOI releases
and the condensed pre-notification estimate.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from typer.testing import CliRunner

from mergers import db, display
from mergers.cli import app
from mergers.db import SearchFilters
from mergers.models import Merger
from tests._index_builder import build_database


def _merger(merger_id: str, **overrides) -> dict:
    base = {
        "merger_id": merger_id,
        "merger_name": f"Merger {merger_id}",
        "status": "Assessment completed",
        "stage": "Phase 1 - initial assessment",
        "is_waiver": False,
        "acquirers": [{"name": "Acquirer"}],
        "targets": [{"name": "Target"}],
        "anzsic_codes": [],
        "merger_description": "A description.",
        "effective_notification_datetime": "2026-03-03T12:00:00Z",
        "events": [],
    }
    base.update(overrides)
    return base


CEASED = _merger(
    "MN-30002",
    status="Assessment ceased",
    stage="Phase 2 - detailed assessment",
    phase_1_determination="Referred to phase 2",
    ceased_date="2026-06-15T12:00:00Z",
)
CONDITIONAL = _merger(
    "MN-80005",
    accc_determination="Approved",
    phase_1_determination="Approved",
    has_conditions=True,
    determination_publication_date="2026-09-01T12:00:00Z",
)
PUBLIC_BENEFIT = _merger(
    "MN-65005",
    status="Under assessment",
    stage="Public benefit phase",
    accc_determination=None,
    phase_1_determination="Referred to phase 2",
    phase_2_determination="Not approved",
    public_benefit_in_progress=True,
    public_benefit_application_date="2026-10-13T12:00:00Z",
    public_benefit_response_date="2099-12-01T12:00:00Z",
    end_of_determination_period="2099-02-01T12:00:00Z",
    under_appeal=True,
    appeal={
        "tribunal_number": "ACT 3 of 2026 and ACT 4 of 2026",
        "appeal_type": "party_denial",
        "appellant": "IAG and RACWA",
        "status": "current",
    },
    appeals=[
        {
            "tribunal_number": "ACT 3 of 2026",
            "appeal_type": "party_denial",
            "appellant": "IAG",
            "status": "current",
            "hearing_date": "2099-03-30",
            "documents": [
                {"date": "2026-10-01", "description": "Application for review", "filed_by": "IAG"},
                {"date": "2026-10-09", "description": "Directions", "filed_by": "-"},
            ],
        },
        {
            "tribunal_number": "ACT 4 of 2026",
            "appeal_type": "party_denial",
            "appellant": "RACWA",
            "status": "current",
            "documents": [
                {"date": "2026-10-05", "description": "Application to Tribunal for Review"},
            ],
        },
    ],
    pre_notification_summary={"kind": "around", "start_date": "2026-02-08", "confidence": "medium"},
)
JUDICIAL_REVIEW = _merger(
    "MN-01068",
    accc_determination="Not approved",
    stage="Phase 2 - detailed assessment",
    phase_2_determination="Not approved",
    judicial_review={"case_number": "NSD1310/2026", "applicant": "Coles", "status": "concluded"},
    judicial_reviews=[
        {
            "case_number": "NSD1310/2026",
            "applicant": "Coles",
            "status": "concluded",
            "outcome": "withdrawn",
            "court": "Federal Court of Australia",
        }
    ],
)
LIVE_REVIEW = _merger(
    "MN-01070",
    accc_determination="Not approved",
    stage="Phase 2 - detailed assessment",
    phase_2_determination="Not approved",
    under_judicial_review=True,
    judicial_reviews=[
        {
            "case_number": "NSD9/2026",
            "status": "current",
            "listings": [
                {"date": "2099-01-10", "time": "10:15", "reason": "Hearing", "hearing": True},
                {"date": "2099-01-05", "reason": "Administrative Listing", "hearing": False},
            ],
        }
    ],
)
SET_ASIDE = _merger(
    "MN-01080",
    accc_determination="Not approved",
    appeal={
        "tribunal_number": "ACT 9 of 2026",
        "status": "concluded",
        "outcome": "set_aside",
        "effective_determination": "Approved",
    },
)
FOI_WAIVER = _merger(
    "WA-80019",
    stage="Waiver application",
    is_waiver=True,
    accc_determination="Approved",
    effective_notification_datetime="2026-05-22T12:00:00Z",
    determination_publication_date="2026-06-22T12:00:00Z",
    foi_disclosures=[
        {"reference": "100473/2026-2027", "published_date": "2026-10-20", "document_count": 2}
    ],
    events=[
        {
            "date": "2026-06-22T12:00:00Z",
            "title": "Notification waiver determination published",
            "display_title": "Waiver application determination: Approved",
            "is_determination_event": True,
        },
        {
            "date": "2026-10-20T12:00:00Z",
            "title": "Waiver application – Part B responses",
            "display_title": "FOI release – Waiver application – Part B responses",
            "is_foi": True,
            "foi_reference": "100473/2026-2027",
        },
        {
            "date": "2026-10-20T12:00:00Z",
            "title": "Waiver application – parties",
            "display_title": "FOI release – Waiver application – parties",
            "is_foi": True,
            "foi_reference": "100473/2026-2027",
        },
    ],
)

ALL = [CEASED, CONDITIONAL, PUBLIC_BENEFIT, JUDICIAL_REVIEW, LIVE_REVIEW, SET_ASIDE, FOI_WAIVER]


@pytest.fixture
def upstream_db(temp_cache):
    build_database(db.DB_PATH, {"mergers": ALL})
    # Suppress the auto-sync the CLI commands would otherwise attempt.
    db.LAST_SYNC_PATH.write_text(dt.datetime.now(dt.timezone.utc).isoformat())
    return db.DB_PATH


@pytest.mark.parametrize(
    "record, expected",
    [
        (CEASED, "Assessment ceased"),
        (CONDITIONAL, "Approved with conditions"),
        (PUBLIC_BENEFIT, None),
        (JUDICIAL_REVIEW, "Not approved"),
        (SET_ASIDE, "Approved"),
        (FOI_WAIVER, "Approved"),
    ],
)
def test_outcome_matches_site(record, expected):
    assert Merger.from_dict(record).outcome() == expected


def test_outcome_text_qualifiers():
    assert Merger.from_dict(SET_ASIDE).outcome_text() == "Approved · on appeal"
    assert Merger.from_dict(PUBLIC_BENEFIT).outcome_text() == "Under assessment"
    decided = dict(CONDITIONAL, public_benefits_determination="Approved")
    assert (
        Merger.from_dict(decided).outcome_text()
        == "Approved with conditions · after public benefit review"
    )


def _list(filters: SearchFilters) -> list[str]:
    conn = db.connect()
    try:
        return sorted(r["merger_id"] for r in db.list_mergers(conn, filters))
    finally:
        conn.close()


def test_outcome_filters(upstream_db):
    assert _list(SearchFilters(outcome="ceased", limit=50)) == ["MN-30002"]
    assert _list(SearchFilters(outcome="conditional", limit=50)) == ["MN-80005"]
    approved = _list(SearchFilters(outcome="approved", limit=50))
    assert "MN-80005" in approved and "MN-01080" in approved
    assert "MN-30002" not in _list(SearchFilters(outcome="pending", limit=50))
    assert "MN-65005" in _list(SearchFilters(outcome="pending", limit=50))
    assert _list(SearchFilters(outcome="denied", limit=50)) == ["MN-01068", "MN-01070"]


def test_judicial_review_filters(upstream_db):
    assert _list(SearchFilters(has_judicial_review=True, limit=50)) == ["MN-01068", "MN-01070"]
    assert _list(SearchFilters(under_judicial_review=True, limit=50)) == ["MN-01070"]


def test_cli_accepts_new_outcomes_and_flag(upstream_db):
    runner = CliRunner()
    result = runner.invoke(app, ["list", "--outcome", "ceased", "--json"])
    assert result.exit_code == 0, result.output
    ids = [r["merger_id"] for r in json.loads(result.stdout)["results"]]
    assert ids == ["MN-30002"]
    result = runner.invoke(app, ["list", "--under-judicial-review", "--json"])
    assert result.exit_code == 0, result.output
    assert [r["merger_id"] for r in json.loads(result.stdout)["results"]] == ["MN-01070"]


@pytest.fixture(autouse=True)
def wide_console(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(display, "_console", Console(width=300, no_color=True))


def _render(fn, *args, **kwargs) -> str:
    c = display.console()
    with c.capture() as cap:
        fn(*args, **kwargs)
    return re.sub(r"\s+", " ", cap.get())


def test_show_lists_every_tribunal_matter_with_documents():
    out = _render(display.show_merger, Merger.from_dict(PUBLIC_BENEFIT), None, section="appeal")
    assert "ACT 3 of 2026" in out and "ACT 4 of 2026" in out
    assert "Appeal against refusal" in out
    assert "Application for review (IAG)" in out
    assert "Application to Tribunal for Review" in out


def test_show_header_public_benefit_and_pre_notification():
    out = _render(display.show_merger, Merger.from_dict(PUBLIC_BENEFIT), None, section="description")
    assert "Public benefit application under assessment" in out
    assert "Phase 2 determination: Not approved" in out
    assert "Estimated pre-notification began around 08 Feb 2026 (medium confidence)" in out


def test_show_judicial_review_state():
    out = _render(display.show_merger, Merger.from_dict(JUDICIAL_REVIEW), None, section="appeal")
    assert "Review discontinued" in out
    assert "Under judicial review" not in out
    live = _render(display.show_merger, Merger.from_dict(LIVE_REVIEW), None, section="appeal")
    assert "Under judicial review" in live
    assert "Next hearing: 10 Jan 2099 10:15 — Hearing" in live


def test_show_ceased_date():
    out = _render(display.show_merger, Merger.from_dict(CEASED), None, section="description")
    assert "Outcome: Assessment ceased" in out
    assert "Assessment ceased: 15 Jun 2026" in out


def test_timeline_collapses_foi_and_uses_determination_title():
    events = display.timeline_events(Merger.from_dict(FOI_WAIVER))
    labels = [e["label"] for e in events]
    assert "FOI release (2 documents)" in labels
    assert "Waiver application determination: Approved" in labels
    # The determination event already covers its publication date.
    assert "Determination published" not in labels
    assert not any("Waiver update" in label for label in labels)


def test_timeline_ceased_and_extension_labels():
    record = dict(
        CEASED,
        events=[
            {
                "date": "2026-04-02T12:00:00Z",
                "title": "Timeline extended by 28 business days – following request by parties",
            }
        ],
    )
    events = display.timeline_events(Merger.from_dict(record))
    by_label = {e["label"]: e for e in events}
    assert by_label["Timeline extended (+28 business days)"]["description"] == "request by parties"
    assert "Assessment ceased" in by_label


def test_upcoming_dates():
    labels = [u["label"] for u in display.upcoming_dates(Merger.from_dict(PUBLIC_BENEFIT))]
    assert labels == [
        "Determination due (statutory deadline)",
        "Tribunal hearing (ACT 3 of 2026)",
        "Public benefit responses / remedy offer due",
    ]
    # Concluded/decided matters have nothing pending.
    assert display.upcoming_dates(Merger.from_dict(CONDITIONAL)) == []


def test_not_approved_is_not_styled_as_approved():
    assert display.outcome_style("Not approved") == "red"
    assert display.outcome_style("Approved with conditions") == "green"
    assert display.outcome_style("Assessment ceased") == "magenta"
