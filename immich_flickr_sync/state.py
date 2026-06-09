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
