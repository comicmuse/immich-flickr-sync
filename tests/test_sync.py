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
        originalPath="",
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
    immich.get_album_assets.return_value = [make_asset()]

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
