"""Small fixture payloads mimicking the ACCC bundled CLI data format."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

MERGERS: list[dict[str, Any]] = [
    {
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
                        "details": "Asahi lease of the Deer Park warehouse site.",
                    },
                    {
                        "item": "Determination",
                        "details": "The ACCC does not propose to oppose the acquisition.",
                    },
                    {
                        "item": "Overlap and relationship between the parties",
                        "details": (
                            "The parties overlap in the supply of beverage "
                            "warehousing services in south-eastern Australia."
                        ),
                    },
                    {
                        "item": "Reasons for determination",
                        "details": (
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
            {
                "commentary": "A routine clearance of a vertical logistics transaction.",
                "tags": ["routine"],
            }
        ],
        "has_questionnaire": True,
    },
    {
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
                        "details": (
                            "The ACCC identified competition concerns in the "
                            "supply of several oncology pharmaceutical products."
                        ),
                    }
                ],
            }
        ],
        "comments": [
            {"commentary": "Landmark pharmaceutical transaction.", "tags": ["landmark"]}
        ],
        "has_questionnaire": False,
    },
    {
        "merger_id": "MN-01018",
        "merger_name": "TelstraX – Regional broadband assets",
        "status": "Completed",
        "stage": "Phase 1",
        "is_waiver": False,
        "acquirers": [{"name": "TelstraX Pty Ltd"}],
        "targets": [{"name": "Regional Broadband Co Pty Ltd"}],
        "anzsic_codes": [
            {"code": "5801", "name": "Wired Telecommunications Network Operation"}
        ],
        "merger_description": (
            "TelstraX proposed to acquire regional broadband infrastructure "
            "assets from Regional Broadband Co."
        ),
        "accc_determination": "Not approved",
        "phase_1_determination": "Not approved",
        "phase_2_determination": None,
        "effective_notification_datetime": "2025-03-10T00:00:00+10:00",
        "determination_publication_date": "2025-04-05T00:00:00+10:00",
        "events": [],
        "comments": [],
        "has_questionnaire": False,
    },
    {
        "merger_id": "MN-01019",
        "merger_name": "Ampol – Fuel retail sites",
        "status": "Completed",
        "stage": "Phase 1",
        "is_waiver": True,
        "related_merger": {
            "merger_id": "MN-01016",
            "relationship": "refiled_as",
            "merger_name": "Asahi – Warehouse site (Deer Park, Vic)",
        },
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
                        "details": (
                            "The ACCC granted the waiver having regard to the "
                            "geographic distance between the acquired sites "
                            "and other Ampol retail outlets."
                        ),
                    }
                ],
            }
        ],
        "comments": [],
        "has_questionnaire": False,
    },
]

QUESTIONNAIRES: dict[str, dict[str, Any]] = {
    "MN-01016": {
        "deadline": "25 August 2025",
        "deadline_iso": "2025-08-25",
        "file_name": "Questionnaire - Asahi - Warehouse site.pdf",
        "questions_count": 3,
        "questions": [
            {
                "number": 1,
                "section": "Questions for all respondents",
                "text": "Outline any concerns regarding the impact of the proposed acquisition on competition in the relevant market.",
            },
            {
                "number": 2,
                "section": "Questions for all respondents",
                "text": "Provide any additional information that would assist the ACCC's assessment of the geographic market.",
            },
            {
                "number": 3,
                "section": None,
                "text": "Provide a brief description of your business and its relationship to the parties.",
            },
        ],
    },
    "MN-01017": {
        "deadline": "1 June 2025",
        "deadline_iso": "2025-06-01",
        "file_name": "MN-01017 - PharmaCo - questionnaire - v2.pdf",
        "questions_count": 3,
        "all_questionnaires": [
            {
                "deadline": "1 June 2025",
                "deadline_iso": "2025-06-01",
                "file_name": "MN-01017 - PharmaCo - questionnaire - v2.pdf",
                "questions_count": 3,
                "questions": [
                    {
                        "number": 1,
                        "section": None,
                        "text": "Provide a brief description of your organisation and its commercial relationship with PharmaCo or GenericsRUs.",
                    },
                    {
                        "number": 2,
                        "section": "Questions for customers",
                        "text": "Outline any concerns you have regarding the impact of the Acquisition on competition.",
                    },
                    {
                        "number": 3,
                        "section": "Questions for customers",
                        "text": "Provide any additional information you consider relevant.",
                    },
                ],
            },
            {
                "deadline": "15 May 2025",
                "deadline_iso": "2025-05-15",
                "file_name": "MN-01017 - PharmaCo - questionnaire - v1.pdf",
                "questions_count": 3,
                "questions": [
                    {
                        "number": 1,
                        "section": None,
                        "text": "Provide a brief description of your organisation and its commercial relationship with PharmaCo or GenericsRUs.",
                    },
                    {
                        "number": 2,
                        "section": "Questions for customers",
                        "text": "Outline any concerns you have regarding the impact of the Acquisition on competition.",
                    },
                    {
                        "number": 3,
                        "section": "Questions for customers",
                        "text": "Provide any additional information you consider relevant.",
                    },
                ],
            },
        ],
        "questions": [
            {
                "number": 1,
                "section": None,
                "text": "Provide a brief description of your organisation and its commercial relationship with PharmaCo or GenericsRUs.",
            },
            {
                "number": 2,
                "section": "Questions for customers",
                "text": "Outline any concerns you have regarding the impact of the Acquisition on competition.",
            },
            {
                "number": 3,
                "section": "Questions for customers",
                "text": "Provide any additional information you consider relevant.",
            },
        ],
    },
}

STATS: dict[str, Any] = {
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

INDUSTRIES: list[dict[str, Any]] = [
    {"code": "1212", "name": "Beverage Manufacturing"},
    {"code": "1841", "name": "Pharmaceutical Product Manufacturing"},
    {"code": "4000", "name": "Fuel Retailing"},
]


def _canonical(payload: Any) -> bytes:
    """Serialise JSON in a stable, compact form and return its bytes."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=False).encode()


