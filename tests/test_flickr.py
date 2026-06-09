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
    assert call_kwargs["format"] == "etree"


def test_upload_photo_quotes_multi_word_tags(tmp_path):
    client, mock_api = make_client()
    mock_api.upload.return_value = MagicMock(
        find=lambda tag: MagicMock(text="photo-id")
    )
    img = tmp_path / "photo.jpg"
    img.write_bytes(b"img")
    client.upload_photo(
        file_path=img,
        title="T",
        tags=["New York", "simple"],
        date_taken="2026-01-01T00:00:00Z",
    )
    call_kwargs = mock_api.upload.call_args[1]
    assert '"New York"' in call_kwargs["tags"]
    assert "simple" in call_kwargs["tags"]


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
    mock_api.test.login.return_value = {
        "user": {"id": "12345678@N00", "username": {"_content": "testuser"}}
    }
    nsid = client.get_user_nsid()
    assert nsid == "12345678@N00"
