"""Dataclasses for the ACCC merger register."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Party:
    name: str
    abn: str | None = None
    acn: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Party":
        return cls(
            name=data.get("name", "") or "",
            abn=data.get("abn"),
            acn=data.get("acn"),
        )


@dataclass
class AnzsicCode:
    code: str
    name: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnzsicCode":
        return cls(
            code=str(data.get("code", "") or ""),
            name=data.get("name", "") or "",
        )


@dataclass
class DeterminationSection:
    item: str
    content: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeterminationSection":
        return cls(
            item=data.get("item", "") or "",
            content=data.get("details") or data.get("content", "") or "",
        )


@dataclass
class Event:
    event_type: str | None = None
    event_date: str | None = None
    description: str | None = None
    determination_table_content: list[DeterminationSection] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        sections = [
            DeterminationSection.from_dict(s)
            for s in (data.get("determination_table_content") or [])
        ]
        return cls(
            event_type=data.get("event_type") or data.get("type"),
            event_date=data.get("event_date") or data.get("date"),
            description=data.get("description"),
            determination_table_content=sections,
            raw=data,
        )


@dataclass
class Comment:
    text: str
    tags: list[str] = field(default_factory=list)
    author: str | None = None
    date: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Comment":
        return cls(
            text=data.get("commentary") or data.get("text") or data.get("comment") or "",
            tags=list(data.get("tags") or []),
            author=data.get("author"),
            date=data.get("date"),
        )


@dataclass
class Merger:
    merger_id: str
    merger_name: str
    status: str | None = None
    stage: str | None = None
    is_waiver: bool = False
    acquirers: list[Party] = field(default_factory=list)
    targets: list[Party] = field(default_factory=list)
    anzsic_codes: list[AnzsicCode] = field(default_factory=list)
    merger_description: str = ""
    accc_determination: str | None = None
    phase_1_determination: str | None = None
    phase_2_determination: str | None = None
    effective_notification_datetime: str | None = None
    determination_publication_date: str | None = None
    events: list[Event] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Merger":
        return cls(
            merger_id=data.get("merger_id", "") or "",
            merger_name=data.get("merger_name", "") or "",
            status=data.get("status"),
            stage=data.get("stage"),
            is_waiver=bool(data.get("is_waiver")),
            acquirers=[Party.from_dict(p) for p in (data.get("acquirers") or [])],
            targets=[Party.from_dict(p) for p in (data.get("targets") or [])],
            anzsic_codes=[AnzsicCode.from_dict(a) for a in (data.get("anzsic_codes") or [])],
            merger_description=data.get("merger_description", "") or "",
            accc_determination=data.get("accc_determination"),
            phase_1_determination=data.get("phase_1_determination"),
            phase_2_determination=data.get("phase_2_determination"),
            effective_notification_datetime=data.get("effective_notification_datetime"),
            determination_publication_date=data.get("determination_publication_date"),
            events=[Event.from_dict(e) for e in (data.get("events") or [])],
            comments=[Comment.from_dict(c) for c in (data.get("comments") or [])],
            raw=data,
        )

    def determination_sections(self) -> list[DeterminationSection]:
        sections: list[DeterminationSection] = []
        for event in self.events:
            sections.extend(event.determination_table_content)
        return sections

    def section_text(self, item_name: str) -> str:
        texts = [
            s.content
            for s in self.determination_sections()
            if s.item.strip().lower() == item_name.strip().lower()
        ]
        return "\n\n".join(t for t in texts if t)

    def all_determination_text(self) -> str:
        return "\n\n".join(
            f"{s.item}\n{s.content}"
            for s in self.determination_sections()
            if s.content
        )

    def notification_year(self) -> int | None:
        dt = self.effective_notification_datetime
        if not dt or len(dt) < 4:
            return None
        try:
            return int(dt[:4])
        except ValueError:
            return None

    def outcome(self) -> str | None:
        """Return the effective outcome for display.

        When a merger is actively in Phase 2 (stage says "Phase 2"), the
        Phase 1 determination of "Referred to Phase 2" is no longer meaningful
        as an outcome — the merger is pending a Phase 2 result.
        """
        if self.accc_determination:
            return self.accc_determination
        if self.phase_2_determination:
            return self.phase_2_determination
        if "phase 2" in (self.stage or "").lower():
            return None
        return self.phase_1_determination or None

    def phase_number(self) -> int | None:
        stage = (self.stage or "").lower()
        if "phase 2" in stage:
            return 2
        if self.phase_2_determination:
            return 2
        if (self.phase_1_determination or "").lower().find("phase 2") >= 0:
            return 2
        if "phase 1" in stage:
            return 1
        if self.phase_1_determination:
            return 1
        return None

    def acquirers_text(self) -> str:
        return "; ".join(p.name for p in self.acquirers if p.name)

    def targets_text(self) -> str:
        return "; ".join(p.name for p in self.targets if p.name)

    def industries_text(self) -> str:
        return "; ".join(a.name for a in self.anzsic_codes if a.name)


@dataclass
class Questionnaire:
    merger_id: str
    merger_name: str | None
    deadline: str | None
    questions: list[dict[str, Any]]
    questions_count: int

    @classmethod
    def from_dict(cls, merger_id: str, data: dict[str, Any]) -> "Questionnaire":
        questions = list(data.get("questions") or [])
        return cls(
            merger_id=merger_id,
            merger_name=data.get("merger_name"),
            deadline=data.get("deadline"),
            questions=questions,
            questions_count=int(data.get("questions_count") or len(questions)),
        )
