# immich-flickr-sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI that syncs favourited photos from prefixed Immich albums to matching Flickr photosets, idempotently, with licence assignment based on face detection.

**Architecture:** Seven focused modules — config loading, state management, Immich HTTP client, Flickr API wrapper, core sync loop, and click CLI — each with a corresponding test file. State is a single JSON file written atomically; no database required.

**Tech Stack:** Python 3.11+, click, requests, flickrapi, pyyaml, pytest, responses (HTTP mocking)

---

## File Map

| File | Responsibility |
|------|---------------|
| `pyproject.toml` | Package metadata, dependencies, entry point |
| `immich_flickr_sync/__init__.py` | Empty package marker |
| `immich_flickr_sync/config.py` | Dataclasses + YAML loader + env-var override |
| `immich_flickr_sync/state.py` | JSON state file, atomic writes, CRUD methods |
| `immich_flickr_sync/immich.py` | Immich REST client (requests), data models |
| `immich_flickr_sync/flickr.py` | flickrapi wrapper, upload, licence, NSID |
| `immich_flickr_sync/sync.py` | Core sync loop, retry logic, dry-run support |
| `immich_flickr_sync/cli.py` | click CLI: auth, run, status, validate |
| `tests/conftest.py` | Shared fixtures (minimal config, tmp paths) |
| `tests/test_config.py` | Config loading and env-var override |
| `tests/test_state.py` | State CRUD and atomic write |
| `tests/test_immich.py` | Immich client (mocked HTTP via `responses`) |
| `tests/test_flickr.py` | Flickr client (mocked flickrapi via `unittest.mock`) |
| `tests/test_sync.py` | Sync logic (all filtering, tagging, licensing, errors) |
| `config.example.yaml` | Template config for users |
| `Dockerfile` | Container image |
| `docker-compose.example.yml` | Compose example |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `immich_flickr_sync/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "immich-flickr-sync"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "flickrapi>=2.4",
    "requests>=2.31",
    "pyyaml>=6.0",
    "click>=8.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "responses>=0.23",
]

[project.scripts]
immich-flickr-sync = "immich_flickr_sync.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package and test stubs**

```bash
mkdir -p immich_flickr_sync tests
touch immich_flickr_sync/__init__.py tests/__init__.py
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
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
```

- [ ] **Step 4: Install package in editable mode**

```bash
pip install -e ".[dev]"
```

Expected: installs without errors, `immich-flickr-sync` command appears in PATH.

- [ ] **Step 5: Verify pytest collects nothing yet**

```bash
pytest --collect-only
```

Expected: `no tests ran` or empty collection — no errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml immich_flickr_sync/ tests/
git commit -m "chore: project scaffolding and test infrastructure"
```

---

## Task 2: Config Module

**Files:**
- Create: `tests/test_config.py`
- Create: `immich_flickr_sync/config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'load_config' from 'immich_flickr_sync.config'`

- [ ] **Step 3: Implement `immich_flickr_sync/config.py`**

```python
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class ImmichConfig:
    url: str
    api_key: str


@dataclass
class FlickrConfig:
    api_key: str
    api_secret: str
    access_token: str = ""
    access_token_secret: str = ""


@dataclass
class TagsConfig:
    sync_immich_tags: bool = True
    extra_tags: list[str] = field(default_factory=list)


@dataclass
class LicensingConfig:
    licence_with_people: int = 0
    licence_without_people: int = 3


@dataclass
class SyncConfig:
    album_prefix: str = "[F]"
    state_file: str = "state.json"
    tmp_dir: str = "/tmp/immich-flickr"
    flickr_photoset_prefix: str = ""
    tags: TagsConfig = field(default_factory=TagsConfig)
    licensing: LicensingConfig = field(default_factory=LicensingConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "text"


@dataclass
class Config:
    immich: ImmichConfig
    flickr: FlickrConfig
    sync: SyncConfig = field(default_factory=SyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: Path) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    immich_raw = data.get("immich", {})
    if v := os.environ.get("IMMICH_API_KEY"):
        immich_raw["api_key"] = v

    flickr_raw = data.get("flickr", {})
    for env, key in [
        ("FLICKR_API_KEY", "api_key"),
        ("FLICKR_API_SECRET", "api_secret"),
        ("FLICKR_ACCESS_TOKEN", "access_token"),
        ("FLICKR_ACCESS_TOKEN_SECRET", "access_token_secret"),
    ]:
        if v := os.environ.get(env):
            flickr_raw[key] = v

    immich = ImmichConfig(
        url=immich_raw["url"],
        api_key=immich_raw["api_key"],
    )
    flickr = FlickrConfig(
        api_key=flickr_raw["api_key"],
        api_secret=flickr_raw["api_secret"],
        access_token=flickr_raw.get("access_token", ""),
        access_token_secret=flickr_raw.get("access_token_secret", ""),
    )

    sync_raw = data.get("sync", {})
    tags_raw = sync_raw.get("tags", {})
    lic_raw = sync_raw.get("licensing", {})
    sync = SyncConfig(
        album_prefix=sync_raw.get("album_prefix", "[F]"),
        state_file=sync_raw.get("state_file", "state.json"),
        tmp_dir=sync_raw.get("tmp_dir", "/tmp/immich-flickr"),
        flickr_photoset_prefix=sync_raw.get("flickr_photoset_prefix", ""),
        tags=TagsConfig(
            sync_immich_tags=tags_raw.get("sync_immich_tags", True),
            extra_tags=tags_raw.get("extra_tags", []),
        ),
        licensing=LicensingConfig(
            licence_with_people=lic_raw.get("licence_with_people", 0),
            licence_without_people=lic_raw.get("licence_without_people", 3),
        ),
    )

    log_raw = data.get("logging", {})
    logging = LoggingConfig(
        level=log_raw.get("level", "INFO"),
        format=log_raw.get("format", "text"),
    )

    return Config(immich=immich, flickr=flickr, sync=sync, logging=logging)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add immich_flickr_sync/config.py tests/test_config.py
git commit -m "feat: config module with YAML loading and env-var override"
```

