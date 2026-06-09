from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import flickrapi
from flickrapi.auth import FlickrAccessToken


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
        token = FlickrAccessToken(access_token, access_token_secret, "write")
        self._api = flickrapi.FlickrAPI(
            api_key, api_secret,
            token=token,
            store_token=False,
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

    @staticmethod
    def _format_tags(tags: list[str]) -> str:
        # Flickr's upload API splits on spaces; quote multi-word tags
        return " ".join(f'"{t}"' if " " in t else t for t in tags)

    def upload_photo(
        self,
        file_path: Path,
        title: str,
        tags: list[str],
        date_taken: str,
        is_public: bool = False,
    ) -> str:
        # Upload endpoint always returns XML regardless of global format setting
        resp = self._api.upload(
            filename=str(file_path),
            title=title,
            tags=self._format_tags(tags),
            date_taken=date_taken,
            is_public=1 if is_public else 0,
            is_friend=0,
            is_family=0,
            format="etree",
        )
        return resp.find("photoid").text

    def set_licence(self, photo_id: str, licence_id: int) -> None:
        self._api.photos.licenses.setLicense(photo_id=photo_id, license_id=licence_id)

    def get_photos_in_photoset(self, photoset_id: str) -> list[str]:
        resp = self._api.photosets.getPhotos(photoset_id=photoset_id)
        return [p["id"] for p in resp["photoset"].get("photo", [])]

    def get_user_nsid(self) -> str:
        resp = self._api.test.login()
        return resp["user"]["id"]
