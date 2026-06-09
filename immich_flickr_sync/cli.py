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
            f"{config.immich.url.rstrip('/')}/api/users/me",
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
        from flickrapi.auth import FlickrAccessToken
        import flickrapi
        token = FlickrAccessToken(
            config.flickr.access_token,
            config.flickr.access_token_secret,
            "write",
        )
        api = flickrapi.FlickrAPI(
            config.flickr.api_key,
            config.flickr.api_secret,
            token=token,
            store_token=False,
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

    immich = ImmichClient(
        base_url=config.immich.url,
        api_key=config.immich.api_key,
        storage_path=config.immich.storage_path,
    )
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