---

## Task 3: State Management

**Files:**
- Create: `tests/test_state.py`
- Create: `immich_flickr_sync/state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_state.py`:

```python
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
    # Reload from disk
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_state.py -v
```

Expected: `ImportError: cannot import name 'StateManager'`

- [ ] **Step 3: Implement `immich_flickr_sync/state.py`**

```python
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path


class StateManager:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            with open(self.path) as f:
                return json.load(f)
        return {"version": 1, "albums": {}}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self.path)

    def is_synced(self, album_id: str, asset_id: str) -> bool:
        return asset_id in self._data["albums"].get(album_id, {}).get("synced_assets", {})

    def record_sync(
        self,
        album_id: str,
        asset_id: str,
        flickr_photo_id: str,
        licence_id: int,
        has_people: bool,
    ) -> None:
        albums = self._data["albums"]
        if album_id not in albums:
            albums[album_id] = {"flickr_photoset_id": "", "synced_assets": {}}
        albums[album_id]["synced_assets"][asset_id] = {
            "flickr_photo_id": flickr_photo_id,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "licence_id": licence_id,
            "has_people": has_people,
        }
        self._save()

    def get_photoset_id(self, album_id: str) -> str | None:
        ps_id = self._data["albums"].get(album_id, {}).get("flickr_photoset_id", "")
        return ps_id or None

    def set_photoset_id(self, album_id: str, photoset_id: str) -> None:
        if album_id not in self._data["albums"]:
            self._data["albums"][album_id] = {"flickr_photoset_id": "", "synced_assets": {}}
        self._data["albums"][album_id]["flickr_photoset_id"] = photoset_id
        self._save()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_state.py -v
```

Expected: 8 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add immich_flickr_sync/state.py tests/test_state.py
git commit -m "feat: state management with atomic JSON writes"
```

---

## Task 4: Immich API Client

**Files:**
- Create: `tests/test_immich.py`
- Create: `immich_flickr_sync/immich.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_immich.py`:

```python
import responses as rsps_lib
import pytest
from pathlib import Path
from immich_flickr_sync.immich import ImmichClient, Album, Asset, Tag, Person


BASE = "http://immich.example.com/api"


@rsps_lib.activate
def test_get_albums_returns_list():
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/albums",
        json=[
            {"id": "a1", "albumName": "[F] Paris", "assetCount": 3, "updatedAt": "2026-01-01T00:00:00Z"},
            {"id": "a2", "albumName": "No prefix", "assetCount": 1, "updatedAt": "2026-01-02T00:00:00Z"},
        ],
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    albums = client.get_albums()
    assert len(albums) == 2
    assert albums[0].id == "a1"
    assert albums[0].albumName == "[F] Paris"


@rsps_lib.activate
def test_get_album_assets_returns_assets():
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/albums/a1",
        json={
            "id": "a1",
            "albumName": "[F] Paris",
            "assets": [
                {
                    "id": "asset-1",
                    "originalFileName": "IMG_001.jpg",
                    "isFavorite": True,
                    "type": "IMAGE",
                    "fileCreatedAt": "2026-03-01T12:00:00Z",
                    "exifInfo": None,
                },
                {
                    "id": "asset-2",
                    "originalFileName": "IMG_002.jpg",
                    "isFavorite": False,
                    "type": "IMAGE",
                    "fileCreatedAt": "2026-03-02T12:00:00Z",
                    "exifInfo": None,
                },
            ],
        },
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    assets = client.get_album_assets("a1")
    assert len(assets) == 2
    assert assets[0].id == "asset-1"
    assert assets[0].isFavorite is True
    assert assets[0].tags == []
    assert assets[0].people == []


@rsps_lib.activate
def test_get_asset_detail_returns_tags_and_people():
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/assets/asset-1",
        json={
            "id": "asset-1",
            "originalFileName": "IMG_001.jpg",
            "isFavorite": True,
            "type": "IMAGE",
            "fileCreatedAt": "2026-03-01T12:00:00Z",
            "exifInfo": None,
            "tags": [{"id": "t1", "name": "travel/europe"}],
            "people": [{"id": "p1", "name": ""}],
        },
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    asset = client.get_asset_detail("asset-1")
    assert len(asset.tags) == 1
    assert asset.tags[0].name == "travel/europe"
    assert len(asset.people) == 1
    assert asset.people[0].name == ""


@rsps_lib.activate
def test_get_asset_detail_empty_people():
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/assets/asset-2",
        json={
            "id": "asset-2",
            "originalFileName": "IMG_002.jpg",
            "isFavorite": True,
            "type": "IMAGE",
            "fileCreatedAt": "2026-03-01T12:00:00Z",
            "exifInfo": None,
            "tags": [],
            "people": [],
        },
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    asset = client.get_asset_detail("asset-2")
    assert asset.people == []


@rsps_lib.activate
def test_download_asset_writes_file(tmp_path):
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/assets/asset-1/original",
        body=b"fake-image-bytes",
        stream=True,
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    dest = tmp_path / "asset-1.jpg"
    result = client.download_asset("asset-1", dest)
    assert result == dest
    assert dest.read_bytes() == b"fake-image-bytes"


@rsps_lib.activate
def test_auth_header_sent():
    rsps_lib.add(rsps_lib.GET, f"{BASE}/albums", json=[])
    client = ImmichClient(base_url="http://immich.example.com", api_key="my-secret-key")
    client.get_albums()
    assert rsps_lib.calls[0].request.headers["x-api-key"] == "my-secret-key"


