# immich-flickr-sync

Syncs favourited photos from prefixed [Immich](https://immich.app) albums to matching [Flickr](https://flickr.com) photosets. Designed to run as a cron job or systemd timer on a self-hosted server.

## How it works

- Albums in Immich whose names start with a configured prefix (default `[F]`) are synced to Flickr
- Only photos marked as **Favourite** in Immich are uploaded — Flickr becomes a curated "best of" collection
- Immich photo tags are replicated to Flickr tags
- Flickr licence is set automatically based on face detection: photos with detected faces get a restrictive licence (All Rights Reserved by default), photos without get a Creative Commons licence
- Runs are idempotent — re-running never creates duplicates

## Prerequisites

- Python 3.11+
- A running Immich instance with an API key
- A Flickr account with an API app (create one at [flickr.com/services/apps/create](https://www.flickr.com/services/apps/create))

## Installation

```bash
git clone git@github.com:comicmuse/immich-flickr-sync.git
cd immich-flickr-sync
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Quick start

**1. Get Flickr OAuth tokens:**

```bash
immich-flickr-sync auth --api-key YOUR_FLICKR_KEY --api-secret YOUR_FLICKR_SECRET
```

Follow the prompts — it prints your `access_token` and `access_token_secret` to stdout.

**2. Create your config:**

```bash
cp config.example.yaml config.yaml
# edit config.yaml
```

**3. Validate the config:**

```bash
immich-flickr-sync validate --config config.yaml
```

**4. Tag albums for sync:**

In Immich, rename any album to start with `[F]` (e.g. `[F] Basque Country 2026`). Mark your best photos in that album as Favourites.

**5. Dry run, then sync:**

```bash
immich-flickr-sync run --config config.yaml --dry-run
immich-flickr-sync run --config config.yaml
```

**6. Check status:**

```bash
immich-flickr-sync status --config config.yaml
```

## Configuration

See [`config.example.yaml`](config.example.yaml) for a full annotated example. All secrets can be supplied as environment variables instead of in the file — env vars take precedence.

| Env var | Config key |
|---------|-----------|
| `IMMICH_API_KEY` | `immich.api_key` |
| `FLICKR_API_KEY` | `flickr.api_key` |
| `FLICKR_API_SECRET` | `flickr.api_secret` |
| `FLICKR_ACCESS_TOKEN` | `flickr.access_token` |
| `FLICKR_ACCESS_TOKEN_SECRET` | `flickr.access_token_secret` |

### Local storage mode

If the sync script runs on the same host as Immich (or has the Immich upload volume mounted), set `immich.storage_path` to the upload directory path. Photos are then read directly from disk — zero download traffic.

```yaml
immich:
  storage_path: "/var/lib/immich/upload"
```

### Flickr licence IDs

| ID | Licence |
|----|---------|
| 0 | All Rights Reserved |
| 1 | CC BY-NC-SA |
| 2 | CC BY-NC |
| 3 | CC BY-NC-ND |
| 4 | CC BY |
| 5 | CC BY-SA |
| 6 | CC BY-ND |
| 10 | CC0 |

## CLI reference

```
immich-flickr-sync auth --api-key KEY --api-secret SECRET
    Run the Flickr OAuth PIN flow. Prints tokens to stdout.

immich-flickr-sync run [--config PATH] [--dry-run] [--album NAME]
    Sync all prefixed albums. --album restricts to a single album
    (without the prefix, e.g. --album "Basque Country 2026").

immich-flickr-sync status [--config PATH]
    Print a summary table with Flickr photoset URLs.

immich-flickr-sync validate [--config PATH]
    Check config, connectivity, and credentials. Exits 0 if all pass.
```

## Docker

```bash
docker build -t immich-flickr-sync .
docker run --rm \
  -v ./data:/app/data \
  -e IMMICH_API_KEY=... \
  -e FLICKR_API_KEY=... \
  -e FLICKR_API_SECRET=... \
  -e FLICKR_ACCESS_TOKEN=... \
  -e FLICKR_ACCESS_TOKEN_SECRET=... \
  immich-flickr-sync
```

See [`docker-compose.example.yml`](docker-compose.example.yml) for a compose setup.

## Systemd timer (homelab)

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

```bash
systemctl enable --now immich-flickr-sync.timer
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests use `responses` to mock Immich HTTP calls and `unittest.mock` for the `flickrapi` library. 53 tests, no external dependencies needed.
