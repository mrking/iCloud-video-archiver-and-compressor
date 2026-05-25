"""CLI entrypoint for archive-videos."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .compress import compress_video
from .config import AppConfig, load_config, resolve_config_path
from .discover import VideoAsset, discover_videos
from .export import export_original, write_sidecar
from .glacier import upload_to_glacier
from .reimport import reimport_asset
from .state import State, StateDB, VideoRecord
from .utils import setup_logging, temp_work_dir

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="archive-videos",
        description="Export, compress, archive, and reimport videos from macOS Photos.app.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", "-c", default=None, help="Path to archive-config.toml")
    parser.add_argument(
        "--execute", action="store_true", help="Run for real (default is dry-run)"
    )
    parser.add_argument("--resume", action="store_true",
                        help="Resume interrupted run from state DB")
    parser.add_argument("--library-path", default=None, help="Path to Photos library")
    parser.add_argument("--state-db", default="./archive-state.db", help="Path to SQLite state DB")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit number of videos to process")
    parser.add_argument("--keep-temps", action="store_true",
                        help="Preserve temp working directory after run for inspection")
    parser.add_argument("--log-level", default=None,
                        help="Override log level from config")
    return parser


def _update_state(
    db: StateDB,
    uuid: str,
    filename: str,
    state: State,
    **kwargs: str | None,
) -> None:
    # Preserve existing field values when not explicitly provided
    existing = db.get(uuid)
    base: dict[str, Any] = {
        "uuid": uuid,
        "filename": filename,
        "state": state,
        "original_path": existing.original_path if existing else None,
        "compressed_path": existing.compressed_path if existing else None,
        "s3_key": existing.s3_key if existing else None,
        "s3_etag": existing.s3_etag if existing else None,
        "sidecar_path": existing.sidecar_path if existing else None,
        "error_log": existing.error_log if existing else None,
    }
    base.update(kwargs)
    record = VideoRecord(**base)
    db.insert_or_update(record)


def process_asset(
    asset: VideoAsset,
    cfg: AppConfig,
    db: StateDB,
    dry_run: bool,
    work_dir: Path,
) -> None:
    """Run the full workflow for a single video asset."""
    logger.info("Processing %s", asset.filename)

    # Paths
    asset_dir = work_dir / asset.uuid
    asset_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = asset_dir / f"{asset.filename}.json"
    compressed_path = asset_dir / f"compressed_{asset.filename}"
    s3_key = f"{cfg.s3.prefix}{asset.uuid}/{asset.filename}"

    # 1. Export
    _update_state(db, asset.uuid, asset.filename, State.EXPORTED)
    original_path = export_original(asset, asset_dir, dry_run=dry_run)
    write_sidecar(asset, sidecar_path)
    _update_state(
        db, asset.uuid, asset.filename, State.EXPORTED,
        original_path=str(original_path), sidecar_path=str(sidecar_path)
    )

    # 2. Compress
    _update_state(db, asset.uuid, asset.filename, State.COMPRESSED)
    compress_video(original_path, compressed_path, cfg.compression, dry_run=dry_run)
    _update_state(
        db, asset.uuid, asset.filename, State.COMPRESSED,
        compressed_path=str(compressed_path)
    )

    # 3. Upload to Glacier
    _update_state(db, asset.uuid, asset.filename, State.UPLOADED)
    etag = upload_to_glacier(original_path, s3_key, cfg.s3, dry_run=dry_run)
    _update_state(
        db, asset.uuid, asset.filename, State.UPLOADED,
        s3_key=s3_key, s3_etag=etag
    )

    # 4. Verify (checksum done inside upload_to_glacier; mark verified)
    _update_state(db, asset.uuid, asset.filename, State.VERIFIED)

    # 5. Reimport
    _update_state(db, asset.uuid, asset.filename, State.DELETED)
    reimport_asset(asset, compressed_path, dry_run=dry_run)
    _update_state(db, asset.uuid, asset.filename, State.IMPORTED)

    # 6. Metadata restore (inside reimport_asset; mark done)
    _update_state(db, asset.uuid, asset.filename, State.METADATA_RESTORED)
    _update_state(db, asset.uuid, asset.filename, State.DONE)
    logger.info("Finished %s", asset.filename)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config_path = resolve_config_path(args.config)
        cfg = load_config(config_path)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    log_level = args.log_level or cfg.log_level
    setup_logging(level=log_level)

    logger.info("Loaded config: %s", config_path)
    logger.info("temp_dir: %s", cfg.temp_dir)

    dry_run = not args.execute
    if dry_run:
        logger.warning("DRY-RUN mode — no changes will be made. Use --execute to run for real.")

    db = StateDB(args.state_db)

    if args.resume:
        pending = db.list_pending()
        logger.info("Resuming %d pending video(s)", len(pending))
        # For simplicity in v0.1, resume re-discovers everything and skips DONE items.
        # A robust resume would re-hydrate VideoAsset from sidecar + state DB.
        logger.info("Resume in v0.1 re-discovers and skips DONE items.")

    assets = discover_videos(
        library_path=args.library_path or cfg.library_path,
        filter_config=cfg.filter,
        limit=args.limit,
    )

    # Skip already-done items when resuming
    if args.resume:
        done_uuids = {r.uuid for r in db.list_by_state(State.DONE)}
        assets = [a for a in assets if a.uuid not in done_uuids]

    if args.limit:
        assets = assets[: args.limit]

    if not assets:
        logger.info("No videos to process.")
        return 0

    logger.info("Processing %d video(s)", len(assets))

    with temp_work_dir(cfg.temp_dir, keep=args.keep_temps) as work_dir:
        for asset in assets:
            try:
                process_asset(asset, cfg, db, dry_run, work_dir)
            except Exception as exc:
                logger.exception("Failed processing %s: %s", asset.filename, exc)
                _update_state(
                    db, asset.uuid, asset.filename, State.ERROR, error_log=str(exc)
                )
                if not dry_run:
                    # Hard stop on real failure to protect data
                    logger.error("Stopping due to error on %s", asset.filename)
                    return 2

    logger.info("All done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