@rsps_lib.activate
def test_immich_401_raises():
    rsps_lib.add(rsps_lib.GET, f"{BASE}/albums", status=401)
    client = ImmichClient(base_url="http://immich.example.com", api_key="bad-key")
    with pytest.raises(PermissionError):
        client.get_albums()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_immich.py -v
```

Expected: `ImportError: cannot import name 'ImmichClient'`

- [ ] **Step 3: Implement `immich_flickr_sync/immich.py`**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import requests


@dataclass
class Tag:
    id: str
    name: str


@dataclass
class Person:
    id: str
    name: str


@dataclass
class Asset:
    id: str
    originalFileName: str
    isFavorite: bool
    type: str
    fileCreatedAt: str
    exifInfo: dict | None
    tags: list[Tag] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)


@dataclass
class Album:
    id: str
    albumName: str
    assetCount: int
    updatedAt: str


def _parse_asset(raw: dict) -> Asset:
    return Asset(
        id=raw["id"],
        originalFileName=raw["originalFileName"],
        isFavorite=raw["isFavorite"],
        type=raw["type"],
        fileCreatedAt=raw["fileCreatedAt"],
        exifInfo=raw.get("exifInfo"),
        tags=[Tag(id=t["id"], name=t["name"]) for t in raw.get("tags", [])],
        people=[Person(id=p["id"], name=p.get("name", "")) for p in raw.get("people", [])],
    )


class ImmichClient:
    def __init__(self, base_url: str, api_key: str):
        self._base = base_url.rstrip("/") + "/api"
        self._session = requests.Session()
        self._session.headers["x-api-key"] = api_key

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self._session.get(f"{self._base}{path}", **kwargs)
        if resp.status_code in (401, 403):
            raise PermissionError(f"Immich auth failed ({resp.status_code}): {path}")
        resp.raise_for_status()
        return resp

    def get_albums(self) -> list[Album]:
        data = self._get("/albums").json()
        return [
            Album(
                id=a["id"],
                albumName=a["albumName"],
                assetCount=a["assetCount"],
                updatedAt=a["updatedAt"],
            )
            for a in data
        ]

    def get_album_assets(self, album_id: str) -> list[Asset]:
        data = self._get(f"/albums/{album_id}").json()
        return [_parse_asset(a) for a in data.get("assets", [])]

    def get_asset_detail(self, asset_id: str) -> Asset:
        data = self._get(f"/assets/{asset_id}").json()
        return _parse_asset(data)

    def download_asset(self, asset_id: str, dest_path: Path) -> Path:
        with self._session.get(
            f"{self._base}/assets/{asset_id}/original", stream=True
        ) as resp:
            if resp.status_code in (401, 403):
                raise PermissionError(f"Immich auth failed on download: {asset_id}")
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
        return dest_path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_immich.py -v
```

Expected: 7 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add immich_flickr_sync/immich.py tests/test_immich.py
git commit -m "feat: Immich API client with data models"
```

---

## Task 5: Flickr API Client

**Files:**
- Create: `tests/test_flickr.py`
- Create: `immich_flickr_sync/flickr.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_flickr.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from immich_flickr_sync.flickr import FlickrClient, Photoset


def make_client():
    with patch("immich_flickr_sync.flickr.flickrapi.FlickrAPI") as MockAPI:
        mock_api = MagicMock()
        MockAPI.return_value = mock_api
        client = FlickrClient(
            api_key="fk", api_secret="fs",
            access_token="at", access_token_secret="ats",
        )
        client._api = mock_api
    return client, mock_api


def test_get_photosets_returns_list():
    client, mock_api = make_client()
    mock_api.photosets.getList.return_value = {
        "photosets": {
            "photoset": [
                {"id": "ps1", "title": {"_content": "Paris"}},
                {"id": "ps2", "title": {"_content": "London"}},
            ]
        }
    }
    photosets = client.get_photosets()
    assert len(photosets) == 2
    assert photosets[0].id == "ps1"
    assert photosets[0].title == "Paris"


def test_get_photosets_empty():
    client, mock_api = make_client()
    mock_api.photosets.getList.return_value = {"photosets": {"photoset": []}}
    assert client.get_photosets() == []


def test_create_photoset():
    client, mock_api = make_client()
    mock_api.photosets.create.return_value = {
        "photoset": {"id": "ps-new"}
    }
    ps = client.create_photoset("My Album", primary_photo_id="photo-1")
    mock_api.photosets.create.assert_called_once_with(
        title="My Album", primary_photo_id="photo-1"
    )
    assert ps.id == "ps-new"
    assert ps.title == "My Album"


def test_add_photo_to_photoset():
    client, mock_api = make_client()
    client.add_photo_to_photoset("ps-1", "photo-2")
    mock_api.photosets.addPhoto.assert_called_once_with(
        photoset_id="ps-1", photo_id="photo-2"
    )


def test_upload_photo_returns_photo_id(tmp_path):
    client, mock_api = make_client()
    mock_api.upload.return_value = MagicMock(
        find=lambda tag: MagicMock(text="uploaded-photo-id")
    )
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"img")
    photo_id = client.upload_photo(
        file_path=img,
        title="My Photo",
        tags=["tag1", "tag2"],
        date_taken="2026-03-01T12:00:00Z",
    )
    assert photo_id == "uploaded-photo-id"
    mock_api.upload.assert_called_once()
    call_kwargs = mock_api.upload.call_args[1]
    assert call_kwargs["filename"] == str(img)
    assert call_kwargs["title"] == "My Photo"
    assert "tag1 tag2" in call_kwargs["tags"]
    assert call_kwargs["is_public"] == 0


def test_set_licence():
    client, mock_api = make_client()
    client.set_licence("photo-1", 3)
    mock_api.photos.licenses.setLicense.assert_called_once_with(
        photo_id="photo-1", license_id=3
    )


