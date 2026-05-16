"""Tests for archive_videos.reimport module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from archive_videos.discover import VideoAsset
from archive_videos.reimport import (
    delete_original,
    import_compressed,
    restore_metadata,
    reimport_asset,
)


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
        keywords=["holiday"],
        albums=["Summer 2024"],
        favorite=True,
        location=(37.7749, -122.4194),
    )


@pytest.fixture
def asset_no_date_no_albums() -> VideoAsset:
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


# ── delete_original tests ─────────────────────────────────────────────────────

@patch("archive_videos.reimport._osascript")
def test_delete_original_dry_run_logs_only(mock_osascript, sample_asset):
    delete_original(sample_asset, dry_run=True)
    mock_osascript.assert_not_called()


@patch("archive_videos.reimport._osascript")
def test_delete_original_exec_calls_osascript_with_uuid(mock_osascript, sample_asset):
    delete_original(sample_asset, dry_run=False)
    mock_osascript.assert_called_once()
    call_args = mock_osascript.call_args[0][0]
    assert sample_asset.uuid in call_args


# ── import_compressed tests ───────────────────────────────────────────────────

@patch("archive_videos.reimport._osascript")
def test_import_compressed_dry_run_logs_and_returns_none(mock_osascript, tmp_path):
    video = tmp_path / "compressed.mp4"
    video.write_bytes(b"compressed data")

    result = import_compressed(video, dry_run=True)

    assert result is None
    mock_osascript.assert_not_called()


def test_import_compressed_file_not_found():
    nonexistent = Path("/tmp/does_not_exist.mp4")

    with pytest.raises(FileNotFoundError):
        import_compressed(nonexistent, dry_run=False)


@patch("archive_videos.reimport._osascript")
def test_import_compressed_exec_calls_osascript(mock_osascript, tmp_path):
    video = tmp_path / "compressed.mp4"
    video.write_bytes(b"compressed data")
    mock_osascript.return_value = "new-uuid-from-photos"

    result = import_compressed(video, dry_run=False)

    assert result == "new-uuid-from-photos"
    mock_osascript.assert_called_once()
    call_args = mock_osascript.call_args[0][0]
    assert str(video) in call_args


# ── restore_metadata tests ─────────────────────────────────────────────────────

@patch("archive_videos.reimport._osascript")
def test_restore_metadata_dry_run_logs_only(mock_osascript, sample_asset):
    restore_metadata("new-uuid", sample_asset, dry_run=True)
    mock_osascript.assert_not_called()


@patch("archive_videos.reimport._osascript")
def test_restore_metadata_exec_sets_date_favorite_albums(mock_osascript, sample_asset):
    restore_metadata("new-uuid", sample_asset, dry_run=False)

    calls = [str(c[0][0]) for c in mock_osascript.call_args_list]
    joined = " ".join(calls)

    # Date
    assert any(sample_asset.date in c for c in calls)
    # Favorite (true since asset.favorite is True)
    assert any("true" in c for c in calls)
    # Album
    assert any("Summer 2024" in c for c in calls)


@patch("archive_videos.reimport._osascript")
def test_restore_metadata_no_date_no_albums_still_succeeds(mock_osascript, asset_no_date_no_albums):
    """No date / no albums should not call osascript (or fail silently)."""
    restore_metadata("new-uuid", asset_no_date_no_albums, dry_run=False)
    # Only favorite call
    assert mock_osascript.call_count == 1


@patch("archive_videos.reimport._osascript")
def test_restore_metadata_albums_multiple(mock_osascript, sample_asset):
    multi_album_asset = VideoAsset(
        uuid=sample_asset.uuid,
        filename=sample_asset.filename,
        path=sample_asset.path,
        duration=sample_asset.duration,
        codec=sample_asset.codec,
        bitrate_mbps=sample_asset.bitrate_mbps,
        width=sample_asset.width,
        height=sample_asset.height,
        date=sample_asset.date,
        title=sample_asset.title,
        keywords=sample_asset.keywords,
        albums=["Album A", "Album B", "Album C"],
        favorite=sample_asset.favorite,
        location=sample_asset.location,
    )
    restore_metadata("new-uuid", multi_album_asset, dry_run=False)

    calls = [str(c[0][0]) for c in mock_osascript.call_args_list]
    assert any("Album A" in c for c in calls)
    assert any("Album B" in c for c in calls)
    assert any("Album C" in c for c in calls)


@patch("archive_videos.reimport._osascript")
def test_restore_metadata_osascript_failure_is_warning_not_error(mock_osascript, sample_asset):
    mock_osascript.side_effect = RuntimeError("AppleScript failed")
    # Should NOT raise — just logs warning
    restore_metadata("new-uuid", sample_asset, dry_run=False)


# ── reimport_asset tests ──────────────────────────────────────────────────────

@patch("archive_videos.reimport.delete_original")
@patch("archive_videos.reimport.import_compressed")
def test_reimport_asset_dry_run_no_subprocess_calls(
    mock_import, mock_delete, sample_asset, tmp_path
):
    mock_import.return_value = None
    compressed = tmp_path / "compressed.mp4"
    compressed.write_bytes(b"data")

    result = reimport_asset(sample_asset, compressed, dry_run=True)

    assert result is None
    # delete_original called with dry_run=True (logs only)
    mock_delete.assert_called_once_with(sample_asset, dry_run=True)
    # import_compressed also called in dry_run mode (logs only, returns None)
    mock_import.assert_called_once()


@patch("archive_videos.reimport._osascript")
def test_reimport_asset_execute_full_workflow(mock_osascript, sample_asset, tmp_path):
    compressed = tmp_path / "compressed.mp4"
    compressed.write_bytes(b"data")
    mock_osascript.return_value = "new-imported-uuid"

    result = reimport_asset(sample_asset, compressed, dry_run=False)

    assert result == "new-imported-uuid"
    # delete + import + date + favorite + album(s) = 1 + 1 + 1 + 1 + 1 = 5 calls
    assert mock_osascript.call_count == 5


@patch("archive_videos.reimport.import_compressed")
@patch("archive_videos.reimport.delete_original")
def test_reimport_asset_compressed_not_found(mock_delete, mock_import, sample_asset, tmp_path):
    nonexistent = tmp_path / "does_not_exist.mp4"
    # No file written

    with pytest.raises(FileNotFoundError):
        reimport_asset(sample_asset, nonexistent, dry_run=False)


@patch("archive_videos.reimport._osascript")
def test_reimport_asset_early_exit_if_no_new_uuid(mock_osascript, sample_asset, tmp_path):
    """If import returns None, restore_metadata should NOT be called."""
    compressed = tmp_path / "compressed.mp4"
    compressed.write_bytes(b"data")

    # First call: delete succeeds; second call: import returns None
    mock_osascript.side_effect = [None, "new-uuid"]  # delete returns None, import returns uuid
    # But actually delete doesn't return anything so just proceed
    # Simpler: make import_compressed return None
    with patch("archive_videos.reimport.import_compressed", return_value=None):
        result = reimport_asset(sample_asset, compressed, dry_run=False)
        # Since new_uuid is None, restore_metadata is not called
        # The osascript mock will only have 1 call (delete)
        assert result is None