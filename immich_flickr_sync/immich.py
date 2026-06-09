from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import requests


@dataclass
class Tag:
    id: str
    name: str


@dataclass
class Person:
    id: str
    name: str


@dataclass
class Asset:
    id: str
    originalFileName: str
    originalPath: str
    isFavorite: bool
    type: str
    fileCreatedAt: str
    exifInfo: dict | None
    tags: list[Tag] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)


@dataclass
class Album:
    id: str
    albumName: str
    assetCount: int
    updatedAt: str


def _parse_asset(raw: dict) -> Asset:
    return Asset(
        id=raw["id"],
        originalFileName=raw["originalFileName"],
        originalPath=raw.get("originalPath", ""),
        isFavorite=raw["isFavorite"],
        type=raw["type"],
        fileCreatedAt=raw["fileCreatedAt"],
        exifInfo=raw.get("exifInfo"),
        tags=[Tag(id=t["id"], name=t["name"]) for t in raw.get("tags", [])],
        people=[Person(id=p["id"], name=p.get("name", "")) for p in raw.get("people", [])],
    )


class ImmichClient:
    def __init__(self, base_url: str, api_key: str, storage_path: str | None = None):
        self._base = base_url.rstrip("/") + "/api"
        self._storage_path = storage_path
        self._session = requests.Session()
        self._session.headers["x-api-key"] = api_key

    def _get(self, path: str, **kwargs) -> requests.Response:
        resp = self._session.get(f"{self._base}{path}", **kwargs)
        if resp.status_code in (401, 403):
            raise PermissionError(f"Immich auth failed ({resp.status_code}): {path}")
        resp.raise_for_status()
        return resp

    def get_albums(self) -> list[Album]:
        data = self._get("/albums").json()
        return [
            Album(
                id=a["id"],
                albumName=a["albumName"],
                assetCount=a["assetCount"],
                updatedAt=a["updatedAt"],
            )
            for a in data
        ]

    def get_album_assets(self, album_id: str) -> list[Asset]:
        data = self._get(f"/albums/{album_id}").json()
        return [_parse_asset(a) for a in data.get("assets", [])]

    def get_asset_detail(self, asset_id: str) -> Asset:
        data = self._get(f"/assets/{asset_id}").json()
        return _parse_asset(data)

    def download_asset(self, asset: Asset, dest_path: Path) -> Path:
        """Returns path to the file. If local storage is used, returns the original
        path (caller must NOT delete). If API download, returns dest_path (caller
        should delete after upload)."""
        if self._storage_path and asset.originalPath:
            local = Path(self._storage_path) / asset.originalPath
            if local.exists():
                return local

        with self._session.get(
            f"{self._base}/assets/{asset.id}/original", stream=True
        ) as resp:
            if resp.status_code in (401, 403):
                raise PermissionError(f"Immich auth failed on download: {asset.id}")
            resp.raise_for_status()
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
        return dest_path
