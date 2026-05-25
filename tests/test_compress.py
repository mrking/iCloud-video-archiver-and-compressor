"""Tests for archive_videos.compress module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from archive_videos.compress import _build_ffmpeg_cmd, compress_video
from archive_videos.config import CompressionConfig


class TestBuildFFmpegCmd:
    def _cfg(
        self,
        codec: Any = "hevc",
        crf: int = 23,
        preset: Any = "medium",
        max_bitrate_mbps: float = 8.0,
        max_height: int = 1080,
        audio_bitrate: str = "128k",
    ) -> CompressionConfig:
        return CompressionConfig(
            codec=codec, crf=crf, preset=preset,
            max_bitrate_mbps=max_bitrate_mbps, max_height=max_height,
            audio_bitrate=audio_bitrate,
        )

    def test_hevc_basic(self, tmp_path: Path) -> None:
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg())
        assert "libx265" in cmd
        assert "-crf" in cmd
        assert "23" in cmd
        assert "-preset" in cmd
        assert "medium" in cmd
        assert str(out) in cmd

    def test_h264_basic(self, tmp_path: Path) -> None:
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(codec="h264"))
        assert "libx264" in cmd

    def test_max_bitrate_zero_skips_flag(self, tmp_path: Path) -> None:
        """max_bitrate_mbps <= 0 must not add -maxrate or -bufsize."""
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(max_bitrate_mbps=0.0))
        assert "-maxrate" not in cmd
        assert "-bufsize" not in cmd

    def test_max_bitrate_positive_adds_flag(self, tmp_path: Path) -> None:
        """max_bitrate_mbps > 0 must add -maxrate and -bufsize."""
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(max_bitrate_mbps=20.0))
        assert "-maxrate" in cmd
        assert "20.0M" in cmd
        assert "-bufsize" in cmd
        assert "40.0M" in cmd

    def test_audio_copy(self, tmp_path: Path) -> None:
        """audio_bitrate='copy' must use -c:a copy with no -b:a."""
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(audio_bitrate="copy"))
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == "copy"
        # No -b:a flag when copying audio
        assert "-b:a" not in cmd

    def test_audio_reencode(self, tmp_path: Path) -> None:
        """Non-copy audio_bitrate must use -c:a aac -b:a <bitrate>."""
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(audio_bitrate="256k"))
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == "aac"
        b_idx = cmd.index("-b:a")
        assert cmd[b_idx + 1] == "256k"

    def test_metadata_preserved(self, tmp_path: Path) -> None:
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg())
        assert "-map_metadata" in cmd
        assert "0" in cmd

    def test_hevc_tag_for_apple(self, tmp_path: Path) -> None:
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(codec="hevc"))
        assert "-tag:v" in cmd
        assert "hvc1" in cmd

    def test_h264_no_hevc_tag(self, tmp_path: Path) -> None:
        inp = tmp_path / "input.mp4"
        out = tmp_path / "output.mp4"
        cmd = _build_ffmpeg_cmd(inp, out, self._cfg(codec="h264"))
        assert "-tag:v" not in cmd


class TestCompressVideo:
    @patch("subprocess.run")
    def test_compress_success_dry_run(self, mock_run: Any, tmp_path: Path) -> None:
        cfg = CompressionConfig()
        inp = tmp_path / "video001_original.mp4"
        inp.write_bytes(b"fake video content")
        out = tmp_path / "video001_compressed.mp4"

        # ffprobe returns high bitrate → proceeds to compress
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="50000000"
        )

        result = compress_video(inp, out, cfg, dry_run=True)

        assert result == out
        assert out.read_text() == "DRY_RUN_PLACEHOLDER"
        # ffprobe called once, ffmpeg not called in dry-run
        assert mock_run.call_count == 1
        assert "ffprobe" in mock_run.call_args_list[0][0][0]

    @patch("subprocess.run")
    def test_compress_failure_raises_runtime_error(self, mock_run: Any, tmp_path: Path) -> None:
        cfg = CompressionConfig()
        inp = tmp_path / "video001_original.mp4"
        inp.write_bytes(b"fake video content")
        out = tmp_path / "video001_compressed.mp4"

        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="ffmpeg error"
        )

        with pytest.raises(RuntimeError, match="ffmpeg failed with code 1"):
            compress_video(inp, out, cfg, dry_run=False)

    @patch("subprocess.run")
    def test_skip_already_compressed(self, mock_run: Any, tmp_path: Path) -> None:
        """Videos with bitrate below threshold should be skipped."""
        cfg = CompressionConfig()
        inp = tmp_path / "video001_original.mp4"
        inp.write_bytes(b"fake video content")
        out = tmp_path / "video001_compressed.mp4"

        # ffprobe returns low bitrate (5 Mbps) → skip compression
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="5000000"
        )

        result = compress_video(inp, out, cfg, dry_run=True)

        assert result == out
        assert out.read_text() == "SKIPPED_ALREADY_COMPRESSED"
        # Only ffprobe called, no ffmpeg
        assert mock_run.call_count == 1
        assert "ffprobe" in mock_run.call_args_list[0][0][0]
