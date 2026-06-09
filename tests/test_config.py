import os
import pytest
from immich_flickr_sync.config import load_config, Config


def test_loads_yaml(tmp_config_path):
    cfg = load_config(tmp_config_path)
    assert cfg.immich.url == "http://immich.example.com"
    assert cfg.immich.api_key == "test-immich-key"
    assert cfg.flickr.api_key == "test-flickr-key"
    assert cfg.sync.album_prefix == "[F]"
    assert cfg.sync.tags.extra_tags == ["immich-sync"]
    assert cfg.sync.tags.sync_immich_tags is True
    assert cfg.sync.licensing.licence_with_people == 0
    assert cfg.sync.licensing.licence_without_people == 3
    assert cfg.logging.level == "INFO"


def test_env_var_overrides_immich_api_key(tmp_config_path, monkeypatch):
    monkeypatch.setenv("IMMICH_API_KEY", "env-immich-key")
    cfg = load_config(tmp_config_path)
    assert cfg.immich.api_key == "env-immich-key"


def test_env_var_overrides_flickr_credentials(tmp_config_path, monkeypatch):
    monkeypatch.setenv("FLICKR_API_KEY", "env-fk")
    monkeypatch.setenv("FLICKR_API_SECRET", "env-fs")
    monkeypatch.setenv("FLICKR_ACCESS_TOKEN", "env-at")
    monkeypatch.setenv("FLICKR_ACCESS_TOKEN_SECRET", "env-ats")
    cfg = load_config(tmp_config_path)
    assert cfg.flickr.api_key == "env-fk"
    assert cfg.flickr.api_secret == "env-fs"
    assert cfg.flickr.access_token == "env-at"
    assert cfg.flickr.access_token_secret == "env-ats"


def test_missing_immich_url_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("immich:\n  api_key: x\nflickr:\n  api_key: x\n  api_secret: x\n")
    with pytest.raises((KeyError, ValueError)):
        load_config(bad)


def test_sync_defaults_applied(tmp_path):
    minimal = tmp_path / "minimal.yaml"
    minimal.write_text(
        "immich:\n  url: http://x\n  api_key: k\n"
        "flickr:\n  api_key: fk\n  api_secret: fs\n"
        "  access_token: at\n  access_token_secret: ats\n"
    )
    cfg = load_config(minimal)
    assert cfg.sync.album_prefix == "[F]"
    assert cfg.sync.flickr_photoset_prefix == ""
    assert cfg.sync.tags.sync_immich_tags is True
    assert cfg.sync.tags.extra_tags == []


def test_storage_path_defaults_to_none(tmp_config_path):
    cfg = load_config(tmp_config_path)
    assert cfg.immich.storage_path is None


def test_storage_path_loaded_when_set(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "immich:\n  url: http://x\n  api_key: k\n  storage_path: /mnt/immich\n"
        "flickr:\n  api_key: fk\n  api_secret: fs\n"
        "  access_token: at\n  access_token_secret: ats\n"
    )
    cfg = load_config(cfg_file)
    assert cfg.immich.storage_path == "/mnt/immich"
