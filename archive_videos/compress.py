"""FFmpeg compression with metadata preservation."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import CompressionConfig

logger = logging.getLogger(__name__)

CODEC_MAP: dict[str, str] = {
    "hevc": "libx265",
    "h264": "libx264",
}

PRESET_MAP: dict[str, str] = {
    "hevc": "slow",  # x265 default behaviour
    "h264": "medium",
}


def _build_ffmpeg_cmd(
    input_path: Path,
    output_path: Path,
    cfg: CompressionConfig,
) -> list[str]:
    """Build an ffmpeg command for video compression (used by tests)."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lib = CODEC_MAP.get(cfg.codec, "libx265")

    vf_list: list[str] = []
    if cfg.max_height > 0:
        vf_list.append(f"scale=-2:{cfg.max_height}")

    cmd: list[str] = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:v", lib, "-crf", str(cfg.crf), "-preset", cfg.preset,
    ]

    # Audio: 'copy' means preserve original audio; else re-encode with explicit bitrate
    if cfg.audio_bitrate == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", cfg.audio_bitrate]

    # Optional bitrate ceiling — only add when max_bitrate_mbps > 0
    if cfg.max_bitrate_mbps > 0:
        cmd += [
            "-maxrate", f"{cfg.max_bitrate_mbps}M",
            "-bufsize", f"{cfg.max_bitrate_mbps * 2}M",
        ]

    cmd += ["-map_metadata", "0", "-movflags", "+faststart"]

    if vf_list:
        cmd += ["-vf", ",".join(vf_list)]

    if cfg.codec == "hevc":
        cmd += ["-tag:v", "hvc1"]

    cmd += [str(output_path)]
    return cmd


def compress_video(
    input_path: Path,
    output_path: Path,
    cfg: CompressionConfig,
    dry_run: bool = True,
) -> Path:
    """Compress a video with ffmpeg, preserving creation_time and GPS metadata.

    Parameters
    ----------
    input_path:
        Path to the original video file.
    output_path:
        Destination path for the compressed video.
    cfg:
        Compression configuration (codec, CRF, preset, etc.).
    dry_run:
        If True, log the command but do not execute.

    Returns
    -------
    Path to the compressed video file.

    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lib = CODEC_MAP.get(cfg.codec, "libx265")

    vf_list: list[str] = []
    if cfg.max_height > 0:
        vf_list.append(f"scale=-2:{cfg.max_height}")

    cmd: list[str] = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", str(input_path),
        "-c:v", lib,
        "-crf", str(cfg.crf),
        "-preset", cfg.preset,
    ]

    if cfg.audio_bitrate == "copy":
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", cfg.audio_bitrate]

    # Optional bitrate ceiling — only add when max_bitrate_mbps > 0
    if cfg.max_bitrate_mbps > 0:
        cmd += [
            "-maxrate", f"{cfg.max_bitrate_mbps}M",
            "-bufsize", f"{cfg.max_bitrate_mbps * 2}M",
        ]

    cmd += [
        "-map_metadata", "0",       # preserve metadata
        "-movflags", "+faststart",  # web-optimized
    ]

    if vf_list:
        cmd += ["-vf", ",".join(vf_list)]

    if cfg.codec == "hevc":
        cmd += ["-tag:v", "hvc1"]  # Apple compatibility

    cmd += [str(output_path)]

    if dry_run:
        logger.info("[DRY-RUN] Would run: %s", " ".join(cmd))
        output_path.write_text("DRY_RUN_PLACEHOLDER")
        return output_path

    logger.info("Running compression: %s → %s", input_path, output_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg stderr: %s", result.stderr)
        raise RuntimeError(f"ffmpeg failed with code {result.returncode}")

    logger.info("Compressed %s → %s", input_path, output_path)
    return output_path


def get_video_info(path: Path) -> dict[str, str | int | float | None]:
    """Return basic video metadata using ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,bit_rate",
        "-show_entries", "format=duration,size",
        "-of", "json",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    import json
    data = json.loads(result.stdout)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "bit_rate": stream.get("bit_rate"),
        "duration": fmt.get("duration"),
        "size": fmt.get("size"),
    }