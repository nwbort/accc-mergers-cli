"""Fetch ACCC merger data from GitHub and index it locally."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
from pathlib import Path
from typing import Any

import httpx

from . import db
from .models import Merger, Questionnaire

BASE_URL = (
    "https://raw.githubusercontent.com/nwbort/accc-mergers/main/"
    "merger-tracker/frontend/public/data"
)
INDEX_URL = f"{BASE_URL}/mergers.json"
LIST_META_URL = f"{BASE_URL}/mergers/list-meta.json"
LIST_PAGE_URL = f"{BASE_URL}/mergers/list-page-{{page}}.json"
STATS_URL = f"{BASE_URL}/stats.json"
QUESTIONNAIRE_URL = f"{BASE_URL}/questionnaire_data.json"
INDUSTRIES_URL = f"{BASE_URL}/industries.json"
MERGER_URL = f"{BASE_URL}/mergers/{{merger_id}}.json"

MAX_CONCURRENCY = 4
REQUEST_TIMEOUT = 30.0


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


async def _fetch_merger(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, merger_id: str
) -> dict[str, Any] | None:
    async with semaphore:
        try:
            return await _fetch_json(client, MERGER_URL.format(merger_id=merger_id))
        except httpx.HTTPError:
            return None


async def _fetch_all_merger_ids(client: httpx.AsyncClient) -> list[str]:
    """Return every merger ID published by the tracker.

    Uses the paginated ``mergers/list-page-N.json`` index when available, since
    ``mergers.json`` only contains the subset of notifications surfaced on the
    landing page and omits waiver (``WA-*``) records entirely.
    """
    ids: list[str] = []
    seen: set[str] = set()

    meta = await _safe_fetch(client, LIST_META_URL)
    if isinstance(meta, dict):
        total_pages = int(meta.get("total_pages") or 0)
        for page in range(1, total_pages + 1):
            page_data = await _safe_fetch(client, LIST_PAGE_URL.format(page=page))
            for mid in _extract_merger_ids(page_data):
                if mid not in seen:
                    seen.add(mid)
                    ids.append(mid)

    if not ids:
        index_data = await _fetch_json(client, INDEX_URL)
        for mid in _extract_merger_ids(index_data):
            if mid not in seen:
                seen.add(mid)
                ids.append(mid)

    return ids


async def _download_all(progress_cb=None) -> dict[str, Any]:
    """Download the index, individual mergers, stats, questionnaires, and industries."""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        merger_ids = await _fetch_all_merger_ids(client)

        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        total = len(merger_ids)
        completed = 0
        mergers: list[dict[str, Any]] = []

        async def fetch_one(mid: str) -> None:
            nonlocal completed
            data = await _fetch_merger(client, semaphore, mid)
            completed += 1
            if progress_cb:
                progress_cb(completed, total)
            if data:
                mergers.append(data)

        await asyncio.gather(*(fetch_one(mid) for mid in merger_ids))

        stats = await _safe_fetch(client, STATS_URL)
        questionnaires = await _safe_fetch(client, QUESTIONNAIRE_URL)
        industries = await _safe_fetch(client, INDUSTRIES_URL)

        return {
            "mergers": mergers,
            "stats": stats,
            "questionnaires": questionnaires,
            "industries": industries,
        }


async def _safe_fetch(client: httpx.AsyncClient, url: str) -> Any:
    try:
        return await _fetch_json(client, url)
    except httpx.HTTPError:
        return None


def _extract_merger_ids(index_data: Any) -> list[str]:
    if isinstance(index_data, list):
        items = index_data
    elif isinstance(index_data, dict):
        items = (
            index_data.get("mergers")
            or index_data.get("items")
            or index_data.get("data")
            or []
        )
    else:
        items = []
    ids: list[str] = []
    for item in items:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            merger_id = item.get("merger_id") or item.get("id")
            if merger_id:
                ids.append(str(merger_id))
    return ids


def is_cache_fresh() -> bool:
    if not db.LAST_SYNC_PATH.exists():
        return False
    try:
        ts = dt.datetime.fromisoformat(db.LAST_SYNC_PATH.read_text().strip())
    except ValueError:
        return False
    age = dt.datetime.now(dt.timezone.utc) - ts
    return age < dt.timedelta(days=db.STALE_DAYS)


def cache_exists() -> bool:
    return db.DB_PATH.exists() and db.LAST_SYNC_PATH.exists()


def cache_age_days() -> float | None:
    if not db.LAST_SYNC_PATH.exists():
        return None
    try:
        ts = dt.datetime.fromisoformat(db.LAST_SYNC_PATH.read_text().strip())
    except ValueError:
        return None
    return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() / 86400.0


def write_last_sync(ts: dt.datetime | None = None) -> None:
    ts = ts or dt.datetime.now(dt.timezone.utc)
    db.ensure_cache_dir()
    db.LAST_SYNC_PATH.write_text(ts.isoformat())


def sync(progress_cb=None) -> dict[str, int]:
    """Download everything and rebuild the local cache. Returns summary counts."""
    data = asyncio.run(_download_all(progress_cb=progress_cb))
    return _persist(data)


def _persist(data: dict[str, Any]) -> dict[str, int]:
    db.ensure_cache_dir()
    conn = db.connect()
    try:
        db.init_schema(conn)
        db.clear_mergers(conn)

        merger_count = 0
        for merger_dict in data.get("mergers") or []:
            merger = Merger.from_dict(merger_dict)
            if not merger.merger_id:
                continue
            db.insert_merger(conn, merger)
            merger_count += 1

        questionnaires = data.get("questionnaires") or {}
        q_count = 0
        if isinstance(questionnaires, dict):
            for mid, q_data in questionnaires.items():
                if not isinstance(q_data, dict):
                    continue
                q = Questionnaire.from_dict(mid, q_data)
                db.insert_questionnaire(conn, q)
                q_count += 1

        if data.get("stats") is not None:
            db.set_stats(conn, data["stats"])
        if data.get("industries") is not None:
            db.set_industries(conn, data["industries"])

        conn.commit()
    finally:
        conn.close()

    write_last_sync()
    return {"mergers": merger_count, "questionnaires": q_count}


def ensure_cache(progress_cb=None) -> dict[str, int] | None:
    """If no cache exists, run an initial sync and return the summary."""
    if cache_exists():
        return None
    return sync(progress_cb=progress_cb)


def load_json_file(path: Path) -> Any:
    return json.loads(path.read_text())


def persist_from_local_dir(root: Path) -> dict[str, int]:
    """Testing helper: load data from a local directory mirroring the GitHub layout."""
    index = load_json_file(root / "mergers.json")
    merger_ids = _extract_merger_ids(index)
    mergers: list[dict[str, Any]] = []
    for mid in merger_ids:
        path = root / "mergers" / f"{mid}.json"
        if path.exists():
            mergers.append(load_json_file(path))

    stats_path = root / "stats.json"
    questionnaires_path = root / "questionnaire_data.json"
    industries_path = root / "industries.json"

    data = {
        "mergers": mergers,
        "stats": load_json_file(stats_path) if stats_path.exists() else None,
        "questionnaires": (
            load_json_file(questionnaires_path)
            if questionnaires_path.exists()
            else None
        ),
        "industries": (
            load_json_file(industries_path) if industries_path.exists() else None
        ),
    }
    return _persist(data)
