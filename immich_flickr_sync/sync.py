from __future__ import annotations
import logging
import time
from pathlib import Path

from immich_flickr_sync.config import Config
from immich_flickr_sync.state import StateManager

log = logging.getLogger(__name__)

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

        for asset in candidates:
            if state.is_synced(album.id, asset.id):
                already_synced += 1
                continue

            try:
                detail = immich.get_asset_detail(asset.id)
            except PermissionError:
                raise
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
            file_path = tmp_file  # default; updated below if local storage is used

            try:
                file_path = immich.download_asset(detail, tmp_file)
                photo_id = _upload_with_retry(
                    flickr,
                    file_path=file_path,
                    title=_flickr_title(asset.originalFileName),
                    tags=flickr_tags,
                    date_taken=asset.fileCreatedAt,
                    is_public=config.sync.public,
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
            except PermissionError:
                raise
            except Exception as exc:
                log.warning("Failed to sync asset %s: %s", asset.id, exc)
            finally:
                # Only delete if we wrote a temp copy; local originals are not ours to remove
                if file_path == tmp_file and tmp_file.exists():
                    tmp_file.unlink()

        log.info(
            "Album '%s': %d uploaded, %d already synced, %d skipped (not favourite)",
            album.albumName, uploaded, already_synced, skipped,
        )
