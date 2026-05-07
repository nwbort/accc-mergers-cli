"""Fetch ACCC merger data from GitHub and index it locally.

The upstream repo (nwbort/accc-mergers) pre-generates three files under
``data/output/cli/`` on every data update: ``cli-manifest.json``,
``cli-bundle.json`` and ``cli-merger-manifest.json``. The CLI consumes those
files directly instead of scraping ~200 per-merger JSONs.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

import httpx

from . import __version__, db
from .models import Merger, Nocc, Questionnaire

BASE_URL_ENV = "ACCC_MERGERS_BASE_URL"
DEFAULT_BASE_URL = (
    "https://raw.githubusercontent.com/nwbort/accc-mergers/main/"
    "data/output/cli"
)

MANIFEST_FILENAME = "cli-manifest.json"
BUNDLE_FILENAME = "cli-bundle.json"
MERGER_MANIFEST_FILENAME = "cli-merger-manifest.json"

REQUEST_TIMEOUT = 30.0
RETRY_DELAYS = (1.0, 2.0, 4.0)
USER_AGENT = f"accc-mergers-cli/{__version__}"

def manifest_cache_path() -> Path:
    return db.CACHE_DIR / MANIFEST_FILENAME


def merger_manifest_cache_path() -> Path:
    return db.CACHE_DIR / MERGER_MANIFEST_FILENAME


class SyncError(RuntimeError):
    """Raised when a sync cannot be completed."""


@dataclass
class SyncResult:
    manifest: dict[str, Any]
    changed: bool
    mergers: int
    questionnaires: int


def base_url() -> str:
    return os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL


def _join_url(base: str, name: str) -> str:
    if base.startswith(("http://", "https://", "file://")):
        return f"{base.rstrip('/')}/{name}"
    return str(Path(base) / name)


def _is_http(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _local_path(url: str) -> Path | None:
    if url.startswith("file://"):
        parsed = urlparse(url)
        return Path(unquote(parsed.path))
    if not _is_http(url):
        return Path(url)
    return None


def _fetch_bytes(client: httpx.Client | None, url: str) -> bytes:
    local = _local_path(url)
    if local is not None:
        if not local.exists():
            raise SyncError(f"File not found: {local}")
        return local.read_bytes()

    assert client is not None, "HTTP client required for remote URLs"
    last_exc: Exception | None = None
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            response = client.get(url, timeout=REQUEST_TIMEOUT)
            if response.status_code == 404:
                raise SyncError(f"Not found: {url}")
            response.raise_for_status()
            return response.content
        except SyncError:
            raise
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(RETRY_DELAYS[attempt])
    raise SyncError(f"Failed to fetch {url}: {last_exc}") from last_exc


def _make_client(base: str) -> httpx.Client | None:
    if not _is_http(base):
        return None
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def _read_cached_manifest() -> dict[str, Any] | None:
    if not manifest_cache_path().exists():
        return None
    try:
        return json.loads(manifest_cache_path().read_text())
    except (ValueError, OSError):
        return None


def _write_cached_manifest(raw: bytes) -> None:
    db.ensure_cache_dir()
    manifest_cache_path().write_bytes(raw)


def _write_cached_merger_manifest(raw: bytes) -> None:
    db.ensure_cache_dir()
    merger_manifest_cache_path().write_bytes(raw)


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


def read_cached_manifest() -> dict[str, Any] | None:
    """Public accessor used by the `status` command."""
    return _read_cached_manifest()


def _require_manifest_fields(manifest: dict[str, Any]) -> None:
    missing = [
        k
        for k in ("version", "generated_at", "merger_count", "bundle_sha256")
        if k not in manifest
    ]
    if missing:
        raise SyncError(
            f"Manifest missing required fields: {', '.join(missing)}"
        )


def sync(force: bool = False, source: str | None = None) -> SyncResult:
    """Run the full manifest/bundle sync flow.

    Fetches ``cli-manifest.json`` first; if the bundle hash matches the
    locally cached manifest and ``force`` is False, the local index is
    already up to date. Otherwise fetches and verifies ``cli-bundle.json``,
    rebuilds the SQLite index, and updates the cached manifest.

    ``source`` overrides the base URL for this call only (takes precedence
    over the ``ACCC_MERGERS_BASE_URL`` environment variable).  Accepts the
    same forms as the env var: an ``http://``/``https://`` URL, a
    ``file://`` URI, or a plain local directory path.
    """
    base = source or base_url()
    manifest_url = _join_url(base, MANIFEST_FILENAME)
    bundle_url = _join_url(base, BUNDLE_FILENAME)
    merger_manifest_url = _join_url(base, MERGER_MANIFEST_FILENAME)

    client = _make_client(base)
    try:
        manifest_bytes = _fetch_bytes(client, manifest_url)
        try:
            manifest = json.loads(manifest_bytes)
        except ValueError as exc:
            raise SyncError(f"Manifest is not valid JSON: {exc}") from exc
        _require_manifest_fields(manifest)

        cached = _read_cached_manifest()
        cached_sha = cached.get("bundle_sha256") if cached else None
        if (
            not force
            and cached_sha == manifest["bundle_sha256"]
            and db.DB_PATH.exists()
        ):
            _write_cached_manifest(manifest_bytes)
            write_last_sync()
            conn = db.connect()
            try:
                merger_count = db.count_mergers(conn)
            finally:
                conn.close()
            return SyncResult(
                manifest=manifest,
                changed=False,
                mergers=merger_count,
                questionnaires=0,
            )

        bundle_bytes = _fetch_bytes(client, bundle_url)
        actual_sha = hashlib.sha256(bundle_bytes).hexdigest()
        if actual_sha != manifest["bundle_sha256"]:
            raise SyncError(
                "Bundle hash mismatch: manifest expected "
                f"{manifest['bundle_sha256']}, got {actual_sha}"
            )

        try:
            bundle = json.loads(bundle_bytes)
        except ValueError as exc:
            raise SyncError(f"Bundle is not valid JSON: {exc}") from exc

        mergers_list = bundle.get("mergers") or []
        if len(mergers_list) != manifest["merger_count"]:
            raise SyncError(
                "Bundle merger count mismatch: manifest expected "
                f"{manifest['merger_count']}, bundle has {len(mergers_list)}"
            )

        summary = _persist(bundle)

        try:
            mm_bytes = _fetch_bytes(client, merger_manifest_url)
        except SyncError:
            mm_bytes = None
        if mm_bytes is not None:
            expected = manifest.get("merger_manifest_sha256")
            if expected is None or hashlib.sha256(mm_bytes).hexdigest() == expected:
                _write_cached_merger_manifest(mm_bytes)

        _write_cached_manifest(manifest_bytes)
        write_last_sync()
        return SyncResult(
            manifest=manifest,
            changed=True,
            mergers=summary["mergers"],
            questionnaires=summary["questionnaires"],
        )
    finally:
        if client is not None:
            client.close()


def _persist(bundle: dict[str, Any]) -> dict[str, int]:
    db.ensure_cache_dir()
    conn = db.connect()
    try:
        db.init_schema(conn)
        db.clear_mergers(conn)

        merger_count = 0
        for merger_dict in bundle.get("mergers") or []:
            merger = Merger.from_dict(merger_dict)
            if not merger.merger_id:
                continue
            db.insert_merger(conn, merger)
            merger_count += 1

        questionnaires = bundle.get("questionnaires") or {}
        q_count = 0
        if isinstance(questionnaires, dict):
            for mid, q_data in questionnaires.items():
                if not isinstance(q_data, dict):
                    continue
                q = Questionnaire.from_dict(mid, q_data)
                db.insert_questionnaire(conn, q)
                q_count += 1

        noccs = bundle.get("noccs") or {}
        if isinstance(noccs, dict):
            for mid, n_data in noccs.items():
                if not isinstance(n_data, dict):
                    continue
                db.insert_nocc(conn, Nocc.from_dict(mid, n_data))

        stats = bundle.get("stats")
        if stats is not None:
            db.set_stats(conn, stats)
        industries = bundle.get("industries")
        if industries is not None:
            db.set_industries(conn, industries)

        conn.commit()
    finally:
        conn.close()

    return {"mergers": merger_count, "questionnaires": q_count}


def ensure_cache() -> SyncResult | None:
    """If no cache exists, run an initial sync and return the result."""
    if cache_exists():
        return None
    return sync()
