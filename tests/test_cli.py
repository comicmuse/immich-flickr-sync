import json
import pytest
from click.testing import CliRunner
from unittest.mock import patch, MagicMock
from immich_flickr_sync.cli import main


def test_validate_passes(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config") as mock_val:
        mock_val.return_value = None
        result = runner.invoke(main, ["validate", "--config", str(tmp_config_path)])
    assert result.exit_code == 0


def test_validate_fails_on_bad_config(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("immich:\n  api_key: x\n")
    runner = CliRunner()
    result = runner.invoke(main, ["validate", "--config", str(bad)])
    assert result.exit_code != 0


def test_run_dry_run_calls_sync(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager"), \
         patch("immich_flickr_sync.cli.run_sync") as mock_sync:
        MockImmich.return_value = MagicMock()
        MockFlickr.return_value = MagicMock()
        result = runner.invoke(main, ["run", "--config", str(tmp_config_path), "--dry-run"])
    assert result.exit_code == 0
    mock_sync.assert_called_once()
    _, kwargs = mock_sync.call_args
    assert kwargs.get("dry_run") is True or mock_sync.call_args[0][5] is True


def test_run_album_filter_passed(tmp_config_path):
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager"), \
         patch("immich_flickr_sync.cli.run_sync") as mock_sync:
        MockImmich.return_value = MagicMock()
        MockFlickr.return_value = MagicMock()
        result = runner.invoke(main, [
            "run", "--config", str(tmp_config_path), "--album", "Paris"
        ])
    assert result.exit_code == 0
    args = mock_sync.call_args
    album_filter = args[1].get("album_filter") or args[0][6]
    assert album_filter == "Paris"


def test_status_prints_table(tmp_config_path, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "version": 1,
        "albums": {
            "a1": {
                "flickr_photoset_id": "ps-1",
                "synced_assets": {
                    "asset-1": {"flickr_photo_id": "fp-1", "synced_at": "2026-01-01T00:00:00Z",
                                "licence_id": 3, "has_people": False}
                }
            }
        }
    }))
    runner = CliRunner()
    with patch("immich_flickr_sync.cli.validate_config"), \
         patch("immich_flickr_sync.cli.ImmichClient") as MockImmich, \
         patch("immich_flickr_sync.cli.FlickrClient") as MockFlickr, \
         patch("immich_flickr_sync.cli.StateManager") as MockState:
        mock_immich = MagicMock()
        mock_flickr = MagicMock()
        MockImmich.return_value = mock_immich
        MockFlickr.return_value = mock_flickr
        mock_flickr.get_user_nsid.return_value = "12345@N00"

        from immich_flickr_sync.state import StateManager as RealState
        MockState.return_value = RealState(state_path)

        from immich_flickr_sync.immich import Album
        mock_immich.get_albums.return_value = [
            Album(id="a1", albumName="[F] Paris", assetCount=5, updatedAt="2026-01-01T00:00:00Z")
        ]
        mock_immich.get_album_assets.return_value = [MagicMock(isFavorite=True, type="IMAGE")] * 3

        result = runner.invoke(main, ["status", "--config", str(tmp_config_path)])
    assert result.exit_code == 0
    assert "Paris" in result.output
    assert "ps-1" in result.output or "12345@N00" in result.output
