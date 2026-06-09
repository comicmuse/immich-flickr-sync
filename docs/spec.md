# immich-flickr-sync — Full Specification

## Overview

A Python daemon/script that monitors Immich albums whose names begin with a
configured prefix and synchronises their favourited assets to matching Flickr
photosets. Designed to run as a cron job or systemd timer on a self-hosted
Linux server (Docker-capable).

---

## Goals

- Zero manual steps after initial setup: rename an Immich album → next run
  syncs it.
- Only upload photos the user has marked as **Favourite** in Immich, keeping
  Flickr as a curated "best of" collection.
- Replicate Immich photo-level tags to Flickr tags automatically.
- Automatically set Flickr licence based on whether Immich has detected faces
  in the photo.
- Idempotent: re-running never creates duplicates.
- Self-contained: single Python package, no external databases, state stored
  in a local JSON file.
- Observable: structured logging, dry-run mode, clear error messages.

---

## Repository Layout

```
immich-flickr-sync/
├── immich_flickr_sync/
│   ├── __init__.py
│   ├── cli.py            # Entry point, click-based CLI
│   ├── config.py         # Config loading and validation
│   ├── immich.py         # Immich API client
│   ├── flickr.py         # Flickr API client
│   ├── state.py          # Persistent state (JSON)
│   └── sync.py           # Core sync logic
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_config.py
│   ├── test_immich.py
│   ├── test_flickr.py
│   ├── test_sync.py
│   └── test_state.py
├── docs/
│   └── spec.md
├── config.example.yaml
├── Dockerfile
├── docker-compose.example.yml
├── pyproject.toml
└── README.md
```

---

## Configuration

Loaded from a YAML file (default path: `config.yaml` in the working
directory, overridable via `--config` flag or `IMMICH_FLICKR_CONFIG` env var).
All secrets can alternatively be supplied as environment variables (env var
takes precedence over file value).

```yaml
immich:
  url: "http://192.168.1.154:2283"   # Base URL of Immich instance
  api_key: "YOUR_IMMICH_API_KEY"     # Env: IMMICH_API_KEY
  storage_path: null                 # Optional: absolute path to Immich's upload storage
                                     # directory on the local filesystem. When set, originals
                                     # are read directly from disk (zero download traffic).
                                     # Only usable when the sync script runs on the same
                                     # host as Immich or has the storage volume mounted.

flickr:
  api_key: "YOUR_FLICKR_API_KEY"         # Env: FLICKR_API_KEY
  api_secret: "YOUR_FLICKR_API_SECRET"   # Env: FLICKR_API_SECRET
  # OAuth access tokens — obtained via `immich-flickr-sync auth`
  access_token: "YOUR_ACCESS_TOKEN"          # Env: FLICKR_ACCESS_TOKEN
  access_token_secret: "YOUR_ACCESS_TOKEN_SECRET"  # Env: FLICKR_ACCESS_TOKEN_SECRET

sync:
  album_prefix: "[F]"          # Albums whose names start with this are synced
                                # e.g. "[F] Basque Country 2026"
  state_file: "state.json"     # Path to persistent state file
  tmp_dir: "/tmp/immich-flickr" # Scratch space for downloaded originals
  flickr_photoset_prefix: ""   # Optional prefix added to Flickr photoset names
                                # (leave empty to mirror Immich album name exactly)
  tags:
    sync_immich_tags: true      # Replicate Immich photo tags to Flickr tags
    extra_tags: ["immich-sync"] # Additional tags always added to every upload
  licensing:
    # Flickr licence IDs:
    #   0 = All Rights Reserved
    #   1 = CC BY-NC-SA  2 = CC BY-NC  3 = CC BY-NC-ND
    #   4 = CC BY        5 = CC BY-SA  6 = CC BY-ND
    #   7 = No known copyright  9 = Public Domain  10 = CC0
    licence_with_people: 0      # All Rights Reserved when faces detected
    licence_without_people: 3   # CC BY-NC-ND when no faces detected

logging:
  level: "INFO"                 # DEBUG | INFO | WARNING | ERROR
  format: "text"                # text | json
```

### Config validation

On startup, validate:
- `immich.url` is reachable (HTTP GET `/api/server/about`, expect 200)
- `immich.api_key` authenticates successfully
- Flickr OAuth tokens are valid (`flickr.auth.checkToken`)
- `sync.tmp_dir` is writable
- `sync.state_file` parent directory is writable

