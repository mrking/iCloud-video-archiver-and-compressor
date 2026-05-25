"""Logging, checksums, and temporary directory management."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Generator

logger = logging.getLogger(__name__)


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    """Configure root logger with console and optional file handler."""
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=handlers,
    )


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


@contextlib.contextmanager
def temp_work_dir(
    base: str | Path = "/tmp/icloud-archiver",
    keep: bool = False,
) -> Generator[Path, None, None]:
    """Create a scoped temporary working directory.

    If *keep* is True, the directory is NOT deleted on exit
    (useful for post-run inspection).
    """
    base_path = Path(base)
    base_path.mkdir(parents=True, exist_ok=True)
    if keep:
        # Use a fixed timestamped directory instead of TemporaryDirectory
        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        td = base_path / f"run_{ts}"
        td.mkdir(parents=True, exist_ok=True)
        try:
            yield td
        finally:
            logger.info("Temp files preserved in %s (--keep-temps)", td)
    else:
        with tempfile.TemporaryDirectory(dir=str(base_path), prefix="run_") as td_name:
            yield Path(td_name)  # type: ignore[assignment]


def clean_temp_dir(base: str | Path = "/tmp/icloud-archiver", max_age_hours: int = 48) -> int:
    """Remove temp subdirectories older than max_age_hours.  Returns count removed."""
    import time

    base_path = Path(base)
    if not base_path.exists():
        return 0

    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    removed = 0
    for sub in base_path.iterdir():
        if sub.is_dir() and sub.stat().st_mtime < cutoff:
            import shutil
            shutil.rmtree(sub, ignore_errors=True)
            removed += 1
    return removed
