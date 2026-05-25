"""Discover uncompressed/high-bitrate videos in the Photos library."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import osxphotos

from .config import FilterConfig

logger = logging.getLogger(__name__)

# Codecs considered "uncompressed" / high-bitrate targets for recompression.
UNCOMPRESSED_CODECS: set[str] = {"hvc1", "avc1", "jpeg", "dvc ", "apcn", "apch", "apcs", "apco"}

# Minimum bitrate in Mbps to trigger compression.
DEFAULT_MIN_BITRATE_MBPS = 15.0


@dataclass(frozen=True)
class VideoAsset:
    """A candidate video asset from Photos.app."""

    uuid: str
    filename: str
    path: Path | None
    duration: float  # seconds
    codec: str | None
    bitrate_mbps: float | None
    width: int
    height: int
    date: str | None
    title: str | None
    keywords: list[str]
    albums: list[str]
    favorite: bool
    location: tuple[float, float] | None  # (lat, lon)


class PhotosLibrary(Protocol):
    """Protocol for mocking osxphotos.PhotosDB in tests."""

    def photos(self, **kwargs: object) -> list[object]: ...  # type: ignore[empty-body]


def _get_duration_ffprobe(photo: osxphotos.PhotoInfo) -> float | None:
    """Get duration from actual video file via ffprobe."""
    path = photo.path
    if not path:
        return None
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None


def _get_bitrate_mbps(photo: osxphotos.PhotoInfo) -> float | None:
    """Estimate bitrate in Mbps from photo metadata."""
    duration = getattr(photo, "duration", 0.0) or 0.0
    if duration <= 0:
        return None

    # Use original_filesize from Photos DB (works even if file not downloaded)
    size_bytes = getattr(photo, "original_filesize", None)
    if isinstance(size_bytes, (int, float)) and size_bytes > 0:
        return round((size_bytes * 8) / (duration * 1_000_000), 2)

    # Fallback to file path if DB size unavailable
    try:
        fpath = photo.path
        if fpath:
            size_bytes = Path(fpath).stat().st_size
            return round((size_bytes * 8) / (duration * 1_000_000), 2)
    except (OSError, AttributeError):
        pass

    return None


def _get_file_size_mb(photo: osxphotos.PhotoInfo) -> float | None:
    """Return original file size in MB if available."""
    try:
        fpath = photo.path
        if fpath:
            return round(Path(fpath).stat().st_size / (1024 * 1024), 2)
    except (OSError, AttributeError):
        pass
    return None


def _extract_location(photo: osxphotos.PhotoInfo) -> tuple[float, float] | None:
    """Extract latitude/longitude from photo if available."""
    lat = getattr(photo, "latitude", None)
    lon = getattr(photo, "longitude", None)
    if lat is not None and lon is not None:
        return (float(lat), float(lon))
    return None


def discover_videos(
    library_path: str | Path | None = None,
    min_bitrate_mbps: float = DEFAULT_MIN_BITRATE_MBPS,
    codecs: set[str] | None = None,
    db: PhotosLibrary | None = None,
    filter_config: FilterConfig | None = None,
    limit: int = 0,
) -> list[VideoAsset]:
    """Query Photos library and return uncompressed video assets.

    Parameters
    ----------
    library_path:
        Optional path to a Photos library database.
    min_bitrate_mbps:
        Minimum bitrate threshold (default 15 Mbps). DEPRECATED: use filter_config instead.
    codecs:
        Set of codec identifiers to target (default UNCOMPRESSED_CODECS). DEPRECATED: use filter_config instead.
    db:
        Optional pre-opened PhotosDB for testing.
    filter_config:
        Optional FilterConfig to control discovery filtering. Takes precedence over legacy args.
    limit:
        If > 0, stop discovery once this many candidates are found.

    """
    if filter_config is not None:
        target_codecs = set(filter_config.target_codecs) if filter_config.target_codecs else set()
        min_bitrate = filter_config.min_bitrate_mbps
        min_file_size = filter_config.min_file_size_mb
    else:
        target_codecs = codecs or UNCOMPRESSED_CODECS
        min_bitrate = min_bitrate_mbps
        min_file_size = 0.0

    photosdb = db or osxphotos.PhotosDB(dbfile=str(library_path) if library_path else None)
    videos = photosdb.photos(images=False, movies=True)

    results: list[VideoAsset] = []
    for photo in videos:  # type: ignore[union-attr]
        photo = cast(osxphotos.PhotoInfo, photo)
        duration_db = getattr(photo, "duration", 0.0) or 0.0
        duration = duration_db if duration_db > 0 else _get_duration_ffprobe(photo)
        if not duration or duration <= 0:
            logger.info("Skipping %s: cannot determine duration", photo.filename)
            continue

        codec = getattr(photo, "codec", None)
        # Normalize empty string to None so we don't filter on it
        if codec == "":
            codec = None
        bitrate = _get_bitrate_mbps(photo)
        file_size_mb = _get_file_size_mb(photo)

        # Fallback bitrate calculation using ffprobe duration if DB bitrate missing
        if bitrate is None and file_size_mb and duration:
            size_bytes = file_size_mb * 1024 * 1024
            bitrate = round((size_bytes * 8) / (duration * 1_000_000), 2)
            logger.debug("Bitrate for %s calculated via ffprobe fallback: %.2f Mbps", photo.filename, bitrate)

        # Filter by file size if configured
        if min_file_size > 0:
            if file_size_mb is not None and file_size_mb < min_file_size:
                logger.info(
                    "Skipping %s: file size %.2f MB < min %.2f MB",
                    photo.filename, file_size_mb, min_file_size
                )
                continue

        # Filter by bitrate if configured
        if min_bitrate > 0:
            if bitrate is not None and bitrate < min_bitrate:
                logger.info(
                    "Skipping %s: bitrate %.2f Mbps < min %.2f Mbps",
                    photo.filename, bitrate, min_bitrate
                )
                continue

        # Filter by target codecs if configured
        if target_codecs:
            if codec is None:
                # Unknown codec: log and skip only when target_codecs is explicitly set
                logger.info(
                    "Skipping %s: unknown codec (not in target set %s)",
                    photo.filename, target_codecs
                )
                continue
            if codec not in target_codecs:
                logger.info(
                    "Skipping %s: codec %s not in target set %s",
                    photo.filename, codec, target_codecs
                )
                continue

        asset = VideoAsset(
            uuid=photo.uuid,
            filename=photo.filename or "",
            path=Path(photo.path) if photo.path else None,
            duration=duration,
            codec=codec,
            bitrate_mbps=bitrate,
            width=getattr(photo, "original_width", 0) or 0,
            height=getattr(photo, "original_height", 0) or 0,
            date=str(photo.date) if getattr(photo, "date", None) else None,
            title=getattr(photo, "title", None),
            keywords=list(getattr(photo, "keywords", []) or []),
            albums=[album.title for album in (getattr(photo, "albums", []) or [])],
            favorite=bool(getattr(photo, "favorite", False)),
            location=_extract_location(photo),
        )
        results.append(asset)
        logger.info(
            "Discovered %s (%s, %dx%d, %.1f Mbps, %.1fs)",
            asset.filename,
            asset.codec,
            asset.width,
            asset.height,
            asset.bitrate_mbps or 0.0,
            asset.duration,
        )

        if limit > 0 and len(results) >= limit:
            logger.info("Reached limit of %d candidate(s), stopping discovery early", limit)
            break

    logger.info("Discovered %d candidate video(s)", len(results))
    return results