Exit with a clear error message if any check fails.

---

## Immich API Client (`immich.py`)

Base URL: `{immich.url}/api`  
Auth header: `x-api-key: {immich.api_key}`

### Methods required

```python
def get_albums() -> list[Album]
```
`GET /albums` — returns all albums.

```python
def get_album_assets(album_id: str) -> list[Asset]
```
`GET /albums/{id}` — returns full album including asset list.

```python
def download_asset(asset: Asset, dest_path: Path) -> Path
```
Returns a `Path` to the original file using one of two strategies:

- **Local storage mode** (when `immich.storage_path` is configured): resolves
  `Path(storage_path) / asset.originalPath` and returns it directly — no
  network traffic, no copy. Falls back to API download if the file is not
  found at that path.
- **API download mode** (default): `GET /assets/{id}/original` — streams the
  original in chunks to `dest_path` and returns `dest_path`.

The caller (sync loop) checks whether the returned path equals `dest_path`; if
not, it is a local original and must **not** be deleted after upload.

### Data models

```python
@dataclass
class Album:
    id: str
    albumName: str
    assetCount: int
    updatedAt: str   # ISO 8601

@dataclass
class Tag:
    id: str
    name: str       # may be hierarchical, e.g. "travel/europe"

@dataclass
class Person:
    id: str
    name: str       # may be empty string if face is unrecognised

@dataclass
class Asset:
    id: str
    originalFileName: str
    originalPath: str      # relative path within Immich storage, e.g. "upload/.../IMG_001.jpg"
    isFavorite: bool
    type: str              # "IMAGE" | "VIDEO"
    fileCreatedAt: str     # ISO 8601 — use as Flickr date_taken
    exifInfo: dict | None
    tags: list[Tag]        # photo-level tags; NOT present in getAlbumInfo response
    people: list[Person]   # detected faces; NOT present in getAlbumInfo response
```

### API call strategy for tags and people

**Important:** The `getAlbumInfo` endpoint (`GET /albums/{id}`) does not return
`tags` or `people` fields on asset objects — this is a known upstream limitation.
To obtain them, the script must call `GET /assets/{id}` individually for each
asset it intends to upload.

To avoid N+1 overhead on albums with many favourites, fetch individual asset
details only for assets that pass the favourite + type filter, not for all
album assets.

```python
def get_asset_detail(asset_id: str) -> Asset
```
`GET /assets/{id}` — returns full asset including `tags` and `people`.

### Filtering

After fetching album assets via `getAlbumInfo`, filter to only those where
`isFavorite == True` and `type == "IMAGE"`. Then call `get_asset_detail` for
each surviving asset to retrieve tags and people. Video upload to Flickr is
out of scope for v1.

---

## Flickr API Client (`flickr.py`)

Use the `flickrapi` library (OAuth1). All calls use `format='parsed-json'`.

### Authentication flow (`auth` subcommand)

Implement the standard Flickr OAuth PIN flow:

1. Request a request token
2. Print the authorisation URL to stdout and prompt the user to visit it
3. Prompt for the PIN
4. Exchange for access token + secret
5. **Print the tokens to stdout for manual entry into config** — the auth
   subcommand does not write to the config file

### Methods required

```python
def get_photosets() -> list[Photoset]
```
`flickr.photosets.getList` — fetch all photosets for the authenticated user.

```python
def create_photoset(title: str, primary_photo_id: str) -> Photoset
```
`flickr.photosets.create` — creates a new photoset. The first photo uploaded
must be passed as `primary_photo_id`.

```python
def add_photo_to_photoset(photoset_id: str, photo_id: str) -> None
```
`flickr.photosets.addPhoto`

```python
def upload_photo(
    file_path: Path,
    title: str,
    tags: list[str],
    date_taken: str,
    is_public: bool = False,
) -> str   # returns Flickr photo ID
```
Use `flickrapi`'s `upload()` method. Set `is_public=0`, `is_friend=0`,
`is_family=0` by default (private until explicitly shared).

After upload, set the licence separately via `flickr.photos.licenses.setLicense`
(the upload API does not accept a licence parameter directly).

```python
def set_licence(photo_id: str, licence_id: int) -> None
```
`flickr.photos.licenses.setLicense` — called immediately after upload.

