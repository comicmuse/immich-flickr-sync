# Agent Instructions — immich-flickr-sync

## What this project is

A Python CLI (`immich-flickr-sync`) that syncs favourited photos from prefixed Immich albums to Flickr photosets. It runs as a one-shot command via cron or systemd timer.

## Running tests

```bash
pytest
```

The `.venv` is pre-created. Tests use `responses` to mock Immich HTTP calls and `unittest.mock` for `flickrapi`. No external services needed.

## Architecture

| Module | Responsibility |
|--------|---------------|
| `cli.py` | click entry point — `auth`, `run`, `status`, `validate` subcommands |
| `config.py` | YAML loading, env-var overrides, dataclasses |
| `immich.py` | Immich REST API client (`requests`, `x-api-key` header) |
| `flickr.py` | Flickr API wrapper (`flickrapi`, OAuth1) |
| `state.py` | JSON state file with atomic writes (`os.replace`) |
| `sync.py` | Core sync loop — wires the above together |

## Key invariants

**Never break these:**

- `PermissionError` (from Immich 401/403) must propagate out of `run_sync` immediately — it must not be caught by the per-asset `except Exception` handler. The `except PermissionError: raise` guard in `sync.py` is load-bearing.
- State writes are atomic: always write to a `.tmp` file then `os.replace`. Never write directly to the state file.
- Idempotency: `state.is_synced()` is checked before any API call or download. Already-synced assets are skipped with no side effects.
- The Flickr upload endpoint always returns XML regardless of the global `format='parsed-json'` setting — `upload()` must pass `format='etree'` explicitly.
- Multi-word Flickr tags must be double-quoted (e.g. `"New York"`) — the upload API splits on spaces.
- Local storage mode: when `immich.storage_path` is set and the file exists, `download_asset()` returns the original path directly — the caller must NOT delete it. The caller detects this by checking `file_path == tmp_file`.

## Test approach

- TDD: write failing tests first, then implement.
- Immich HTTP: mock with `responses` library (`@responses.activate`).
- `flickrapi`: mock with `unittest.mock.patch("immich_flickr_sync.flickr.flickrapi.FlickrAPI")`.
- No integration tests — all tests are unit tests against mocks.
- `conftest.py` provides `tmp_state` (Path) and `tmp_config_path` (Path to a written YAML config).

## Flickr licence IDs

0=All Rights Reserved, 1=CC BY-NC-SA, 2=CC BY-NC, 3=CC BY-NC-ND, 4=CC BY, 5=CC BY-SA, 6=CC BY-ND, 10=CC0.

## Face detection rule

`has_people = len(asset.people) > 0` — unnamed/unrecognised faces still count. Do not use `any(p.name for p in people)`.

## What's out of scope (v1)

- Video upload
- Bi-directional sync
- Removing photos when un-favourited in Immich
- Re-licensing when a face is later identified
