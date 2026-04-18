"""Shared pytest fixtures — redirect cache paths to temp dirs for every test."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergers import db, sync
from tests.fixtures import write_fixture_tree


@pytest.fixture
def temp_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    db_path = cache_dir / "db.sqlite"
    last_sync = cache_dir / "last_sync.txt"
    monkeypatch.setattr(db, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "LAST_SYNC_PATH", last_sync)
    monkeypatch.setattr(sync.db, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(sync.db, "DB_PATH", db_path)
    monkeypatch.setattr(sync.db, "LAST_SYNC_PATH", last_sync)
    yield cache_dir


@pytest.fixture
def fixture_tree(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    write_fixture_tree(root)
    return root


@pytest.fixture
def populated_db(temp_cache, fixture_tree):
    summary = sync.persist_from_local_dir(fixture_tree)
    assert summary["mergers"] == 3
    sync.write_last_sync()
    return temp_cache
