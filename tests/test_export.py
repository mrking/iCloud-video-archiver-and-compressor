"""Tests for archive_videos.export module."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from archive_videos.discover import VideoAsset
from archive_videos.export import export_original, write_sidecar

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_asset() -> VideoAsset:
    return VideoAsset(
        uuid="11111111-1111-1111-1111-111111111111",
        filename="IMG_0001.mov",
        path=Path("/fake/photos/IMG_0001.mov"),
        duration=120.5,
        codec="hvc1",
        bitrate_mbps=45.0,
        width=3840,
        height=2160,
        date="2024-07-15T10:30:00+00:00",
        title="Vacation Video",
        keywords=["holiday", "family"],
        albums=["Summer 2024"],
        favorite=True,
        location=(37.7749, -122.4194),
    )


@pytest.fixture
def asset_no_location() -> VideoAsset:
    return VideoAsset(
        uuid="22222222-2222-2222-2222-222222222222",
        filename="IMG_0002.mov",
        path=None,
        duration=60.0,
        codec="avc1",
        bitrate_mbps=20.0,
        width=1920,
        height=1080,
        date=None,
        title=None,
        keywords=[],
        albums=[],
        favorite=False,
        location=None,
    )


# ── write_sidecar tests ──────────────────────────────────────────────────────

def test_write_sidecar_creates_file(sample_asset: VideoAsset, tmp_path: Path) -> None:
    sidecar = tmp_path / "sidecars" / "11111111.json"
    result = write_sidecar(sample_asset, sidecar)
    assert result == sidecar
    assert sidecar.exists()
    assert sidecar.read_text(encoding="utf-8")  # not empty


def test_write_sidecar_json_structure(sample_asset: VideoAsset, tmp_path: Path) -> None:
    sidecar = tmp_path / "11111111.json"
    write_sidecar(sample_asset, sidecar)

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["uuid"] == "11111111-1111-1111-1111-111111111111"
    assert payload["filename"] == "IMG_0001.mov"
    assert payload["date"] == "2024-07-15T10:30:00+00:00"
    assert payload["title"] == "Vacation Video"
    assert payload["keywords"] == ["holiday", "family"]
    assert payload["albums"] == ["Summer 2024"]
    assert payload["favorite"] is True
    assert payload["location"] == [37.7749, -122.4194]
    assert payload["duration"] == 120.5
    assert payload["codec"] == "hvc1"
    assert payload["width"] == 3840
    assert payload["height"] == 2160
    assert payload["bitrate_mbps"] == 45.0


def test_write_sidecar_no_location(asset_no_location: VideoAsset, tmp_path: Path) -> None:
    sidecar = tmp_path / "22222222.json"
    write_sidecar(asset_no_location, sidecar)

    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["uuid"] == "22222222-2222-2222-2222-222222222222"
    assert payload["location"] is None
    assert payload["title"] is None
    assert payload["keywords"] == []


def test_write_sidecar_creates_parent_dirs(sample_asset: VideoAsset, tmp_path: Path) -> None:
    """Parent directory of sidecar path should be created automatically."""
    sidecar = tmp_path / "deep" / "nested" / "path" / "11111111.json"
    write_sidecar(sample_asset, sidecar)
    assert sidecar.exists()
    assert json.loads(sidecar.read_text(encoding="utf-8"))["uuid"] == \
        "11111111-1111-1111-1111-111111111111"


# ── export_original dry-run tests ─────────────────────────────────────────────

def test_export_original_dry_run_creates_placeholder(sample_asset: VideoAsset, tmp_path: Path) -> None:
    dest_dir = tmp_path / "exports"
    result = export_original(sample_asset, dest_dir, dry_run=True)

    assert result == dest_dir / "IMG_0001.mov"
    assert result.exists()
    assert result.read_text() == "DRY_RUN_PLACEHOLDER"


def test_export_original_dry_run_does_not_call_photosdb(sample_asset: VideoAsset, tmp_path: Path) -> None:
    """Dry-run should not instantiate or call PhotosDB."""
    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB") as mock_db_cls:
        export_original(sample_asset, dest_dir, dry_run=True)
        mock_db_cls.assert_not_called()


def test_export_original_dry_run_creates_dest_dir(sample_asset: VideoAsset, tmp_path: Path) -> None:
    """dest_dir should be created even if it does not exist."""
    dest_dir = tmp_path / "does_not_exist" / "exports"
    result = export_original(sample_asset, dest_dir, dry_run=True)
    assert dest_dir.exists()
    assert result.exists()


# ── export_original execute path tests ───────────────────────────────────────

def _make_mock_photo(asset: VideoAsset) -> MagicMock:
    mock_photo = MagicMock()
    mock_photo.uuid = asset.uuid
    mock_photo.filename = asset.filename
    # .export() returns a string path or list of paths
    exported_name = f"exported_{asset.filename}"
    mock_photo.export.return_value = exported_name
    return mock_photo


def test_export_original_execute_calls_photosdb(sample_asset: VideoAsset, tmp_path: Path) -> None:
    mock_photo = _make_mock_photo(sample_asset)
    mock_db = MagicMock()
    mock_db.get_photo.return_value = mock_photo

    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB", return_value=mock_db):
        result = export_original(sample_asset, dest_dir, dry_run=False, db=mock_db)

    mock_db.get_photo.assert_called_once_with(sample_asset.uuid)
    assert result.name == f"exported_{sample_asset.filename}"


def test_export_original_execute_calls_export_on_photo(sample_asset: VideoAsset, tmp_path: Path) -> None:
    mock_photo = _make_mock_photo(sample_asset)
    mock_db = MagicMock()
    mock_db.get_photo.return_value = mock_photo

    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB", return_value=mock_db):
        export_original(sample_asset, dest_dir, dry_run=False, db=mock_db)

    mock_photo.export.assert_called_once_with(str(dest_dir), overwrite=True)


def test_export_original_execute_returns_path(sample_asset: VideoAsset, tmp_path: Path) -> None:
    mock_photo = _make_mock_photo(sample_asset)
    mock_db = MagicMock()
    mock_db.get_photo.return_value = mock_photo

    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB", return_value=mock_db):
        result = export_original(sample_asset, dest_dir, dry_run=False, db=mock_db)

    assert isinstance(result, Path)
    assert result.name == f"exported_{sample_asset.filename}"


def test_export_original_execute_list_response(sample_asset: VideoAsset, tmp_path: Path) -> None:
    """Export may return a list; function should handle the first item."""
    mock_photo = MagicMock()
    mock_photo.uuid = sample_asset.uuid
    mock_photo.filename = sample_asset.filename
    mock_photo.export.return_value = [f"exported_{sample_asset.filename}"]

    mock_db = MagicMock()
    mock_db.get_photo.return_value = mock_photo

    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB", return_value=mock_db):
        result = export_original(sample_asset, dest_dir, dry_run=False, db=mock_db)

    assert isinstance(result, Path)
    assert result.name == f"exported_{sample_asset.filename}"


def test_export_original_execute_photo_not_found(sample_asset: VideoAsset, tmp_path: Path) -> None:
    """Photo not found in library should raise FileNotFoundError."""
    mock_db = MagicMock()
    mock_db.get_photo.return_value = None

    dest_dir = tmp_path / "exports"
    with patch("archive_videos.export.osxphotos.PhotosDB", return_value=mock_db):
        with pytest.raises(FileNotFoundError, match=sample_asset.uuid):
            export_original(sample_asset, dest_dir, dry_run=False, db=mock_db)
