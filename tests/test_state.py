import json
import pytest
from pathlib import Path
from immich_flickr_sync.state import StateManager


def test_not_synced_initially(tmp_state):
    sm = StateManager(tmp_state)
    assert sm.is_synced("album-1", "asset-1") is False


def test_record_and_check_synced(tmp_state):
    sm = StateManager(tmp_state)
    sm.record_sync("album-1", "asset-1", "flickr-photo-1", licence_id=3, has_people=False)
    assert sm.is_synced("album-1", "asset-1") is True


def test_synced_asset_data_persisted(tmp_state):
    sm = StateManager(tmp_state)
    sm.record_sync("album-1", "asset-1", "flickr-photo-1", licence_id=0, has_people=True)
    sm2 = StateManager(tmp_state)
    assert sm2.is_synced("album-1", "asset-1") is True
    data = json.loads(tmp_state.read_text())
    rec = data["albums"]["album-1"]["synced_assets"]["asset-1"]
    assert rec["flickr_photo_id"] == "flickr-photo-1"
    assert rec["licence_id"] == 0
    assert rec["has_people"] is True


def test_photoset_id_roundtrip(tmp_state):
    sm = StateManager(tmp_state)
    assert sm.get_photoset_id("album-1") is None
    sm.set_photoset_id("album-1", "ps-999")
    assert sm.get_photoset_id("album-1") == "ps-999"


def test_photoset_id_survives_reload(tmp_state):
    sm = StateManager(tmp_state)
    sm.set_photoset_id("album-1", "ps-999")
    sm2 = StateManager(tmp_state)
    assert sm2.get_photoset_id("album-1") == "ps-999"


def test_atomic_write_no_tmp_leftover(tmp_state):
    sm = StateManager(tmp_state)
    sm.record_sync("album-1", "asset-1", "flickr-photo-1", licence_id=3, has_people=False)
    tmp_file = tmp_state.with_suffix(".tmp")
    assert not tmp_file.exists()


def test_loads_empty_structure_when_file_missing(tmp_path):
    path = tmp_path / "nonexistent.json"
    sm = StateManager(path)
    assert sm.is_synced("x", "y") is False


def test_different_albums_independent(tmp_state):
    sm = StateManager(tmp_state)
    sm.record_sync("album-1", "asset-1", "fp-1", licence_id=3, has_people=False)
    assert sm.is_synced("album-2", "asset-1") is False
