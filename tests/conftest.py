import pytest
from pathlib import Path


@pytest.fixture
def tmp_state(tmp_path):
    return tmp_path / "state.json"


@pytest.fixture
def tmp_config_path(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
immich:
  url: "http://immich.example.com"
  api_key: "test-immich-key"
flickr:
  api_key: "test-flickr-key"
  api_secret: "test-flickr-secret"
  access_token: "test-token"
  access_token_secret: "test-token-secret"
sync:
  album_prefix: "[F]"
  state_file: "state.json"
  tmp_dir: "/tmp/immich-flickr-test"
  flickr_photoset_prefix: ""
  tags:
    sync_immich_tags: true
    extra_tags: ["immich-sync"]
  licensing:
    licence_with_people: 0
    licence_without_people: 3
logging:
  level: "INFO"
  format: "text"
""")
    return cfg
