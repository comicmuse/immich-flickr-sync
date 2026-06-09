from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
import yaml


@dataclass
class ImmichConfig:
    url: str
    api_key: str
    storage_path: str | None = None


@dataclass
class FlickrConfig:
    api_key: str
    api_secret: str
    access_token: str = ""
    access_token_secret: str = ""


@dataclass
class TagsConfig:
    sync_immich_tags: bool = True
    extra_tags: list[str] = field(default_factory=list)


@dataclass
class LicensingConfig:
    licence_with_people: int = 0
    licence_without_people: int = 3


@dataclass
class SyncConfig:
    album_prefix: str = "[F]"
    state_file: str = "state.json"
    tmp_dir: str = "/tmp/immich-flickr"
    flickr_photoset_prefix: str = ""
    tags: TagsConfig = field(default_factory=TagsConfig)
    licensing: LicensingConfig = field(default_factory=LicensingConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "text"


@dataclass
class Config:
    immich: ImmichConfig
    flickr: FlickrConfig
    sync: SyncConfig = field(default_factory=SyncConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: Path) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f) or {}

    immich_raw = data.get("immich", {})
    if v := os.environ.get("IMMICH_API_KEY"):
        immich_raw["api_key"] = v

    flickr_raw = data.get("flickr", {})
    for env, key in [
        ("FLICKR_API_KEY", "api_key"),
        ("FLICKR_API_SECRET", "api_secret"),
        ("FLICKR_ACCESS_TOKEN", "access_token"),
        ("FLICKR_ACCESS_TOKEN_SECRET", "access_token_secret"),
    ]:
        if v := os.environ.get(env):
            flickr_raw[key] = v

    immich = ImmichConfig(
        url=immich_raw["url"],
        api_key=immich_raw["api_key"],
        storage_path=immich_raw.get("storage_path"),
    )
    flickr = FlickrConfig(
        api_key=flickr_raw["api_key"],
        api_secret=flickr_raw["api_secret"],
        access_token=flickr_raw.get("access_token", ""),
        access_token_secret=flickr_raw.get("access_token_secret", ""),
    )

    sync_raw = data.get("sync", {})
    tags_raw = sync_raw.get("tags", {})
    lic_raw = sync_raw.get("licensing", {})
    sync = SyncConfig(
        album_prefix=sync_raw.get("album_prefix", "[F]"),
        state_file=sync_raw.get("state_file", "state.json"),
        tmp_dir=sync_raw.get("tmp_dir", "/tmp/immich-flickr"),
        flickr_photoset_prefix=sync_raw.get("flickr_photoset_prefix", ""),
        tags=TagsConfig(
            sync_immich_tags=tags_raw.get("sync_immich_tags", True),
            extra_tags=tags_raw.get("extra_tags", []),
        ),
        licensing=LicensingConfig(
            licence_with_people=lic_raw.get("licence_with_people", 0),
            licence_without_people=lic_raw.get("licence_without_people", 3),
        ),
    )

    log_raw = data.get("logging", {})
    logging = LoggingConfig(
        level=log_raw.get("level", "INFO"),
        format=log_raw.get("format", "text"),
    )

    return Config(immich=immich, flickr=flickr, sync=sync, logging=logging)
