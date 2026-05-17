"""Tests for archive_videos.glacier module."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from archive_videos.glacier import calculate_sha256, upload_to_glacier
from archive_videos.config import S3Config


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def s3_cfg() -> S3Config:
    return S3Config(
        bucket="test-bucket",
        region="us-east-1",
        prefix="test/",
        storage_class="DEEP_ARCHIVE",
    )


@pytest.fixture
def real_file(tmp_path) -> Path:
    f = tmp_path / "video001_original.mp4"
    f.write_bytes(b"fake video content for checksum")
    return f


# ── calculate_sha256 tests ──────────────────────────────────────────────────

def test_calculate_sha256_returns_hex_string(real_file):
    digest = calculate_sha256(real_file)
    assert len(digest) == 64  # SHA-256 hex = 64 chars
    assert all(c in "0123456789abcdef" for c in digest)


def test_calculate_sha256_deterministic(real_file):
    d1 = calculate_sha256(real_file)
    d2 = calculate_sha256(real_file)
    assert d1 == d2


def test_calculate_sha256_zero_length_file(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    digest = calculate_sha256(empty)
    # SHA-256 of empty string
    expected = hashlib.sha256(b"").hexdigest()
    assert digest == expected


def test_calculate_sha256_different_content_different_hash(tmp_path):
    f1 = tmp_path / "a.mp4"
    f1.write_bytes(b"content A")
    f2 = tmp_path / "b.mp4"
    f2.write_bytes(b"content B")
    assert calculate_sha256(f1) != calculate_sha256(f2)


# ── upload_to_glacier dry-run tests ─────────────────────────────────────────

def test_dry_run_returns_synthetic_id_and_does_not_upload(real_file, s3_cfg):
    result = upload_to_glacier(real_file, "originals/uuid/file.mp4", s3_cfg, dry_run=True)
    assert result.startswith("dry-run-")
    assert len(result) == len("dry-run-") + 16


@patch("archive_videos.glacier.boto3")
def test_dry_run_does_not_instantiate_boto3_client(mock_boto3, real_file, s3_cfg):
    upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=True)
    mock_boto3.assert_not_called()


@patch("archive_videos.glacier.calculate_sha256")
def test_dry_run_calculates_checksum(mock_calc_sha, real_file, s3_cfg):
    mock_calc_sha.return_value = "deadbeef" * 8  # 64-char fake
    result = upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=True)
    mock_calc_sha.assert_called_once_with(real_file)
    assert "deadbeefdeadbeef" in result  # first 16 chars of 64-char digest


# ── upload_to_glacier execute path tests ────────────────────────────────────

@patch("archive_videos.glacier.boto3")
@patch("archive_videos.glacier.calculate_sha256")
def test_execute_uploads_with_correct_s3_args(mock_calc_sha, mock_boto3, real_file, s3_cfg):
    fake_checksum = "abcd1234" * 8  # 64-char
    mock_calc_sha.return_value = fake_checksum
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_client.upload_file.return_value = None
    mock_client.head_object.return_value = {
        "ETag": '"abc123"',
        "ChecksumSHA256": fake_checksum,
    }

    result = upload_to_glacier(real_file, "originals/uuid/file.mp4", s3_cfg, dry_run=False)

    mock_client.upload_file.assert_called_once_with(
        Filename=str(real_file),
        Bucket="test-bucket",
        Key="originals/uuid/file.mp4",
        ExtraArgs={
            "StorageClass": "DEEP_ARCHIVE",
            "ChecksumAlgorithm": "SHA256",
        },
    )


@patch("archive_videos.glacier.boto3")
@patch("archive_videos.glacier.calculate_sha256")
def test_execute_calls_head_object_to_verify(mock_calc_sha, mock_boto3, real_file, s3_cfg):
    mock_calc_sha.return_value = "abcd1234" * 8
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_client.upload_file.return_value = None
    mock_client.head_object.return_value = {
        "ETag": '"abc123"',
        "ChecksumSHA256": "abcd1234" * 8,
    }

    upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=False)

    mock_client.head_object.assert_called_once_with(
        Bucket="test-bucket",
        Key="key.mp4",
        ChecksumMode="ENABLED",
    )


@patch("archive_videos.glacier.boto3")
@patch("archive_videos.glacier.calculate_sha256")
def test_execute_returns_etag_stripped_of_quotes(mock_calc_sha, mock_boto3, real_file, s3_cfg):
    mock_calc_sha.return_value = "abcd1234" * 8
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_client.upload_file.return_value = None
    mock_client.head_object.return_value = {
        "ETag": '"abc123"',
        "ChecksumSHA256": "abcd1234" * 8,
    }

    result = upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=False)
    assert result == "abc123"


@patch("archive_videos.glacier.boto3")
@patch("archive_videos.glacier.calculate_sha256")
def test_checksum_mismatch_raises_runtime_error(mock_calc_sha, mock_boto3, real_file, s3_cfg):
    # Use valid 64-char hex strings for strict comparison path
    local_sha = "a" * 64
    remote_sha = "b" * 64
    mock_calc_sha.return_value = local_sha
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_client.upload_file.return_value = None
    # Remote has a DIFFERENT checksum
    mock_client.head_object.return_value = {
        "ETag": '"abc123"',
        "ChecksumSHA256": remote_sha,
    }

    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=False)


@patch("archive_videos.glacier.boto3")
@patch("archive_videos.glacier.calculate_sha256")
def test_upload_failure_raises_boto_error(mock_calc_sha, mock_boto3, real_file, s3_cfg):
    mock_calc_sha.return_value = "abcd1234" * 8
    mock_client = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_client.upload_file.side_effect = RuntimeError("S3 upload failed")

    with pytest.raises(RuntimeError, match="S3 upload failed"):
        upload_to_glacier(real_file, "key.mp4", s3_cfg, dry_run=False)


def test_empty_file_can_be_uploaded(tmp_path, s3_cfg):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")

    with patch("archive_videos.glacier.boto3") as mock_boto3, \
         patch("archive_videos.glacier.calculate_sha256") as mock_calc_sha:
        mock_calc_sha.return_value = hashlib.sha256(b"").hexdigest()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        mock_client.upload_file.return_value = None
        mock_client.head_object.return_value = {
            "ETag": '"empty"',
            "ChecksumSHA256": hashlib.sha256(b"").hexdigest(),
        }

        result = upload_to_glacier(empty, "originals/uuid/empty.mp4", s3_cfg, dry_run=False)
        assert result == "empty"


def test_nonexistent_file_raises_file_not_found_error(s3_cfg, tmp_path):
    nonexistent = tmp_path / "does_not_exist.mp4"

    with pytest.raises(FileNotFoundError):
        upload_to_glacier(nonexistent, "key.mp4", s3_cfg, dry_run=False)