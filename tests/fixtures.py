"""Small fixture payloads mimicking the ACCC data format."""

from __future__ import annotations

import json
from pathlib import Path


def write_fixture_tree(root: Path) -> None:
    (root / "mergers").mkdir(parents=True, exist_ok=True)

    index = [
        {"merger_id": "MN-01016"},
        {"merger_id": "MN-01017"},
        {"merger_id": "MN-01019"},
    ]
    (root / "mergers.json").write_text(json.dumps(index))

    mn_01016 = {
        "merger_id": "MN-01016",
        "merger_name": "Asahi – Warehouse site (Deer Park, Vic)",
        "status": "Completed",
        "stage": "Phase 1",
        "is_waiver": False,
        "acquirers": [{"name": "Asahi Holdings (Australia) Pty Ltd", "abn": "12345678901"}],
        "targets": [{"name": "Warehouse Site Pty Ltd", "abn": "98765432100"}],
        "anzsic_codes": [
            {"code": "1212", "name": "Beverage Manufacturing"},
            {"code": "5301", "name": "Warehouse Leasing"},
        ],
        "merger_description": (
            "Asahi proposes to acquire a long-term lease over a warehouse "
            "site in Deer Park, Victoria, currently operated by an independent "
            "beverage distributor. The transaction consolidates logistics "
            "capacity in the south-eastern Australian beverage market."
        ),
        "accc_determination": "Approved",
        "phase_1_determination": "Approved",
        "phase_2_determination": None,
        "effective_notification_datetime": "2025-08-15T00:00:00+10:00",
        "determination_publication_date": "2025-09-12T00:00:00+10:00",
        "events": [
            {
                "event_type": "determination",
                "determination_table_content": [
                    {
                        "item": "Notified acquisition",
                        "content": "Asahi lease of the Deer Park warehouse site.",
                    },
                    {
                        "item": "Determination",
                        "content": "The ACCC does not propose to oppose the acquisition.",
                    },
                    {
                        "item": "Overlap and relationship between the parties",
                        "content": (
                            "The parties overlap in the supply of beverage "
                            "warehousing services in south-eastern Australia."
                        ),
                    },
                    {
                        "item": "Reasons for determination",
                        "content": (
                            "The ACCC considered the geographic scope of the "
                            "warehouse market and concluded there would be "
                            "sufficient alternative logistics providers "
                            "following the transaction."
                        ),
                    },
                ],
            }
        ],
        "comments": [
            {"text": "A routine clearance of a vertical logistics transaction.", "tags": ["routine"]}
        ],
    }
    (root / "mergers" / "MN-01016.json").write_text(json.dumps(mn_01016))

    mn_01017 = {
        "merger_id": "MN-01017",
        "merger_name": "PharmaCo – Generic medicine portfolio",
        "status": "Under review",
        "stage": "Phase 2",
        "is_waiver": False,
        "acquirers": [{"name": "PharmaCo Ltd"}],
        "targets": [{"name": "GenericsRUs Pty Ltd"}],
        "anzsic_codes": [
            {"code": "1841", "name": "Pharmaceutical Product Manufacturing"}
        ],
        "merger_description": (
            "PharmaCo proposes to acquire a portfolio of generic "
            "pharmaceutical products from GenericsRUs, including several "
            "off-patent oncology treatments."
        ),
        "accc_determination": None,
        "phase_1_determination": "Phase 2 referral",
        "phase_2_determination": None,
        "effective_notification_datetime": "2025-05-01T00:00:00+10:00",
        "determination_publication_date": None,
        "events": [
            {
                "event_type": "phase_1",
                "determination_table_content": [
                    {
                        "item": "Reasons for determination",
                        "content": (
                            "The ACCC identified competition concerns in the "
                            "supply of several oncology pharmaceutical products."
                        ),
                    }
                ],
            }
        ],
        "comments": [
            {"text": "Landmark pharmaceutical transaction.", "tags": ["landmark"]}
        ],
    }
    (root / "mergers" / "MN-01017.json").write_text(json.dumps(mn_01017))

    mn_01019 = {
        "merger_id": "MN-01019",
        "merger_name": "Ampol – Fuel retail sites",
        "status": "Completed",
        "stage": "Phase 1",
        "is_waiver": True,
        "acquirers": [{"name": "Ampol Limited"}],
        "targets": [{"name": "Regional Fuel Holdings"}],
        "anzsic_codes": [
            {"code": "4000", "name": "Fuel Retailing"}
        ],
        "merger_description": (
            "Ampol seeks a waiver in respect of its acquisition of four fuel "
            "retail sites in regional New South Wales."
        ),
        "accc_determination": "Approved",
        "phase_1_determination": "Approved",
        "phase_2_determination": None,
        "effective_notification_datetime": "2024-11-11T00:00:00+10:00",
        "determination_publication_date": "2024-11-28T00:00:00+10:00",
        "events": [
            {
                "event_type": "waiver",
                "determination_table_content": [
                    {
                        "item": "Reasons for determination",
                        "content": (
                            "The ACCC granted the waiver having regard to the "
                            "geographic distance between the acquired sites "
                            "and other Ampol retail outlets."
                        ),
                    }
                ],
            }
        ],
        "comments": [],
    }
    (root / "mergers" / "MN-01019.json").write_text(json.dumps(mn_01019))

    questionnaires = {
        "MN-01016": {
            "deadline": "25 August 2025",
            "questions_count": 3,
            "questions": [
                {
                    "number": "1",
                    "text": "Outline any concerns regarding the impact of the proposed acquisition on competition in the relevant market.",
                },
                {
                    "number": "2",
                    "text": "Provide any additional information that would assist the ACCC's assessment of the geographic market.",
                },
                {
                    "number": "3",
                    "text": "Provide a brief description of your business and its relationship to the parties.",
                },
            ],
        }
    }
    (root / "questionnaire_data.json").write_text(json.dumps(questionnaires))

    stats = {
        "totals": {
            "total_mergers": 3,
            "approved": 2,
            "phase_2": 1,
        },
        "phase_durations": {
            "phase_1": {"average": 30, "median": 28},
        },
        "top_industries": [
            {"name": "Beverage Manufacturing", "count": 1},
            {"name": "Fuel Retailing", "count": 1},
        ],
        "recent_determinations": [
            {
                "merger_id": "MN-01016",
                "merger_name": "Asahi – Warehouse site",
                "determination": "Approved",
                "date": "2025-09-12",
            }
        ],
    }
    (root / "stats.json").write_text(json.dumps(stats))

    industries = [
        {"code": "1212", "name": "Beverage Manufacturing"},
        {"code": "1841", "name": "Pharmaceutical Product Manufacturing"},
        {"code": "4000", "name": "Fuel Retailing"},
    ]
    (root / "industries.json").write_text(json.dumps(industries))
