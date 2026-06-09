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


def _make_asset(id="asset-1", filename="IMG_001.jpg", original_path="upload/IMG_001.jpg"):
    from immich_flickr_sync.immich import Asset
    return Asset(
        id=id, originalFileName=filename, originalPath=original_path,
        isFavorite=True, type="IMAGE", fileCreatedAt="2026-03-01T12:00:00Z",
        exifInfo=None,
    )


@rsps_lib.activate
def test_download_asset_api_mode(tmp_path):
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/assets/asset-1/original",
        body=b"fake-image-bytes",
        stream=True,
    )
    client = ImmichClient(base_url="http://immich.example.com", api_key="key")
    dest = tmp_path / "asset-1.jpg"
    asset = _make_asset()
    result = client.download_asset(asset, dest)
    assert result == dest  # returned temp path — caller should clean up
    assert dest.read_bytes() == b"fake-image-bytes"


def test_download_asset_local_storage_mode(tmp_path):
    original = tmp_path / "upload" / "IMG_001.jpg"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"real-image-bytes")

    client = ImmichClient(
        base_url="http://immich.example.com",
        api_key="key",
        storage_path=str(tmp_path),
    )
    dest = tmp_path / "tmp" / "asset-1.jpg"
    asset = _make_asset(original_path="upload/IMG_001.jpg")
    result = client.download_asset(asset, dest)
    assert result == original  # returned original path — caller must NOT delete
    assert not dest.exists()   # no download occurred


@rsps_lib.activate
def test_download_asset_local_storage_falls_back_when_missing(tmp_path):
    rsps_lib.add(
        rsps_lib.GET,
        f"{BASE}/assets/asset-1/original",
        body=b"api-bytes",
        stream=True,
    )
    client = ImmichClient(
        base_url="http://immich.example.com",
        api_key="key",
        storage_path=str(tmp_path / "nonexistent"),
    )
    dest = tmp_path / "asset-1.jpg"
    asset = _make_asset()
    result = client.download_asset(asset, dest)
    assert result == dest
    assert dest.read_bytes() == b"api-bytes"


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