```python
def get_photos_in_photoset(photoset_id: str) -> list[str]
```
`flickr.photosets.getPhotos` — returns list of Flickr photo IDs.

```python
def get_user_nsid() -> str
```
`flickr.auth.checkToken` — returns the authenticated user's NSID (e.g.
`"12345678@N00"`). Used by the `status` subcommand to construct photoset
URLs of the form `https://www.flickr.com/photos/{nsid}/sets/{photoset_id}/`.

### Data models

```python
@dataclass
class Photoset:
    id: str
    title: str
```

---

## State Management (`state.py`)

A single JSON file tracking what has already been synced, to ensure
idempotency across runs.

### Schema

```json
{
  "version": 1,
  "albums": {
    "<immich_album_id>": {
      "flickr_photoset_id": "<flickr_photoset_id>",
      "synced_assets": {
        "<immich_asset_id>": {
          "flickr_photo_id": "<flickr_photo_id>",
          "synced_at": "2026-06-09T10:00:00Z",
          "licence_id": 0,
          "has_people": true
        }
      }
    }
  }
}
```

### Behaviour

- Load on startup; create with empty structure if not present.
- Write atomically (write to `.tmp` then `os.replace`) after each successful
  asset upload to avoid corruption on interrupt.
- Expose methods:
  - `is_synced(album_id, asset_id) -> bool`
  - `record_sync(album_id, asset_id, flickr_photo_id, licence_id, has_people)`
  - `get_photoset_id(album_id) -> str | None`
  - `set_photoset_id(album_id, photoset_id)`

---

## Core Sync Logic (`sync.py`)

```
for each Immich album where albumName.startswith(album_prefix):
    flickr_title = albumName.removeprefix(album_prefix).strip()
    if flickr_photoset_prefix:
        flickr_title = flickr_photoset_prefix + flickr_title

    get or create Flickr photoset with that title

    favourite_assets = [a for a in album.assets if a.isFavorite and a.type == "IMAGE"]

    for each asset in favourite_assets:
        if state.is_synced(album.id, asset.id):
            continue

        # Fetch full asset detail to get tags and people
        detail = immich.get_asset_detail(asset.id)

        # Build Flickr tags: Immich tags + configured extra_tags
        flickr_tags = config.sync.tags.extra_tags.copy()
        if config.sync.tags.sync_immich_tags:
            flickr_tags += [t.name for t in detail.tags]

        # Determine licence from face detection
        has_people = len(detail.people) > 0
        licence_id = (
            config.sync.licensing.licence_with_people
            if has_people
            else config.sync.licensing.licence_without_people
        )

        download original to tmp_dir / f"{asset.id}{ext}"
        upload to Flickr with:
            title      = asset.originalFileName (without extension)
            tags       = flickr_tags
            date_taken = asset.fileCreatedAt
            is_public  = False

        set_licence(flickr_photo_id, licence_id)
        add photo to photoset
        state.record_sync(album.id, asset.id, flickr_photo_id, licence_id, has_people)
        delete tmp file

    log summary: "Album '{name}': {n} uploaded, {m} already synced, {k} skipped (not favourite)"
    # For uploaded photos, log per-photo: filename, tags synced, licence applied
```

### Error handling

- Network errors on download/upload: log warning, skip asset, continue.
  Do not abort the whole run for a single asset failure.
- If Flickr rate-limits (HTTP 429 or error code 18): back off with
  exponential delay, retry up to 3 times.
- If Immich returns 401/403: abort immediately with clear message.
- If tmp file already exists (leftover from crashed run): overwrite.

---

## CLI (`cli.py`)

Built with **`click`**.

### Subcommands

```
immich-flickr-sync auth
```
Run the Flickr OAuth PIN flow. Prints the obtained access token and access
token secret to stdout. The user copies these into their config file manually.
Does not accept `--config` (tokens are not read from or written to any config
file during this step).

```
immich-flickr-sync run [--config PATH] [--dry-run] [--album ALBUM_NAME]
```
Main sync run.

- `--dry-run`: go through all logic, log what *would* be uploaded, but make
  no writes to Flickr or state file.
- `--album ALBUM_NAME`: restrict this run to a single album. The value is
  the album name **without** the configured prefix. For example,
  `--album "Basque Country 2026"` matches the Immich album named
  `[F] Basque Country 2026` (when `album_prefix = "[F]"`).

