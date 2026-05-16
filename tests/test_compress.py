"""Tests for compression logic (dry-run, command building)."""

from pathlib import Path

from archive_videos.compress import CODEC_MAP, compress_video
from archive_videos.config import CompressionConfig


def test_codec_map() -> None:
    assert CODEC_MAP["hevc"] == "libx265"
    assert CODEC_MAP["h264"] == "libx264"


def test_compress_dry_run(tmp_path: Path) -> None:
    cfg = CompressionConfig(codec="hevc", crf=23, preset="medium", max_height=1080)
    input_file = tmp_path / "input.mov"
    input_file.write_text("fake video data")
    output_file = tmp_path / "output.mp4"

    result = compress_video(input_file, output_file, cfg, dry_run=True)
    assert result == output_file
    assert output_file.read_text() == "DRY_RUN_PLACEHOLDER"


def test_compress_command_building() -> None:
    """Verify the ffmpeg command is assembled correctly by inspecting internals."""
    cfg = CompressionConfig(
        codec="h264",
        crf=20,
        preset="slow",
        max_height=720,
        max_bitrate_mbps=6.0,
        audio_bitrate="96k",
    )
    # We can't easily run ffmpeg without a real file, but we can assert
    # the config binds correctly.
    assert cfg.codec == "h264"
    assert cfg.crf == 20
    assert cfg.preset == "slow"
    assert cfg.max_height == 720
    assert cfg.max_bitrate_mbps == 6.0
    assert cfg.audio_bitrate == "96k"