def write_bundle_tree(
    root: Path,
    *,
    mergers: list[dict[str, Any]] | None = None,
    questionnaires: dict[str, dict[str, Any]] | None = None,
    stats: Any = STATS,
    industries: Any = INDUSTRIES,
    version: int = 1,
    generated_at: str = "2026-04-18T04:48:02Z",
    corrupt_bundle: bool = False,
    fake_merger_count: int | None = None,
) -> Path:
    """Write the three CLI bundle files to ``root`` and return ``root``.

    Mirrors the layout of ``nwbort/accc-mergers/data/output/cli/``.
    """
    root.mkdir(parents=True, exist_ok=True)

    bundle = {
        "mergers": mergers if mergers is not None else MERGERS,
        "questionnaires": (
            questionnaires if questionnaires is not None else QUESTIONNAIRES
        ),
        "stats": stats,
        "industries": industries,
    }
    bundle_bytes = _canonical(bundle)
    bundle_sha = hashlib.sha256(bundle_bytes).hexdigest()
    if corrupt_bundle:
        bundle_bytes = bundle_bytes + b" "

    per_merger = {m["merger_id"]: hashlib.sha256(_canonical(m)).hexdigest() for m in bundle["mergers"]}
    per_merger_bytes = _canonical(per_merger)
    per_merger_sha = hashlib.sha256(per_merger_bytes).hexdigest()

    manifest = {
        "version": version,
        "generated_at": generated_at,
        "merger_count": (
            fake_merger_count
            if fake_merger_count is not None
            else len(bundle["mergers"])
        ),
        "bundle_sha256": bundle_sha,
        "merger_manifest_sha256": per_merger_sha,
    }

    (root / "cli-manifest.json").write_bytes(_canonical(manifest))
    (root / "cli-bundle.json").write_bytes(bundle_bytes)
    (root / "cli-merger-manifest.json").write_bytes(per_merger_bytes)
    return root