```
immich-flickr-sync status [--config PATH]
```
Print a summary table of all tracked albums: album name, photoset URL,
total assets, synced count, pending count. Photoset URLs are constructed as
`https://www.flickr.com/photos/{nsid}/sets/{photoset_id}/` where the NSID
is fetched once via `flickr.auth.checkToken`.

```
immich-flickr-sync validate [--config PATH]
```
Run the startup config checks and exit 0 if all pass, non-zero otherwise.

---

## Packaging (`pyproject.toml`)

```toml
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
```

---

## Docker

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
VOLUME ["/app/data"]
ENTRYPOINT ["immich-flickr-sync"]
CMD ["run", "--config", "/app/data/config.yaml"]
```

### docker-compose.example.yml

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
    restart: "no"    # run via cron/systemd timer, not as a long-running service
```

---

## Deployment (systemd timer on homelab)

```ini
# /etc/systemd/system/immich-flickr-sync.service
[Unit]
Description=Immich → Flickr sync

[Service]
Type=oneshot
User=colm
WorkingDirectory=/home/colm/immich-flickr-sync
ExecStart=/home/colm/immich-flickr-sync/.venv/bin/immich-flickr-sync run
EnvironmentFile=/home/colm/immich-flickr-sync/.env
```

```ini
# /etc/systemd/system/immich-flickr-sync.timer
[Unit]
Description=Run Immich → Flickr sync every 30 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
```

---

## Testing

- Use `pytest`.
- Mock all HTTP calls (Immich) with `responses` library; mock `flickrapi`
  with `unittest.mock`.
- Key test cases:
  - Album prefix filtering (matches, non-matches, edge cases like prefix with
    no trailing space)
  - Favourite-only filtering
  - Tags: Immich tags correctly merged with extra_tags; sync disabled when
    `sync_immich_tags: false`; hierarchical tag names passed as-is
  - Licensing: photo with people → `licence_with_people`; photo without →
    `licence_without_people`; `set_licence` called after every upload
  - Licensing: empty `people` list (unrecognised face not assigned to a person
    but face detected) — confirm API returns face entries even when unnamed;
    test that `len(people) > 0` is the correct signal regardless of name
  - `get_asset_detail` is called only for favourite IMAGE assets, not all
    album assets
  - Idempotency: asset already in state is skipped (no re-upload, no licence
    re-set)
  - Photoset creation on first sync vs reuse on subsequent sync
  - Atomic state write verified (tmp file renamed, not left behind)
  - Dry-run makes no mutations
  - Network error on single asset doesn't abort whole album
  - Retry logic on Flickr rate limit

---

## Known Limitations and Notes

### Download strategy

By default the sync script downloads each original from Immich via HTTP, writes
it to `tmp_dir`, uploads it to Flickr, then deletes the temp file. For a remote
Immich instance this means bytes travel Immich → sync host → Flickr, doubling
the external bandwidth cost.

When `immich.storage_path` is set the script reads originals directly from disk
instead, so only the Flickr upload consumes external bandwidth. This requires
the sync script to run on the same machine as Immich, or for the Immich upload
volume to be mounted at `storage_path`. The path is constructed as
`Path(storage_path) / asset.originalPath` using the relative path returned by
the `GET /assets/{id}` endpoint.

### Tags API caveat
The `getAlbumInfo` endpoint does not return tags on asset objects (upstream
issue #19108). The workaround of calling `GET /assets/{id}` per favourite
asset adds one extra API call per photo per first-sync run. On re-runs,
already-synced assets are skipped before the detail fetch, so the overhead is
bounded to new uploads only.

### Face detection vs named persons
Immich's `people` field on an asset includes detected faces whether or not they
have been named/assigned to a person. An unnamed face still appears as an entry
with an empty `name` field. The licensing rule therefore uses
`len(asset.people) > 0` (any detected face), not `any(p.name for p in people)`
(only named persons). This is intentional — an untagged face still means the
photo contains a person.

---

## Future / Out of Scope for v1

- Video upload to Flickr
- Bi-directional sync (Flickr → Immich)
- Removal: if a photo is un-favourited or removed from the album in Immich,
  optionally remove from Flickr
- Re-licensing: if a person is later identified in Immich and licence should
  change from CC to ARR, detect the delta and update via `set_licence`
- Flickr privacy levels per-album (currently hardcoded to private)
- Web UI or Home Assistant integration
