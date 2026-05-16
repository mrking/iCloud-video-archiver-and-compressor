"""Tests for config loading and validation."""

from pathlib import Path

import pytest

from archive_videos.config import AppConfig, CompressionConfig, S3Config, load_config, resolve_config_path


SAMPLE_TOML = """
[s3]
bucket = "test-bucket"
region = "eu-west-1"
prefix = "archive/"
storage_class = "GLACIER"

[compression]
codec = "h264"
crf = 20
preset = "slow"
max_height = 720
max_bitrate_mbps = 5.0
audio_bitrate = "96k"

library_path = "/Users/test/Pictures/Photos Library.photoslibrary"
temp_dir = "/tmp/test-archiver"
log_level = "DEBUG"
dry_run = false
"""


def test_load_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "test-config.toml"
    cfg_path.write_text(SAMPLE_TOML)
    cfg = load_config(cfg_path)

    assert isinstance(cfg, AppConfig)
    assert cfg.s3.bucket == "test-bucket"
    assert cfg.s3.region == "eu-west-1"
    assert cfg.s3.storage_class == "GLACIER"

    assert cfg.compression.codec == "h264"
    assert cfg.compression.crf == 20
    assert cfg.compression.max_height == 720
    assert cfg.compression.max_bitrate_mbps == 5.0

    assert cfg.library_path == "/Users/test/Pictures/Photos Library.photoslibrary"
    assert cfg.temp_dir == "/tmp/test-archiver"
    assert cfg.log_level == "DEBUG"
    assert cfg.dry_run is False


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.toml")


def test_resolve_config_path_cli(tmp_path: Path) -> None:
    cfg_path = tmp_path / "archive-config.toml"
    cfg_path.write_text("")
    resolved = resolve_config_path(str(cfg_path))
    assert resolved == cfg_path


def test_compression_defaults() -> None:
    c = CompressionConfig()
    assert c.codec == "hevc"
    assert c.crf == 23
    assert c.preset == "medium"


def test_s3_defaults() -> None:
    s = S3Config(bucket="x")
    assert s.region == "us-east-1"
    assert s.prefix == "icloud-archiver/"
    assert s.storage_class == "DEEP_ARCHIVE"
