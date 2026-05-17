"""Export original video files and sidecar metadata JSON."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import osxphotos

from .discover import VideoAsset

logger = logging.getLogger(__name__)


def export_original(
    asset: VideoAsset,
    dest_dir: Path,
    dry_run: bool = True,
    db: osxphotos.PhotosDB | None = None,
) -> Path:
    """Export the original video file to dest_dir.

    Returns the exported file path.  In dry-run mode a placeholder is created.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / asset.filename

    if dry_run:
        logger.info("[DRY-RUN] Would export %s → %s", asset.uuid, dest_path)
        # Create a tiny placeholder so downstream steps can proceed in dry-run mode
        dest_path.write_text("DRY_RUN_PLACEHOLDER")
        return dest_path

    photosdb = db or osxphotos.PhotosDB()
    photo = photosdb.get_photo(asset.uuid)
    if photo is None:
        raise FileNotFoundError(f"Photo with uuid {asset.uuid} not found in library")

    # osxphotos PhotoInfo.export handles the actual copy
    exported = photo.export(str(dest_dir), overwrite=True)
    logger.info("Exported %s → %s", asset.uuid, exported)
    return Path(exported) if not isinstance(exported, list) else Path(exported[0])


def write_sidecar(asset: VideoAsset, sidecar_path: Path) -> Path:
    """Write a JSON sidecar with metadata needed for reimport."""
    payload = {
        "uuid": asset.uuid,
        "filename": asset.filename,
        "date": asset.date,
        "title": asset.title,
        "keywords": asset.keywords,
        "albums": asset.albums,
        "favorite": asset.favorite,
        "location": asset.location,
        "duration": asset.duration,
        "codec": asset.codec,
        "width": asset.width,
        "height": asset.height,
        "bitrate_mbps": asset.bitrate_mbps,
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("Wrote sidecar %s", sidecar_path)
    return sidecar_path
