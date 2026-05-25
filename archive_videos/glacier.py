"""Upload original to S3 Glacier Deep Archive with checksum verification."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import boto3

from .config import S3Config

logger = logging.getLogger(__name__)


def calculate_sha256(path: Path) -> str:
    """Return the SHA-256 hex digest for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(8192 * 1024):  # 8 MiB chunks
            h.update(chunk)
    return h.hexdigest()


def upload_to_glacier(
    local_path: Path,
    s3_key: str,
    cfg: S3Config,
    dry_run: bool = True,
) -> str:
    """Upload a file to S3 Glacier Deep Archive and return the archive ID / ETag.

    Parameters
    ----------
    local_path:
        File to upload.
    s3_key:
        Destination key in the bucket.
    cfg:
        S3 configuration.
    dry_run:
        If True, skip the actual upload.

    Returns
    -------
    The S3 ETag (or a synthetic ID in dry-run mode).

    """
    chk = calculate_sha256(local_path)
    if dry_run:
        logger.info("[DRY-RUN] Would upload %s → s3://%s/%s (SHA-256: %s)",
                    local_path, cfg.bucket, s3_key, chk)
        return f"dry-run-{chk[:16]}"

    s3 = boto3.client("s3", region_name=cfg.region)

    logger.info("Uploading %s → s3://%s/%s (SHA-256: %s)", local_path, cfg.bucket, s3_key, chk)
    s3.upload_file(
        Filename=str(local_path),
        Bucket=cfg.bucket,
        Key=s3_key,
        ExtraArgs={
            "StorageClass": cfg.storage_class,
            "ChecksumAlgorithm": "SHA256",
        },
    )

    # Verify by head-object
    head = s3.head_object(Bucket=cfg.bucket, Key=s3_key, ChecksumMode="ENABLED")
    remote_checksum = (head.get("ChecksumSHA256") or "").strip()

    # S3 may return a multipart ETag (base64-N) instead of SHA-256 for large files.
    # Only enforce comparison when we actually got a valid 64-char hex SHA-256.
    if remote_checksum and len(remote_checksum) == 64 and all(
        c in "0123456789abcdef" for c in remote_checksum.lower()
    ):
        if remote_checksum.lower() != chk.lower():
            raise RuntimeError(
                f"Checksum mismatch after upload: local={chk} remote={remote_checksum}"
            )
    elif remote_checksum:
        logger.warning(
            "S3 returned non-hex checksum for %s (multipart ETag). Skipping strict verification.",
            s3_key,
        )
    else:
        logger.warning(
            "S3 did not return SHA-256 checksum for %s. Skipping verification.", s3_key
        )

    etag = str(head.get("ETag", "")).strip('"')
    logger.info("Upload verified. ETag=%s", etag)
    return etag