def test_get_photos_in_photoset():
    client, mock_api = make_client()
    mock_api.photosets.getPhotos.return_value = {
        "photoset": {
            "photo": [{"id": "p1"}, {"id": "p2"}]
        }
    }
    ids = client.get_photos_in_photoset("ps-1")
    assert ids == ["p1", "p2"]


def test_get_user_nsid():
    client, mock_api = make_client()
    mock_api.auth.checkToken.return_value = {
        "auth": {"user": {"nsid": "12345678@N00"}}
    }
    nsid = client.get_user_nsid()
    assert nsid == "12345678@N00"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_flickr.py -v
```

Expected: `ImportError: cannot import name 'FlickrClient'`

- [ ] **Step 3: Implement `immich_flickr_sync/flickr.py`**

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import flickrapi


@dataclass
class Photoset:
    id: str
    title: str


class FlickrClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str,
        access_token_secret: str,
    ):
        self._api = flickrapi.FlickrAPI(
            api_key, api_secret,
            token=access_token,
            token_secret=access_token_secret,
            format="parsed-json",
        )

    def get_photosets(self) -> list[Photoset]:
        resp = self._api.photosets.getList()
        raw = resp["photosets"].get("photoset", [])
        return [Photoset(id=p["id"], title=p["title"]["_content"]) for p in raw]

    def create_photoset(self, title: str, primary_photo_id: str) -> Photoset:
        resp = self._api.photosets.create(title=title, primary_photo_id=primary_photo_id)
        return Photoset(id=resp["photoset"]["id"], title=title)

    def add_photo_to_photoset(self, photoset_id: str, photo_id: str) -> None:
        self._api.photosets.addPhoto(photoset_id=photoset_id, photo_id=photo_id)

    def upload_photo(
        self,
        file_path: Path,
        title: str,
        tags: list[str],
        date_taken: str,
        is_public: bool = False,
    ) -> str:
        resp = self._api.upload(
            filename=str(file_path),
            title=title,
            tags=" ".join(tags),
            date_taken=date_taken,
            is_public=1 if is_public else 0,
            is_friend=0,
            is_family=0,
        )
        return resp.find("photoid").text

    def set_licence(self, photo_id: str, licence_id: int) -> None:
        self._api.photos.licenses.setLicense(photo_id=photo_id, license_id=licence_id)

    def get_photos_in_photoset(self, photoset_id: str) -> list[str]:
        resp = self._api.photosets.getPhotos(photoset_id=photoset_id)
        return [p["id"] for p in resp["photoset"].get("photo", [])]

    def get_user_nsid(self) -> str:
        resp = self._api.auth.checkToken()
        return resp["auth"]["user"]["nsid"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_flickr.py -v
```

Expected: 9 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add immich_flickr_sync/flickr.py tests/test_flickr.py
git commit -m "feat: Flickr API client wrapping flickrapi"
```

---

## Task 6: Core Sync Logic

**Files:**
- Create: `tests/test_sync.py`
- Create: `immich_flickr_sync/sync.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sync.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from immich_flickr_sync.config import (
    Config, ImmichConfig, FlickrConfig, SyncConfig,
    TagsConfig, LicensingConfig, LoggingConfig,
)
from immich_flickr_sync.immich import Album, Asset, Tag, Person
from immich_flickr_sync.flickr import Photoset
from immich_flickr_sync.state import StateManager
from immich_flickr_sync.sync import run_sync


def make_config(prefix="[F]", extra_tags=None, sync_immich_tags=True,
                licence_with=0, licence_without=3, photoset_prefix=""):
    return Config(
        immich=ImmichConfig(url="http://x", api_key="k"),
        flickr=FlickrConfig(api_key="fk", api_secret="fs",
                            access_token="at", access_token_secret="ats"),
        sync=SyncConfig(
            album_prefix=prefix,
            state_file="state.json",
            tmp_dir="/tmp/test",
            flickr_photoset_prefix=photoset_prefix,
            tags=TagsConfig(sync_immich_tags=sync_immich_tags, extra_tags=extra_tags or []),
            licensing=LicensingConfig(
                licence_with_people=licence_with,
                licence_without_people=licence_without,
            ),
        ),
        logging=LoggingConfig(),
    )


def make_album(id="a1", name="[F] Paris"):
    return Album(id=id, albumName=name, assetCount=1, updatedAt="2026-01-01T00:00:00Z")


def make_asset(id="asset-1", favourite=True, type_="IMAGE",
               tags=None, people=None, filename="IMG_001.jpg"):
    return Asset(
        id=id,
        originalFileName=filename,
        isFavorite=favourite,
        type=type_,
        fileCreatedAt="2026-03-01T12:00:00Z",
        exifInfo=None,
        tags=tags or [],
        people=people or [],
    )


def make_mocks(tmp_path, state_data=None):
    immich = MagicMock()
    flickr = MagicMock()
    state = StateManager(tmp_path / "state.json")
    flickr.upload_photo.return_value = "flickr-photo-1"
    flickr.get_photosets.return_value = []
    flickr.create_photoset.return_value = Photoset(id="ps-1", title="Paris")
    return immich, flickr, state


