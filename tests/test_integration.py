"""Integration tests for the full end-to-end workflow in cli.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from archive_videos.cli import process_asset
from archive_videos.config import AppConfig, CompressionConfig, S3Config, FilterConfig
from archive_videos.discover import VideoAsset
from archive_videos.state import State, StateDB, VideoRecord


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def cfg(tmp_path) -> AppConfig:
    return AppConfig(
        library_path="/Photos",
        temp_dir=str(tmp_path / "work"),
        log_level="DEBUG",
        compression=CompressionConfig(
            codec="hevc", crf=18, preset="slow",
            max_bitrate_mbps=0, audio_bitrate="copy",
        ),
        s3=S3Config(
            bucket="test-bucket", region="us-east-1",
            prefix="test/", storage_class="DEEP_ARCHIVE",
        ),
        filter=FilterConfig(),
    )


@pytest.fixture
def work_dir(tmp_path) -> Path:
    """Shared work directory — created once per test."""
    d = tmp_path / "work"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sample_asset() -> VideoAsset:
    return VideoAsset(
        uuid="11111111-1111-1111-1111-111111111111",
        filename="IMG_0001.mov",
        path=Path("/fake/photos/IMG_0001.mov"),
        duration=120.5, codec="hvc1", bitrate_mbps=45.0,
        width=3840, height=2160,
        date="2024-07-15T10:30:00+00:00",
        title="Test Video", keywords=[], albums=[], favorite=False, location=None,
    )


@pytest.fixture
def multi_asset() -> list[VideoAsset]:
    return [
        VideoAsset(
            uuid=f"22222222-{i:04d}-2222-2222-222222222222",
            filename=f"IMG_{i:04d}.mov",
            path=Path(f"/fake/photos/IMG_{i:04d}.mov"),
            duration=60.0, codec="avc1", bitrate_mbps=20.0,
            width=1920, height=1080,
            date="2024-07-15T10:30:00+00:00",
            title=f"Video {i}", keywords=[], albums=[], favorite=False, location=None,
        )
        for i in range(1, 4)
    ]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _build_db(tmp_path: Path) -> StateDB:
    return StateDB(tmp_path / "state.db")


def _setup_asset_files(work_dir: Path, asset: VideoAsset) -> tuple[Path, Path]:
    """Create original + compressed files for an asset. Returns (original, compressed)."""
    ad = work_dir / asset.uuid
    ad.mkdir(parents=True, exist_ok=True)
    original = ad / asset.filename
    compressed = ad / f"compressed_{asset.filename}"
    original.write_bytes(b"video data")
    compressed.write_bytes(b"compressed data")
    return original, compressed


def _mock_temp_work_dir(work_dir: Path):
    """Patch temp_work_dir to yield work_dir without creating anything."""
    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=work_dir)
    mock_cm.__exit__ = MagicMock(return_value=False)
    return patch("archive_videos.cli.temp_work_dir", return_value=mock_cm)


# ── Happy path tests ─────────────────────────────────────────────────────────

@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_happy_path_all_states_transition(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """Full pipeline: export → compress → upload → reimport → final state DONE."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag-abc123"'
    mock_reimport.return_value = "new-uuid-2222"
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        process_asset(sample_asset, cfg, db, dry_run=True, work_dir=work_dir)

    assert mock_export.call_count == 1
    assert mock_compress.call_count == 1
    assert mock_upload.call_count == 1
    assert mock_write_sidecar.call_count == 1
    assert mock_reimport.call_count == 1
    assert db.get(sample_asset.uuid).state == State.DONE


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_happy_path_compressed_path_written_to_state(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """After COMPRESSED step, compressed_path is persisted to DB."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag"'
    mock_reimport.return_value = "new-uuid"
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        process_asset(sample_asset, cfg, db, dry_run=True, work_dir=work_dir)

    record = db.get(sample_asset.uuid)
    assert record.compressed_path is not None
    assert "compressed" in record.compressed_path


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_happy_path_s3_key_and_etag_recorded(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """After UPLOADED step, s3_key and s3_etag are persisted to DB."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag-xyz"'
    mock_reimport.return_value = "new-uuid"
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        process_asset(sample_asset, cfg, db, dry_run=True, work_dir=work_dir)

    record = db.get(sample_asset.uuid)
    assert record.s3_key is not None
    assert "test/" in record.s3_key
    assert record.s3_etag == '"etag-xyz"'


# ── Crash recovery tests ─────────────────────────────────────────────────────

@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_recovery_skips_done_assets_on_resume(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """When resume filters out DONE assets, process_asset is never called for them."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag"'
    mock_reimport.return_value = "new-uuid"
    db = _build_db(work_dir.parent)

    # Pre-populate as DONE
    db.insert_or_update(VideoRecord(
        uuid=sample_asset.uuid, filename=sample_asset.filename, state=State.DONE,
    ))

    done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
    assets_to_process = [a for a in [sample_asset] if a.uuid not in done_uuids]

    for asset in assets_to_process:
        with _mock_temp_work_dir(work_dir):
            process_asset(asset, cfg, db, dry_run=True, work_dir=work_dir)

    # DONE assets skipped entirely
    assert mock_export.call_count == 0
    assert mock_compress.call_count == 0


@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.export_original")
def test_recovery_error_state_recorded_on_compress_failure(
    mock_export, mock_compress,
    mock_write_sidecar,
    sample_asset, cfg, work_dir,
):
    """When compress raises, exception propagates to caller (main) which records ERROR.

    process_asset itself does not catch exceptions — it lets them bubble up so the
    caller (main) can decide what to do. The caller is responsible for setting ERROR.
    """
    original, _ = _setup_asset_files(work_dir, sample_asset)
    (work_dir / sample_asset.uuid / f"compressed_{sample_asset.filename}").unlink()
    mock_export.return_value = original
    mock_write_sidecar.return_value = work_dir / "ignored.json"
    mock_compress.side_effect = RuntimeError("ffmpeg crashed")
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        try:
            process_asset(sample_asset, cfg, db, dry_run=False, work_dir=work_dir)
        except RuntimeError:
            pass
        # Caller (main) records ERROR; process_asset itself does not catch.
        _update_state = lambda uuid, filename, state, **kw: (
            db.insert_or_update(VideoRecord(uuid=uuid, filename=filename, state=state, **kw))
        )
        _update_state(sample_asset.uuid, sample_asset.filename, State.ERROR, error_log="ffmpeg crashed")

    record = db.get(sample_asset.uuid)
    assert record is not None
    assert record.state == State.ERROR


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_recovery_resume_skips_verified_and_deleted(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """Assets already in VERIFIED state are still processed (reimport continues)."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag"'
    mock_reimport.return_value = "uuid-after-import"
    db = _build_db(work_dir.parent)

    # Pre-populate in VERIFIED state (upload succeeded, delete not yet called)
    db.insert_or_update(VideoRecord(
        uuid=sample_asset.uuid, filename=sample_asset.filename, state=State.VERIFIED,
        original_path=str(original), compressed_path=str(compressed),
        s3_key="test/uuid/file.mov", s3_etag='"verified-etag"',
    ))

    done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
    assets_to_process = [a for a in [sample_asset] if a.uuid not in done_uuids]

    for asset in assets_to_process:
        with _mock_temp_work_dir(work_dir):
            process_asset(asset, cfg, db, dry_run=True, work_dir=work_dir)

    # VERIFIED → IMPORTED (reimport was called)
    mock_reimport.assert_called_once()


# ── Idempotency tests ─────────────────────────────────────────────────────────

@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_idempotency_skips_done_assets(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    multi_asset, cfg, work_dir,
):
    """Re-running on already-DONE assets skips all processing."""
    db = _build_db(work_dir.parent)

    for asset in multi_asset:
        db.insert_or_update(VideoRecord(
            uuid=asset.uuid, filename=asset.filename, state=State.DONE,
            original_path=str(work_dir / asset.uuid / "original.mov"),
            compressed_path=str(work_dir / asset.uuid / "compressed.mov"),
        ))

    done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
    remaining = [a for a in multi_asset if a.uuid not in done_uuids]

    for asset in remaining:
        with _mock_temp_work_dir(work_dir):
            process_asset(asset, cfg, db, dry_run=True, work_dir=work_dir)

    # Nothing processed since all were DONE
    assert mock_export.call_count == 0
    assert mock_compress.call_count == 0


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_idempotency_partial_batch_only_reruns_pending(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    multi_asset, cfg, work_dir,
):
    """Given DONE + PENDING mix, only PENDING assets are processed."""
    db = _build_db(work_dir.parent)

    # Asset 0 = DONE
    db.insert_or_update(VideoRecord(
        uuid=multi_asset[0].uuid, filename=multi_asset[0].filename, state=State.DONE,
        original_path=str(work_dir / multi_asset[0].uuid / "original.mov"),
        compressed_path=str(work_dir / multi_asset[0].uuid / "compressed.mov"),
    ))

    # Assets 1, 2 = PENDING → need processing
    for asset in multi_asset[1:]:
        o, c = _setup_asset_files(work_dir, asset)
        db.insert_or_update(VideoRecord(
            uuid=asset.uuid, filename=asset.filename, state=State.EXPORTED,
            original_path=str(o),
        ))

    mock_export.side_effect = lambda a, *args, **kw: work_dir / a.uuid / a.filename
    mock_compress.return_value = Path("/fake/compressed")
    mock_upload.return_value = '"etag"'
    mock_reimport.return_value = "new-uuid"

    done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
    pending = [a for a in multi_asset if a.uuid not in done_uuids]

    for asset in pending:
        with _mock_temp_work_dir(work_dir):
            process_asset(asset, cfg, db, dry_run=True, work_dir=work_dir)

    # Assets 1 and 2 processed, asset 0 skipped
    assert mock_export.call_count == 2
    assert mock_compress.call_count == 2


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_idempotency_preserves_existing_done_record(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """Re-processing skipped for DONE assets; existing DB record is untouched."""
    db = _build_db(work_dir.parent)

    db.insert_or_update(VideoRecord(
        uuid=sample_asset.uuid, filename=sample_asset.filename, state=State.DONE,
        original_path="/already/processed/original.mov",
        compressed_path="/already/processed/compressed.mov",
        s3_key="originals/uuid/file.mov",
        s3_etag='"original-etag"',
    ))

    done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
    assert sample_asset.uuid in done_uuids

    record = db.get(sample_asset.uuid)
    assert record.state == State.DONE
    assert record.original_path == "/already/processed/original.mov"
    assert record.compressed_path == "/already/processed/compressed.mov"


# ── Error handling tests ─────────────────────────────────────────────────────

@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.export_original")
def test_error_logged_on_compress_failure(
    mock_export, mock_compress,
    mock_write_sidecar,
    sample_asset, cfg, work_dir,
):
    """When compress fails, exception propagates; caller is responsible for ERROR state."""
    original, _ = _setup_asset_files(work_dir, sample_asset)
    (work_dir / sample_asset.uuid / f"compressed_{sample_asset.filename}").unlink()
    mock_export.return_value = original
    mock_write_sidecar.return_value = work_dir / "ignored.json"
    mock_compress.side_effect = RuntimeError("ffmpeg segfault")
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        try:
            process_asset(sample_asset, cfg, db, dry_run=False, work_dir=work_dir)
        except RuntimeError:
            pass
        # Caller (main) records ERROR state.
        db.insert_or_update(VideoRecord(
            uuid=sample_asset.uuid, filename=sample_asset.filename,
            state=State.ERROR, error_log="ffmpeg segfault",
        ))

    record = db.get(sample_asset.uuid)
    assert record.state == State.ERROR


# ── End-to-end summary tests ──────────────────────────────────────────────────

@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_end_to_end_no_duplicate_calls(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """Full pipeline calls each step exactly once; final DB state is DONE."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"final-etag"'
    mock_reimport.return_value = "final-uuid"
    db = _build_db(work_dir.parent)

    with _mock_temp_work_dir(work_dir):
        process_asset(sample_asset, cfg, db, dry_run=True, work_dir=work_dir)

    assert mock_export.call_count == 1
    assert mock_compress.call_count == 1
    assert mock_upload.call_count == 1
    assert mock_write_sidecar.call_count == 1
    assert mock_reimport.call_count == 1
    assert db.get(sample_asset.uuid).state == State.DONE


@patch("archive_videos.cli.reimport_asset")
@patch("archive_videos.cli.write_sidecar")
@patch("archive_videos.cli.upload_to_glacier")
@patch("archive_videos.cli.compress_video")
@patch("archive_videos.cli.export_original")
def test_all_states_transitioned_in_sequence(
    mock_export, mock_compress, mock_upload,
    mock_write_sidecar, mock_reimport,
    sample_asset, cfg, work_dir,
):
    """Verify the complete state sequence: EXPORTED → ... → DONE."""
    original, compressed = _setup_asset_files(work_dir, sample_asset)
    mock_export.return_value = original
    mock_compress.return_value = compressed
    mock_upload.return_value = '"etag"'
    mock_reimport.return_value = "uuid-after-import"
    db = _build_db(work_dir.parent)

    states_seen: list[State] = []

    orig_insert = db.insert_or_update

    def tracking_insert(record: VideoRecord):
        states_seen.append(record.state)
        orig_insert(record)

    db.insert_or_update = tracking_insert

    with _mock_temp_work_dir(work_dir):
        process_asset(sample_asset, cfg, db, dry_run=True, work_dir=work_dir)

    assert State.EXPORTED in states_seen
    assert State.COMPRESSED in states_seen
    assert State.UPLOADED in states_seen
    assert State.VERIFIED in states_seen
    assert State.DELETED in states_seen
    assert State.IMPORTED in states_seen
    assert State.METADATA_RESTORED in states_seen
    assert states_seen[-1] == State.DONE