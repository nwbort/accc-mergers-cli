"""Tests for the local-directory ingestion path used by sync."""

from __future__ import annotations

from mergers import db, sync


def test_persist_from_local_dir_indexes_everything(populated_db):
    conn = db.connect()
    try:
        assert db.count_mergers(conn) == 3
        merger = db.get_merger(conn, "MN-01016")
        assert merger is not None
        assert merger.merger_name.startswith("Asahi")
        q = db.get_questionnaire(conn, "MN-01016")
        assert q is not None
        assert q.questions_count == 3
        stats = db.get_stats(conn)
        assert stats["totals"]["total_mergers"] == 3
    finally:
        conn.close()


def test_sync_writes_last_sync_timestamp(populated_db):
    # persist_from_local_dir doesn't touch last_sync; write_last_sync does.
    sync.write_last_sync()
    assert db.LAST_SYNC_PATH.exists()
    assert sync.cache_exists()
    assert sync.is_cache_fresh() is True


def test_extract_merger_ids_from_list_of_dicts():
    ids = sync._extract_merger_ids(
        [{"merger_id": "MN-1"}, {"id": "MN-2"}, "MN-3"]
    )
    assert ids == ["MN-1", "MN-2", "MN-3"]


def test_extract_merger_ids_from_wrapped_dict():
    ids = sync._extract_merger_ids({"mergers": [{"merger_id": "MN-9"}]})
    assert ids == ["MN-9"]
