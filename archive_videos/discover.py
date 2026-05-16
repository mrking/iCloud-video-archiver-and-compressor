"""Discover uncompressed/high-bitrate videos in the Photos library."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import osxphotos

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


def _get_bitrate_mbps(photo: osxphotos.PhotoInfo) -> float | None:
    """Estimate bitrate in Mbps from photo metadata if available."""
    # osxphotos exposes original_height/width; we can estimate from file size + duration.
    duration = getattr(photo, "duration", 0.0) or 0.0
    if duration <= 0:
        return None
    try:
        # Prefer original file size
        fpath = photo.path_original or photo.path
        if fpath:
            size_bytes = Path(fpath).stat().st_size
            return round((size_bytes * 8) / (duration * 1_000_000), 2)
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
) -> list[VideoAsset]:
    """Query Photos library and return uncompressed video assets.

    Parameters
    ----------
    library_path:
        Optional path to a Photos library database.
    min_bitrate_mbps:
        Minimum bitrate threshold (default 15 Mbps).
    codecs:
        Set of codec identifiers to target (default UNCOMPRESSED_CODECS).
    db:
        Optional pre-opened PhotosDB for testing.

    """
    target_codecs = codecs or UNCOMPRESSED_CODECS
    photosdb = db or osxphotos.PhotosDB(dbfile=str(library_path) if library_path else None)
    videos = photosdb.photos(images=False, movies=True)

    results: list[VideoAsset] = []
    for photo in videos:
        duration = getattr(photo, "duration", 0.0) or 0.0
        if duration <= 0:
            continue

        codec = getattr(photo, "codec", None) or ""
        bitrate = _get_bitrate_mbps(photo)

        # Filter by bitrate if we can estimate it
        if bitrate is not None and bitrate < min_bitrate_mbps:
            continue

        # Filter by target codecs
        if target_codecs and codec not in target_codecs:
            logger.debug("Skipping %s: codec %s not in target set", photo.filename, codec)
            continue

        asset = VideoAsset(
            uuid=photo.uuid,
            filename=photo.filename or "",
            path=Path(photo.path) if photo.path else None,
            duration=duration,
            codec=codec or None,
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

    logger.info("Discovered %d candidate video(s)", len(results))
    return results
