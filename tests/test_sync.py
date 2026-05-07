"""Tests for the manifest + bundle sync path."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergers import db, sync
from tests.fixtures import write_bundle_tree


def test_sync_indexes_everything_from_bundle(populated_db):
    conn = db.connect()
    try:
        assert db.count_mergers(conn) == 4
        merger = db.get_merger(conn, "MN-01016")
        assert merger is not None
        assert merger.merger_name.startswith("Asahi")
        q = db.get_questionnaire(conn, "MN-01016")
        assert q is not None
        assert q.questions_count == 3
        assert q.deadline_iso == "2025-08-25"
        assert q.file_name == "Questionnaire - Asahi - Warehouse site.pdf"
        assert q.all_questionnaires == []
        stats = db.get_stats(conn)
        assert stats["totals"]["total_mergers"] == 3
    finally:
        conn.close()


def test_sync_indexes_multi_questionnaire(populated_db):
    conn = db.connect()
    try:
        q = db.get_questionnaire(conn, "MN-01017")
        assert q is not None
        assert q.questions_count == 3
        assert q.deadline_iso == "2025-06-01"
        assert q.file_name == "MN-01017 - PharmaCo - questionnaire - v2.pdf"
        assert len(q.all_questionnaires) == 2
        assert q.all_questionnaires[0]["deadline_iso"] == "2025-06-01"
        assert q.all_questionnaires[1]["deadline_iso"] == "2025-05-15"
    finally:
        conn.close()


def test_sync_indexes_noccs(populated_db):
    conn = db.connect()
    try:
        n = db.get_nocc(conn, "MN-01017")
        assert n is not None
        assert n.date_iso == "2026-03-01"
        assert n.document_type.startswith("Notice of Competition Concerns")
        assert n.file_name == "PharmaCo - NOCC summary - 1 March 2026.pdf"
        assert n.matter_id == "MN-01017"
        assert len(n.sections) == 2
        assert n.sections[0].title == "Introduction"
        assert n.sections[0].blocks[0].number == "1.1"
        assert n.sections[1].blocks[0].type == "heading"
    finally:
        conn.close()


def test_sync_indexes_question_sections(populated_db):
    conn = db.connect()
    try:
        q = db.get_questionnaire(conn, "MN-01016")
        assert q is not None
        assert q.questions[0]["section"] == "Questions for all respondents"
        assert q.questions[2]["section"] is None
    finally:
        conn.close()


def test_sync_writes_last_sync_timestamp(populated_db):
    assert db.LAST_SYNC_PATH.exists()
    assert sync.cache_exists()
    assert sync.is_cache_fresh() is True


def test_sync_caches_manifest_and_merger_manifest(populated_db):
    assert sync.manifest_cache_path().exists()
    assert sync.merger_manifest_cache_path().exists()
    cached = sync.read_cached_manifest()
    assert cached is not None
    assert cached["merger_count"] == 4
    assert "bundle_sha256" in cached


def test_second_sync_is_a_noop(temp_cache, fixture_tree):
    first = sync.sync()
    assert first.changed is True

    second = sync.sync()
    assert second.changed is False
    assert second.mergers == 4
    assert second.manifest["bundle_sha256"] == first.manifest["bundle_sha256"]


def test_force_sync_reindexes_even_when_hash_matches(temp_cache, fixture_tree):
    first = sync.sync()
    assert first.changed is True

    forced = sync.sync(force=True)
    assert forced.changed is True
    assert forced.mergers == 4


def test_sync_rejects_bundle_with_bad_hash(temp_cache, tmp_path, monkeypatch):
    root = tmp_path / "corrupt"
    write_bundle_tree(root, corrupt_bundle=True)
    monkeypatch.setenv(sync.BASE_URL_ENV, root.as_uri())

    with pytest.raises(sync.SyncError, match="hash mismatch"):
        sync.sync()

    # The index must not have been written.
    assert not db.DB_PATH.exists()


def test_sync_rejects_bundle_with_wrong_count(temp_cache, tmp_path, monkeypatch):
    root = tmp_path / "badcount"
    write_bundle_tree(root, fake_merger_count=999)
    monkeypatch.setenv(sync.BASE_URL_ENV, root.as_uri())

    with pytest.raises(sync.SyncError, match="merger count mismatch"):
        sync.sync()


def test_sync_tolerates_null_stats_and_industries(temp_cache, tmp_path, monkeypatch):
    root = tmp_path / "nulls"
    write_bundle_tree(root, stats=None, industries=None)
    monkeypatch.setenv(sync.BASE_URL_ENV, root.as_uri())

    result = sync.sync()
    assert result.changed is True
    assert result.mergers == 4

    conn = db.connect()
    try:
        assert db.get_stats(conn) is None
        assert db.get_industries(conn) is None
    finally:
        conn.close()


def test_sync_missing_manifest_is_hard_error(temp_cache, tmp_path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv(sync.BASE_URL_ENV, empty.as_uri())

    with pytest.raises(sync.SyncError, match="[Nn]ot found|File not found"):
        sync.sync()


def test_base_url_default_when_env_unset(monkeypatch):
    monkeypatch.delenv(sync.BASE_URL_ENV, raising=False)
    assert sync.base_url() == sync.DEFAULT_BASE_URL


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv(sync.BASE_URL_ENV, "https://example.com/cli")
    assert sync.base_url() == "https://example.com/cli"


def test_sync_with_explicit_local_path(temp_cache, tmp_path):
    root = tmp_path / "local-data"
    write_bundle_tree(root)

    result = sync.sync(source=str(root))

    assert result.changed is True
    assert result.mergers == 4


def test_sync_source_takes_precedence_over_env(temp_cache, tmp_path, monkeypatch):
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    write_bundle_tree(good)
    bad.mkdir()
    monkeypatch.setenv(sync.BASE_URL_ENV, bad.as_uri())

    result = sync.sync(source=str(good))

    assert result.changed is True
    assert result.mergers == 4
