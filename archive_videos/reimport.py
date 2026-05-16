"""AppleScript bridge for delete, import, metadata restoration, and album reassignments."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from .discover import VideoAsset

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# AppleScript helpers
# ---------------------------------------------------------------------------


def _osascript(script: str) -> str:
    """Run an AppleScript and return stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"AppleScript failed: {result.stderr}")
    return result.stdout.strip()


DELETE_SCRIPT = '''
tell application "Photos"
    set targetPhoto to media item id "{uuid}"
    delete targetPhoto
end tell
'''

IMPORT_SCRIPT = '''
tell application "Photos"
    import POSIX file "{path}"
end tell
'''

# Note: Photos.app AppleScript API is limited.  Metadata restoration is best-effort
# via manual scripting; full GPS/date restoration may require osxphotos write API.

SET_DATE_SCRIPT = '''
tell application "Photos"
    set targetPhoto to media item id "{uuid}"
    set date of targetPhoto to date "{date_str}"
end tell
'''

ADD_TO_ALBUM_SCRIPT = '''
tell application "Photos"
    set targetPhoto to media item id "{uuid}"
    if not (exists album "{album_name}") then
        make new album named "{album_name}"
    end if
    add targetPhoto to album "{album_name}"
end tell
'''

FAVORITE_SCRIPT = '''
tell application "Photos"
    set targetPhoto to media item id "{uuid}"
    set favorite of targetPhoto to {favorite_val}
end tell
'''


def delete_original(asset: VideoAsset, dry_run: bool = True) -> None:
    """Delete the original video from Photos.app."""
    if dry_run:
        logger.info("[DRY-RUN] Would delete original %s", asset.uuid)
        return
    logger.info("Deleting original %s", asset.uuid)
    _osascript(DELETE_SCRIPT.format(uuid=asset.uuid))


def import_compressed(path: Path, dry_run: bool = True) -> str | None:
    """Import a compressed video into Photos.app.

    Returns the UUID of the newly imported item if the AppleScript returns it.
    """
    if dry_run:
        logger.info("[DRY-RUN] Would import %s", path)
        return None
    logger.info("Importing %s", path)
    result = _osascript(IMPORT_SCRIPT.format(path=str(path)))
    # Photos.app import may return nothing useful; callers should match by filename.
    return result or None


def restore_metadata(new_uuid: str, asset: VideoAsset, dry_run: bool = True) -> None:
    """Restore date, favorite, and album assignments to the newly imported video."""
    if dry_run:
        logger.info("[DRY-RUN] Would restore metadata for %s", new_uuid)
        return

    # Date
    if asset.date:
        # macOS AppleScript date format: "Saturday, January 1, 2000 at 12:00:00 AM"
        # We'll attempt ISO -> AppleScript date via Photos app coercion
        try:
            _osascript(SET_DATE_SCRIPT.format(uuid=new_uuid, date_str=asset.date))
        except RuntimeError as exc:
            logger.warning("Failed to set date for %s: %s", new_uuid, exc)

    # Favorite
    try:
        _osascript(FAVORITE_SCRIPT.format(uuid=new_uuid, favorite_val="true" if asset.favorite else "false"))
    except RuntimeError as exc:
        logger.warning("Failed to set favorite for %s: %s", new_uuid, exc)

    # Albums
    for album in asset.albums:
        try:
            _osascript(ADD_TO_ALBUM_SCRIPT.format(uuid=new_uuid, album_name=album))
        except RuntimeError as exc:
            logger.warning("Failed to add %s to album '%s': %s", new_uuid, album, exc)


def reimport_asset(
    asset: VideoAsset,
    compressed_path: Path,
    dry_run: bool = True,
) -> str | None:
    """High-level workflow: delete original, import compressed, restore metadata.

    Returns the new UUID if obtainable.
    """
    delete_original(asset, dry_run=dry_run)
    new_uuid = import_compressed(compressed_path, dry_run=dry_run)
    if new_uuid:
        restore_metadata(new_uuid, asset, dry_run=dry_run)
    return new_uuid