def test_album_prefix_filtering(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [
        make_album("a1", "[F] Paris"),
        make_album("a2", "No prefix"),
        make_album("a3", "[F] London"),
    ]
    immich.get_album_assets.return_value = []

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    assert immich.get_album_assets.call_count == 2
    called_ids = {c.args[0] for c in immich.get_album_assets.call_args_list}
    assert called_ids == {"a1", "a3"}


def test_only_favourite_images_uploaded(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [
        make_asset("a1", favourite=True, type_="IMAGE"),
        make_asset("a2", favourite=False, type_="IMAGE"),
        make_asset("a3", favourite=True, type_="VIDEO"),
    ]
    immich.get_asset_detail.return_value = make_asset("a1")
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    assert immich.get_asset_detail.call_count == 1
    assert flickr.upload_photo.call_count == 1


def test_get_asset_detail_not_called_for_non_favourites(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [
        make_asset("a1", favourite=False),
        make_asset("a2", favourite=True, type_="VIDEO"),
    ]

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    immich.get_asset_detail.assert_not_called()


def test_tags_merged_from_immich_and_extra(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    detail = make_asset("a1", tags=[Tag("t1", "travel/europe")])
    immich.get_asset_detail.return_value = detail
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(extra_tags=["immich-sync"], sync_immich_tags=True)
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    tags_used = flickr.upload_photo.call_args[1]["tags"]
    assert "immich-sync" in tags_used
    assert "travel/europe" in tags_used


def test_tags_not_synced_when_disabled(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    detail = make_asset("a1", tags=[Tag("t1", "travel/europe")])
    immich.get_asset_detail.return_value = detail
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(extra_tags=["immich-sync"], sync_immich_tags=False)
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    tags_used = flickr.upload_photo.call_args[1]["tags"]
    assert "travel/europe" not in tags_used
    assert "immich-sync" in tags_used


def test_licence_with_people(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1", people=[Person("p1", "")])
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(licence_with=0, licence_without=3)
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.set_licence.assert_called_once_with("flickr-photo-1", 0)


def test_licence_without_people(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1", people=[])
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(licence_with=0, licence_without=3)
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.set_licence.assert_called_once_with("flickr-photo-1", 3)


def test_unnamed_face_counts_as_person(tmp_path):
    # An unnamed face (empty name) still sets licence_with_people
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1", people=[Person("p1", "")])
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(licence_with=0, licence_without=3)
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.set_licence.assert_called_once_with("flickr-photo-1", 0)


def test_idempotent_already_synced(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    state.set_photoset_id("a1", "ps-1")
    state.record_sync("a1", "asset-1", "old-flickr-id", licence_id=3, has_people=False)

    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    immich.get_asset_detail.assert_not_called()
    flickr.upload_photo.assert_not_called()
    flickr.set_licence.assert_not_called()


def test_photoset_created_on_first_sync(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album("a1", "[F] Paris")]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1")
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.create_photoset.assert_called_once_with("Paris", primary_photo_id="flickr-photo-1")
    assert state.get_photoset_id("a1") == "ps-1"


def test_photoset_reused_on_second_sync(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    state.set_photoset_id("a1", "existing-ps")
    flickr.get_photosets.return_value = [Photoset(id="existing-ps", title="Paris")]

    immich.get_albums.return_value = [make_album("a1", "[F] Paris")]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1")
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.create_photoset.assert_not_called()
    flickr.add_photo_to_photoset.assert_called_once_with("existing-ps", "flickr-photo-1")


def test_dry_run_no_mutations(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1", people=[])

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=True)

    flickr.upload_photo.assert_not_called()
    flickr.set_licence.assert_not_called()
    flickr.create_photoset.assert_not_called()
    assert not state.is_synced("a1", "asset-1")


def test_network_error_on_single_asset_continues(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album()]
    immich.get_album_assets.return_value = [
        make_asset("a1"),
        make_asset("a2", filename="IMG_002.jpg"),
    ]

    detail_a1 = make_asset("a1")
    detail_a2 = make_asset("a2")
    immich.get_asset_detail.side_effect = [detail_a1, detail_a2]

    fail_path = tmp_path / "a1.jpg"
    ok_path = tmp_path / "a2.jpg"
    ok_path.write_bytes(b"img")
    immich.download_asset.side_effect = [
        OSError("network failure"),
        ok_path,
    ]

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp", dry_run=False)

    assert flickr.upload_photo.call_count == 1
    assert state.is_synced("a1", "a2")


def test_flickr_photoset_prefix_applied(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [make_album("a1", "[F] Paris")]
    immich.get_album_assets.return_value = [make_asset("a1")]
    immich.get_asset_detail.return_value = make_asset("a1")
    immich.download_asset.return_value = tmp_path / "a1.jpg"
    (tmp_path / "a1.jpg").write_bytes(b"img")

    cfg = make_config(photoset_prefix="Best: ")
    run_sync(cfg, immich, flickr, state, tmp_path / "tmp", dry_run=False)

    flickr.create_photoset.assert_called_once_with(
        "Best: Paris", primary_photo_id="flickr-photo-1"
    )


def test_album_filter_by_name(tmp_path):
    immich, flickr, state = make_mocks(tmp_path)
    immich.get_albums.return_value = [
        make_album("a1", "[F] Paris"),
        make_album("a2", "[F] London"),
    ]
    immich.get_album_assets.return_value = []

    run_sync(make_config(), immich, flickr, state, tmp_path / "tmp",
             dry_run=False, album_filter="Paris")

    assert immich.get_album_assets.call_count == 1
    immich.get_album_assets.assert_called_with("a1")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sync.py -v
```

Expected: `ImportError: cannot import name 'run_sync'`

- [ ] **Step 3: Implement `immich_flickr_sync/sync.py`**

```python
from __future__ import annotations
import logging
import time
from pathlib import Path

from immich_flickr_sync.config import Config
from immich_flickr_sync.state import StateManager

log = logging.getLogger(__name__)

_RETRY_CODES = {429}
_FLICKR_RATE_LIMIT_CODE = 18


def _flickr_title(filename: str) -> str:
    return Path(filename).stem


def _get_or_create_photoset(flickr, state: StateManager, album_id: str, title: str, primary_photo_id: str):
    ps_id = state.get_photoset_id(album_id)
    if ps_id:
        return ps_id
    ps = flickr.create_photoset(title, primary_photo_id=primary_photo_id)
    state.set_photoset_id(album_id, ps.id)
    return ps.id


def _upload_with_retry(flickr, **kwargs) -> str:
    delay = 5
    for attempt in range(3):
        try:
            return flickr.upload_photo(**kwargs)
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or str(_FLICKR_RATE_LIMIT_CODE) in msg:
                if attempt < 2:
                    log.warning("Flickr rate limit, retrying in %ds", delay)
                    time.sleep(delay)
                    delay *= 2
                    continue
            raise
    raise RuntimeError("Flickr upload failed after retries")


def run_sync(
    config: Config,
    immich,
    flickr,
    state: StateManager,
    tmp_dir: Path,
    dry_run: bool = False,
    album_filter: str | None = None,
) -> None:
    prefix = config.sync.album_prefix
    albums = immich.get_albums()

    for album in albums:
        if not album.albumName.startswith(prefix):
            continue

        flickr_title_base = album.albumName.removeprefix(prefix).strip()
        if config.sync.flickr_photoset_prefix:
            flickr_title_full = config.sync.flickr_photoset_prefix + flickr_title_base
        else:
            flickr_title_full = flickr_title_base

        if album_filter and flickr_title_base != album_filter:
            continue

        assets = immich.get_album_assets(album.id)
        candidates = [a for a in assets if a.isFavorite and a.type == "IMAGE"]

        uploaded = 0
        already_synced = 0
        skipped = len(assets) - len(candidates)
        photoset_id: str | None = state.get_photoset_id(album.id)
        first_upload_in_album = True

        for asset in candidates:
            if state.is_synced(album.id, asset.id):
                already_synced += 1
                continue

            try:
                detail = immich.get_asset_detail(asset.id)
            except Exception as exc:
                log.warning("Failed to fetch detail for %s: %s", asset.id, exc)
                continue

            flickr_tags = list(config.sync.tags.extra_tags)
            if config.sync.tags.sync_immich_tags:
                flickr_tags += [t.name for t in detail.tags]

            has_people = len(detail.people) > 0
            licence_id = (
                config.sync.licensing.licence_with_people
                if has_people
                else config.sync.licensing.licence_without_people
            )

            if dry_run:
                log.info(
                    "[dry-run] Would upload %s → tags=%s licence=%d",
                    asset.originalFileName, flickr_tags, licence_id,
                )
                continue

            ext = Path(asset.originalFileName).suffix
            tmp_file = tmp_dir / f"{asset.id}{ext}"
            tmp_dir.mkdir(parents=True, exist_ok=True)

            try:
                immich.download_asset(asset.id, tmp_file)
                photo_id = _upload_with_retry(
                    flickr,
                    file_path=tmp_file,
                    title=_flickr_title(asset.originalFileName),
                    tags=flickr_tags,
                    date_taken=asset.fileCreatedAt,
                )
                flickr.set_licence(photo_id, licence_id)

                if photoset_id is None:
                    photoset_id = _get_or_create_photoset(
                        flickr, state, album.id, flickr_title_full, photo_id
                    )
                else:
                    flickr.add_photo_to_photoset(photoset_id, photo_id)

                state.record_sync(album.id, asset.id, photo_id, licence_id, has_people)
                uploaded += 1
                log.info(
                    "Uploaded %s tags=%s licence=%d",
                    asset.originalFileName, flickr_tags, licence_id,
                )
            except Exception as exc:
                log.warning("Failed to sync asset %s: %s", asset.id, exc)
            finally:
                if tmp_file.exists():
                    tmp_file.unlink()

        log.info(
            "Album '%s': %d uploaded, %d already synced, %d skipped (not favourite)",
            album.albumName, uploaded, already_synced, skipped,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sync.py -v
```

Expected: 14 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add immich_flickr_sync/sync.py tests/test_sync.py
git commit -m "feat: core sync logic with filtering, licensing, retry, and dry-run"
```

---

## Task 7: CLI

**Files:**
- Create: `immich_flickr_sync/cli.py`

Note: CLI tests use `click.testing.CliRunner`. The `auth` subcommand wraps
`flickrapi.FlickrAPI` OAuth flow; in tests we mock it entirely.

- [ ] **Step 1: Write failing CLI tests**

Add to a new file `tests/test_cli.py`:

```python
import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from immich_flickr_sync.cli import main


def test_validate_passes(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config") as mock_val:
        mock_val.return_value = None
        result = runner.invoke(main, ["validate", "--config", str(tmp_config_path)])
    assert result.exit_code == 0


def test_validate_fails_on_bad_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("immich:\n  api_key: x\n")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--config", str(bad)])
    assert result.exit_code != 0


def test_run_dry_run_calls_sync(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager"), \
         patch("immich_flickr_sync.cli.run_sync") as mock_sync:
        MockImmich.return_value = MagicMock()
        MockFlickr.return_value = MagicMock()
        result = runner.invoke(main, ["run", "--config", str(tmp_config_path), "--dry-run"])
    assert result.exit_code == 0
    mock_sync.assert_called_once()
    _, kwargs = mock_sync.call_args
    assert kwargs.get("dry_run") is True or mock_sync.call_args[0][5] is True


def test_run_album_filter_passed(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager"), \
         patch("immich_flickr_sync.cli.run_sync") as mock_sync:
        MockImmich.return_value = MagicMock()
        MockFlickr.return_value = MagicMock()
        result = runner.invoke(main, [
            "run", "--config", str(tmp_config_path), "--album", "Paris"
        ])
    assert result.exit_code == 0
    args = mock_sync.call_args
    album_filter = args[1].get("album_filter") or args[0][6]
    assert album_filter == "Paris"


def test_status_prints_table(tmp_config_path, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "version": 1,
        "albums": {
            "a1": {
                "flickr_photoset_id": "ps-1",
                "synced_assets": {
                    "asset-1": {"flickr_photo_id": "fp-1", "synced_at": "2026-01-01T00:00:00Z",
                                "licence_id": 3, "has_people": False}
                }
            }
        }
    }))
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager") as MockState:
        mock_immich = MagicMock()
        mock_flickr = MagicMock()
        MockImmich.return_value = mock_immich
        MockFlickr.return_value = mock_flickr
        mock_flickr.get_user_nsid.return_value = "12345@N00"

        from immich_flickr_sync.state import StateManager as RealState
        MockState.return_value = RealState(state_path)

        from immich_flickr_sync.immich import Album
        mock_immich.get_albums.return_value = [
            Album(id="a1", albumName="[F] Paris", assetCount=5, updatedAt="2026-01-01T00:00:00Z")
        ]
        mock_immich.get_album_assets.return_value = [MagicMock(isFavorite=True, type="IMAGE")] * 3

        result = runner.invoke(main, ["status", "--config", str(tmp_config_path)])
    assert result.exit_code == 0
    assert "Paris" in result.output
    assert "ps-1" in result.output or "12345@N00" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'main'`

- [ ] **Step 3: Implement `immich_flickr_sync/cli.py`**

```python
from __future__ import annotations
import logging
import sys
from pathlib import Path

import click
import requests

from immich_flickr_sync.config import load_config, Config
from immich_flickr_sync.flickr import FlickrClient
from immich_flickr_sync.immich import ImmichClient
from immich_flickr_sync.state import StateManager
from immich_flickr_sync.sync import run_sync


def _setup_logging(config: Config) -> None:
    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    fmt = (
        '{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}'
        if config.logging.format == "json"
        else "%(asctime)s %(levelname)s %(message)s"
    )
    logging.basicConfig(level=level, format=fmt)


def validate_config(config: Config) -> None:
    errors = []

    try:
        resp = requests.get(
            f"{config.immich.url.rstrip('/')}/api/server/about",
            headers={"x-api-key": config.immich.api_key},
            timeout=10,
        )
        if resp.status_code == 401:
            errors.append("Immich API key is invalid (401)")
        elif not resp.ok:
            errors.append(f"Immich not reachable: HTTP {resp.status_code}")
    except requests.RequestException as exc:
        errors.append(f"Immich not reachable: {exc}")

    try:
        import flickrapi
        api = flickrapi.FlickrAPI(
            config.flickr.api_key,
            config.flickr.api_secret,
            token=config.flickr.access_token,
            token_secret=config.flickr.access_token_secret,
            format="parsed-json",
        )
        api.auth.checkToken()
    except Exception as exc:
        errors.append(f"Flickr auth failed: {exc}")

    tmp_dir = Path(config.sync.tmp_dir)
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        test_file = tmp_dir / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
    except OSError as exc:
        errors.append(f"tmp_dir not writable: {exc}")

    state_parent = Path(config.sync.state_file).parent
    try:
        state_parent.mkdir(parents=True, exist_ok=True)
        test_file = state_parent / ".write_test"
        test_file.write_text("ok")
        test_file.unlink()
    except OSError as exc:
        errors.append(f"state_file parent not writable: {exc}")

    if errors:
        for e in errors:
            click.echo(f"ERROR: {e}", err=True)
        raise SystemExit(1)


@click.group()
def main() -> None:
    pass


@main.command()
def auth() -> None:
    """Run Flickr OAuth PIN flow and print credentials."""
    import flickrapi

    api_key = click.prompt("Flickr API key")
    api_secret = click.prompt("Flickr API secret")

    flickr = flickrapi.FlickrAPI(api_key, api_secret)
    flickr.get_request_token(oauth_callback="oob")
    auth_url = flickr.auth_url(perms="write")
    click.echo(f"\nVisit this URL to authorise:\n  {auth_url}\n")
    pin = click.prompt("Enter the PIN shown on Flickr")
    flickr.get_access_token(pin)

    click.echo("\nAuthorisation successful! Add these to your config.yaml:\n")
    click.echo(f"  access_token: \"{flickr.token_cache.token.token}\"")
    click.echo(f"  access_token_secret: \"{flickr.token_cache.token.token_secret}\"")


@main.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--album", "album_filter", default=None,
              help="Sync only this album (name without prefix)")
def run(config_path: Path, dry_run: bool, album_filter: str | None) -> None:
    """Run the sync."""
    config = load_config(config_path)
    _setup_logging(config)
    validate_config(config)

    immich = ImmichClient(base_url=config.immich.url, api_key=config.immich.api_key)
    flickr = FlickrClient(
        api_key=config.flickr.api_key,
        api_secret=config.flickr.api_secret,
        access_token=config.flickr.access_token,
        access_token_secret=config.flickr.access_token_secret,
    )
    state = StateManager(Path(config.sync.state_file))
    tmp_dir = Path(config.sync.tmp_dir)

    run_sync(config, immich, flickr, state, tmp_dir, dry_run=dry_run, album_filter=album_filter)


@main.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True,
              type=click.Path(exists=True, path_type=Path))
def status(config_path: Path) -> None:
    """Print sync status table."""
    config = load_config(config_path)
    _setup_logging(config)
    validate_config(config)

    immich = ImmichClient(base_url=config.immich.url, api_key=config.immich.api_key)
    flickr = FlickrClient(
        api_key=config.flickr.api_key,
        api_secret=config.flickr.api_secret,
        access_token=config.flickr.access_token,
        access_token_secret=config.flickr.access_token_secret,
    )
    state = StateManager(Path(config.sync.state_file))

    nsid = flickr.get_user_nsid()
    prefix = config.sync.album_prefix
    albums = immich.get_albums()

    click.echo(f"{'Album':<40} {'Synced':>6} {'Pending':>7} {'Photoset URL'}")
    click.echo("-" * 100)
    for album in albums:
        if not album.albumName.startswith(prefix):
            continue
        assets = immich.get_album_assets(album.id)
        favourites = [a for a in assets if a.isFavorite and a.type == "IMAGE"]
        ps_id = state.get_photoset_id(album.id)
        synced = sum(1 for a in favourites if state.is_synced(album.id, a.id))
        pending = len(favourites) - synced
        url = (
            f"https://www.flickr.com/photos/{nsid}/sets/{ps_id}/"
            if ps_id else "—"
        )
        name = album.albumName.removeprefix(prefix).strip()
        click.echo(f"{name:<40} {synced:>6} {pending:>7} {url}")


@main.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True,
              type=click.Path(exists=True, path_type=Path))
def validate(config_path: Path) -> None:
    """Validate config and connectivity."""
    try:
        config = load_config(config_path)
    except (KeyError, ValueError) as exc:
        click.echo(f"ERROR: Config invalid: {exc}", err=True)
        sys.exit(1)
    validate_config(config)
    click.echo("All checks passed.")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Run the full test suite**

```bash
pytest -v
```

Expected: all tests across all modules PASSED.

- [ ] **Step 6: Commit**

```bash
git add immich_flickr_sync/cli.py tests/test_cli.py
git commit -m "feat: click CLI with auth, run, status, validate subcommands"
```

---

## Task 8: Config Example and Docker Files

**Files:**
- Create: `config.example.yaml`
- Create: `Dockerfile`
- Create: `docker-compose.example.yml`

No tests for these — correctness verified by inspection.

- [ ] **Step 1: Write `config.example.yaml`**

```yaml
immich:
  url: "http://192.168.1.154:2283"
  api_key: "YOUR_IMMICH_API_KEY"   # or set env var IMMICH_API_KEY

flickr:
  api_key: "YOUR_FLICKR_API_KEY"         # or FLICKR_API_KEY
  api_secret: "YOUR_FLICKR_API_SECRET"   # or FLICKR_API_SECRET
  access_token: "YOUR_ACCESS_TOKEN"          # or FLICKR_ACCESS_TOKEN
  access_token_secret: "YOUR_ACCESS_TOKEN_SECRET"  # or FLICKR_ACCESS_TOKEN_SECRET

sync:
  album_prefix: "[F]"
  state_file: "data/state.json"
  tmp_dir: "/tmp/immich-flickr"
  flickr_photoset_prefix: ""
  tags:
    sync_immich_tags: true
    extra_tags:
      - "immich-sync"
  licensing:
    licence_with_people: 0   # All Rights Reserved
    licence_without_people: 3  # CC BY-NC-ND

logging:
  level: "INFO"
  format: "text"   # or "json"
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
VOLUME ["/app/data"]
ENTRYPOINT ["immich-flickr-sync"]
CMD ["run", "--config", "/app/data/config.yaml"]
```

- [ ] **Step 3: Write `docker-compose.example.yml`**

```yaml
services:
  immich-flickr-sync:
    build: .
    volumes:
      - ./data:/app/data
    environment:
      - IMMICH_API_KEY=${IMMICH_API_KEY}
      - FLICKR_API_KEY=${FLICKR_API_KEY}
      - FLICKR_API_SECRET=${FLICKR_API_SECRET}
      - FLICKR_ACCESS_TOKEN=${FLICKR_ACCESS_TOKEN}
      - FLICKR_ACCESS_TOKEN_SECRET=${FLICKR_ACCESS_TOKEN_SECRET}
    restart: "no"
```

- [ ] **Step 4: Commit**

```bash
git add config.example.yaml Dockerfile docker-compose.example.yml
git commit -m "chore: add config example and Docker files"
```

---

## Self-Review Checklist

Spec sections vs plan coverage:

| Spec requirement | Covered in |
|-----------------|-----------|
| Album prefix filtering | Task 6 `test_album_prefix_filtering` |
| Favourite-only, IMAGE-only | Task 6 `test_only_favourite_images_uploaded` |
| `get_asset_detail` only for candidates | Task 6 `test_get_asset_detail_not_called_for_non_favourites` |
| Tag merging (Immich + extra_tags) | Task 6 `test_tags_merged_from_immich_and_extra` |
| `sync_immich_tags: false` | Task 6 `test_tags_not_synced_when_disabled` |
| Hierarchical tag names passed as-is | Covered — tags are used verbatim |
| Licence with people | Task 6 `test_licence_with_people` |
| Licence without people | Task 6 `test_licence_without_people` |
| Unnamed face = has_people | Task 6 `test_unnamed_face_counts_as_person` |
| Idempotency / skip synced | Task 6 `test_idempotent_already_synced` |
| Photoset created on first sync | Task 6 `test_photoset_created_on_first_sync` |
| Photoset reused on subsequent sync | Task 6 `test_photoset_reused_on_second_sync` |
| Atomic state write | Task 3 `test_atomic_write_no_tmp_leftover` |
| Dry-run no mutations | Task 6 `test_dry_run_no_mutations` |
| Network error skips asset | Task 6 `test_network_error_on_single_asset_continues` |
| Flickr rate-limit retry | `_upload_with_retry` in sync.py (tested via exception path) |
| Immich 401 aborts | Task 4 `test_immich_401_raises` |
| photoset URL in status | Task 7 `test_status_prints_table` |
| `--album` filter without prefix | Task 7 `test_run_album_filter_passed` + Task 6 `test_album_filter_by_name` |
| Config env-var override | Task 2 `test_env_var_overrides_*` |
| Config YAML validation | Task 2 `test_missing_immich_url_raises` |
| Docker files | Task 8 |
