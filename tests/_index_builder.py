"""Test helper that builds a SQLite database matching the upstream schema.

The production CLI never indexes data locally — it downloads a pre-built
SQLite file from the upstream ``nwbort/accc-mergers`` repo. Tests need to
construct a fixture database that looks like one upstream would publish,
so this module re-implements just enough indexing logic for that purpose.

If the upstream schema changes, ``mergers.db.SCHEMA_VERSION`` and the
``SCHEMA`` constant here must be updated together.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from mergers import db
from mergers.models import Merger, Nocc, Questionnaire


SCHEMA = """
CREATE TABLE mergers (
    merger_id TEXT PRIMARY KEY,
    merger_name TEXT,
    status TEXT,
    stage TEXT,
    is_waiver INTEGER,
    acquirers_text TEXT,
    targets_text TEXT,
    industries_text TEXT,
    determination TEXT,
    phase INTEGER,
    notification_date TEXT,
    determination_date TEXT,
    related_merger_id TEXT,
    related_relationship TEXT,
    related_merger_name TEXT,
    under_appeal INTEGER,
    has_judicial_review INTEGER,
    phase_1_estimate_days INTEGER,
    raw_json TEXT
);

CREATE INDEX mergers_related_merger_id_idx ON mergers(related_merger_id);

CREATE VIRTUAL TABLE merger_content USING fts5(
    merger_id UNINDEXED,
    merger_name,
    acquirers_text,
    targets_text,
    industries_text,
    merger_description,
    determination_reasons,
    determination_overlap,
    all_determination_text,
    tokenize = 'porter unicode61'
);

CREATE TABLE questionnaires (
    merger_id TEXT PRIMARY KEY,
    deadline TEXT,
    deadline_iso TEXT,
    file_name TEXT,
    questions_count INTEGER,
    raw_json TEXT,
    all_questionnaires_json TEXT
);

CREATE VIRTUAL TABLE questionnaire_content USING fts5(
    merger_id UNINDEXED,
    question_number UNINDEXED,
    question_text,
    tokenize = 'porter unicode61'
);

CREATE TABLE noccs (
    merger_id TEXT PRIMARY KEY,
    matter_id TEXT,
    date TEXT,
    date_iso TEXT,
    document_type TEXT,
    file_name TEXT,
    file_path TEXT,
    raw_json TEXT
);

CREATE VIRTUAL TABLE nocc_content USING fts5(
    merger_id UNINDEXED,
    section_number UNINDEXED,
    section_title,
    block_number UNINDEXED,
    block_text,
    tokenize = 'porter unicode61'
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE stats (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE industries (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def build_database(
    path: Path,
    bundle: dict[str, Any],
    *,
    schema_version: int | None = None,
) -> None:
    """Build a SQLite database at ``path`` from a bundle dict.

    The bundle has the shape that the upstream repo's ``cli-bundle.json``
    used to have before indexing moved upstream.
    """
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        version = db.SCHEMA_VERSION if schema_version is None else schema_version
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )

        for merger_dict in bundle.get("mergers") or []:
            merger = Merger.from_dict(merger_dict)
            if not merger.merger_id:
                continue
            _insert_merger(conn, merger)

        for mid, q_data in (bundle.get("questionnaires") or {}).items():
            if not isinstance(q_data, dict):
                continue
            _insert_questionnaire(conn, Questionnaire.from_dict(mid, q_data))

        for mid, n_data in (bundle.get("noccs") or {}).items():
            if not isinstance(n_data, dict):
                continue
            _insert_nocc(conn, Nocc.from_dict(mid, n_data))

        stats = bundle.get("stats")
        if stats is not None:
            conn.execute(
                "INSERT INTO stats (key, value) VALUES ('stats', ?)",
                (json.dumps(stats),),
            )

        industries = bundle.get("industries")
        if industries is not None:
            conn.execute(
                "INSERT INTO industries (key, value) VALUES ('industries', ?)",
                (json.dumps(industries),),
            )

        conn.commit()
    finally:
        conn.close()


def _insert_merger(conn: sqlite3.Connection, merger: Merger) -> None:
    related = merger.related_merger
    phase_1_estimate = merger.phase_1_estimate or {}
    conn.execute(
        """
        INSERT INTO mergers (
            merger_id, merger_name, status, stage, is_waiver,
            acquirers_text, targets_text, industries_text,
            determination, phase, notification_date, determination_date,
            related_merger_id, related_relationship, related_merger_name,
            under_appeal, has_judicial_review, phase_1_estimate_days,
            raw_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            merger.merger_id,
            merger.merger_name,
            merger.status,
            merger.stage,
            1 if merger.is_waiver else 0,
            merger.acquirers_text(),
            merger.targets_text(),
            merger.industries_text(),
            merger.outcome(),
            merger.phase_number(),
            merger.effective_notification_datetime,
            merger.determination_publication_date,
            related.merger_id if related else None,
            related.relationship if related else None,
            related.merger_name if related else None,
            1 if merger.under_appeal else 0,
            1 if merger.judicial_review else 0,
            phase_1_estimate.get("expected_business_days"),
            json.dumps(merger.raw),
        ),
    )
    conn.execute(
        """
        INSERT INTO merger_content (
            merger_id, merger_name, acquirers_text, targets_text, industries_text,
            merger_description, determination_reasons, determination_overlap,
            all_determination_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            merger.merger_id,
            merger.merger_name,
            merger.acquirers_text(),
            merger.targets_text(),
            merger.industries_text(),
            merger.merger_description,
            merger.section_text("Reasons for determination"),
            merger.section_text("Overlap and relationship between the parties"),
            merger.all_determination_text(),
        ),
    )


def _insert_questionnaire(conn: sqlite3.Connection, q: Questionnaire) -> None:
    conn.execute(
        """
        INSERT INTO questionnaires
        (merger_id, deadline, deadline_iso, file_name, questions_count,
         raw_json, all_questionnaires_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            q.merger_id,
            q.deadline,
            q.deadline_iso,
            q.file_name,
            q.questions_count,
            json.dumps(q.questions),
            json.dumps(q.all_questionnaires) if q.all_questionnaires else None,
        ),
    )
    for question in q.questions:
        number = question.get("number") or question.get("question_number") or ""
        text = (
            question.get("text")
            or question.get("question")
            or question.get("question_text")
            or ""
        )
        conn.execute(
            """
            INSERT INTO questionnaire_content
            (merger_id, question_number, question_text)
            VALUES (?, ?, ?)
            """,
            (q.merger_id, str(number), text),
        )


def _insert_nocc(conn: sqlite3.Connection, n: Nocc) -> None:
    conn.execute(
        """
        INSERT INTO noccs
        (merger_id, matter_id, date, date_iso, document_type, file_name,
         file_path, raw_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            n.merger_id,
            n.matter_id,
            n.date,
            n.date_iso,
            n.document_type,
            n.file_name,
            n.file_path,
            json.dumps(
                {
                    "sections": [
                        {
                            "number": s.number,
                            "title": s.title,
                            "blocks": [
                                {"number": b.number, "text": b.text, "type": b.type}
                                for b in s.blocks
                            ],
                        }
                        for s in n.sections
                    ]
                }
            ),
        ),
    )
    for section in n.sections:
        for block in section.blocks:
            if not (block.text or "").strip():
                continue
            conn.execute(
                """
                INSERT INTO nocc_content
                (merger_id, section_number, section_title,
                 block_number, block_text)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    n.merger_id,
                    str(section.number or ""),
                    section.title or "",
                    str(block.number or ""),
                    block.text,
                ),
            )
