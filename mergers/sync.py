"""Fetch the pre-built CLI SQLite database from upstream and install it locally.

The upstream repo (``nwbort/accc-mergers``) publishes a pre-indexed SQLite
file to its ``cli-dist`` branch on every data update. The CLI just downloads
that database and verifies its SHA-256; there is no client-side indexing.

The branch is force-pushed (no history kept), so the URLs always point at
the current build.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, unquote

import httpx

from . import __version__, db

BASE_URL_ENV = "ACCC_MERGERS_BASE_URL"
DEFAULT_BASE_URL = (
    "https://raw.githubusercontent.com/nwbort/accc-mergers/cli-dist"
)

MANIFEST_FILENAME = "cli-manifest.json"
SQLITE_FILENAME = "cli.sqlite"

REQUEST_TIMEOUT = 60.0
RETRY_DELAYS = (1.0, 2.0, 4.0)
USER_AGENT = f"accc-mergers-cli/{__version__}"

REQUIRED_MANIFEST_FIELDS = (
    "schema_version",
    "version",
    "generated_at",
    "merger_count",
    "sqlite_sha256",
)


def manifest_cache_path() -> Path:
    return db.CACHE_DIR / MANIFEST_FILENAME


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
    missing = [k for k in REQUIRED_MANIFEST_FIELDS if k not in manifest]
    if missing:
        raise SyncError(
            f"Manifest missing required fields: {', '.join(missing)}"
        )


def _require_schema_version(manifest: dict[str, Any]) -> None:
    got = manifest.get("schema_version")
    if got != db.SCHEMA_VERSION:
        raise SyncError(
            f"Schema version mismatch: this CLI supports schema_version "
            f"{db.SCHEMA_VERSION}, but upstream published {got!r}. "
            "Upgrade the CLI to a version that supports this schema."
        )


def _install_sqlite(content: bytes) -> None:
    """Atomically write *content* to ``db.DB_PATH``."""
    db.ensure_cache_dir()
    fd, tmp_name = tempfile.mkstemp(
        prefix=".db.sqlite.", suffix=".tmp", dir=str(db.CACHE_DIR)
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp_name, db.DB_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _count_questionnaires(conn) -> int:
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM questionnaires").fetchone()
    except Exception:
        return 0
    return int(row["n"]) if row else 0


def sync(force: bool = False, source: str | None = None) -> SyncResult:
    """Download the latest SQLite database and install it.

    Fetches ``cli-manifest.json`` first; if the SHA-256 matches the locally
    cached manifest and ``force`` is False, no download is needed. Otherwise
    fetches and verifies ``cli.sqlite`` and atomically replaces the local
    database.

    ``source`` overrides the base URL for this call only (takes precedence
    over the ``ACCC_MERGERS_BASE_URL`` environment variable).  Accepts the
    same forms as the env var: an ``http://``/``https://`` URL, a
    ``file://`` URI, or a plain local directory path.
    """
    base = source or base_url()
    manifest_url = _join_url(base, MANIFEST_FILENAME)
    sqlite_url = _join_url(base, SQLITE_FILENAME)

    client = _make_client(base)
    try:
        manifest_bytes = _fetch_bytes(client, manifest_url)
        try:
            manifest = json.loads(manifest_bytes)
        except ValueError as exc:
            raise SyncError(f"Manifest is not valid JSON: {exc}") from exc
        _require_manifest_fields(manifest)
        _require_schema_version(manifest)

        cached = _read_cached_manifest()
        cached_sha = cached.get("sqlite_sha256") if cached else None
        if (
            not force
            and cached_sha == manifest["sqlite_sha256"]
            and db.DB_PATH.exists()
        ):
            _write_cached_manifest(manifest_bytes)
            write_last_sync()
            conn = db.connect()
            try:
                merger_count = db.count_mergers(conn)
                q_count = _count_questionnaires(conn)
            finally:
                conn.close()
            return SyncResult(
                manifest=manifest,
                changed=False,
                mergers=merger_count,
                questionnaires=q_count,
            )

        sqlite_bytes = _fetch_bytes(client, sqlite_url)
        actual_sha = hashlib.sha256(sqlite_bytes).hexdigest()
        if actual_sha != manifest["sqlite_sha256"]:
            raise SyncError(
                "SQLite hash mismatch: manifest expected "
                f"{manifest['sqlite_sha256']}, got {actual_sha}"
            )

        _install_sqlite(sqlite_bytes)

        conn = db.connect()
        try:
            db_schema = db.read_schema_version(conn)
            merger_count = db.count_mergers(conn)
            q_count = _count_questionnaires(conn)
        finally:
            conn.close()

        if db_schema != db.SCHEMA_VERSION:
            raise SyncError(
                f"Downloaded database reports schema_version {db_schema!r}, "
                f"CLI expects {db.SCHEMA_VERSION}"
            )
        if merger_count != manifest["merger_count"]:
            raise SyncError(
                "Merger count mismatch: manifest expected "
                f"{manifest['merger_count']}, database has {merger_count}"
            )

        _write_cached_manifest(manifest_bytes)
        write_last_sync()
        return SyncResult(
            manifest=manifest,
            changed=True,
            mergers=merger_count,
            questionnaires=q_count,
        )
    finally:
        if client is not None:
            client.close()


def ensure_cache() -> SyncResult | None:
    """If no cache exists, run an initial sync and return the result."""
    if cache_exists():
        return None
    return sync()
