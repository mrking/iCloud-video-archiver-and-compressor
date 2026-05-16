"""Tests for archive_videos.utils module."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path

import pytest

from archive_videos.utils import (
    clean_temp_dir,
    setup_logging,
    sha256_file,
    temp_work_dir,
)


# ── sha256_file tests ───────────────────────────────────────────────────────

def test_sha256_file_returns_hex_string(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    assert len(sha256_file(f)) == 64
    assert all(c in "0123456789abcdef" for c in sha256_file(f))


def test_sha256_file_deterministic(tmp_path):
    f = tmp_path / "data.bin"
    f.write_bytes(b"hello world")
    assert sha256_file(f) == sha256_file(f)


def test_sha256_file_empty_file(tmp_path):
    import hashlib
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    assert sha256_file(f) == hashlib.sha256(b"").hexdigest()


def test_sha256_file_large_file(tmp_path):
    """File larger than the 8 MiB chunk size still hashes correctly."""
    chunk = b"x" * (8 * 1024 * 1024)
    f = tmp_path / "large.bin"
    f.write_bytes(chunk * 3)
    import hashlib
    assert sha256_file(f) == hashlib.sha256(chunk * 3).hexdigest()


def test_sha256_file_nonexistent_raises():
    with pytest.raises(FileNotFoundError):
        sha256_file(Path("/nonexistent/path/file.bin"))


def test_sha256_file_different_content_different_hash(tmp_path):
    f1 = tmp_path / "a.bin"
    f1.write_bytes(b"content A")
    f2 = tmp_path / "b.bin"
    f2.write_bytes(b"content B")
    assert sha256_file(f1) != sha256_file(f2)


# ── setup_logging tests ──────────────────────────────────────────────────────
# These must run in a subprocess so logging.basicConfig() starts from a
# clean state each time — basicConfig applies only once per process.

def _run_in_subprocess(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )


def test_setup_logging_sets_root_logger_level_debug(tmp_path):
    code = f"""
import logging
from archive_videos.utils import setup_logging
setup_logging(level="DEBUG")
logger = logging.getLogger("test")
print(logger.level)
"""
    r = _run_in_subprocess(code)
    level = int(r.stdout.strip())
    assert level <= logging.DEBUG, f"Expected level <= 10 (DEBUG), got {level}"


def test_setup_logging_creates_and_writes_log_file(tmp_path):
    log_path = tmp_path / "test.log"
    code = f"""
import logging
from archive_videos.utils import setup_logging
setup_logging(level="INFO", log_file={str(log_path)!r})
logger = logging.getLogger("test_marker")
logger.info("hello from test")
"""
    r = _run_in_subprocess(code)
    assert r.returncode == 0, r.stderr
    assert log_path.exists()
    assert "hello from test" in log_path.read_text(encoding="utf-8")


def test_setup_logging_log_file_accepts_pathlib(tmp_path):
    log_path = tmp_path / "test2.log"
    code = f"""
import logging
from pathlib import Path
from archive_videos.utils import setup_logging
setup_logging(log_file=Path({str(log_path)!r}))
logger = logging.getLogger("test_marker_2")
logger.info("another message")
"""
    r = _run_in_subprocess(code)
    assert r.returncode == 0, r.stderr
    assert log_path.exists()
    assert "another message" in log_path.read_text(encoding="utf-8")


def test_setup_logging_invalid_level_does_not_raise(tmp_path):
    """Unknown level string should not raise — falls back gracefully."""
    code = f"""
import logging
from archive_videos.utils import setup_logging
try:
    setup_logging(level="NOT_A_REAL_LEVEL")
    print("ok")
except Exception as e:
    print(f"ERROR: {{e}}")
"""
    r = _run_in_subprocess(code)
    assert "ok" in r.stdout, r.stderr


# ── temp_work_dir tests ───────────────────────────────────────────────────────

def test_temp_work_dir_yields_path(tmp_path):
    base = tmp_path / "work"
    with temp_work_dir(base) as td:
        assert isinstance(td, Path)
        assert td.exists()


def test_temp_work_dir_created_under_base(tmp_path):
    base = tmp_path / "work_base"
    with temp_work_dir(base) as td:
        # The temp dir is a direct child of base
        assert td.parent == base


def test_temp_work_dir_cleaned_up_after(tmp_path):
    base = tmp_path / "cleanup_test"
    with temp_work_dir(base):
        pass
    remaining = list(base.iterdir())
    assert len(remaining) == 0


def test_temp_work_dir_parent_created_if_missing(tmp_path):
    base = tmp_path / "does_not_exist" / "nested"
    with temp_work_dir(base) as td:
        assert base.exists()
        assert td.exists()


# ── clean_temp_dir tests ─────────────────────────────────────────────────────

def test_clean_temp_dir_nonexistent_base_returns_zero():
    assert clean_temp_dir("/nonexistent/base/path/xyz") == 0


def test_clean_temp_dir_removes_old_subdirs(tmp_path):
    base = tmp_path / "clean_base"
    base.mkdir()

    old_dir = base / "old_subdir"
    old_dir.mkdir()
    import os
    os.utime(old_dir, (time.time() - 49 * 3600, time.time() - 49 * 3600))

    recent_dir = base / "recent_subdir"
    recent_dir.mkdir()
    os.utime(recent_dir, (time.time() - 1 * 3600, time.time() - 1 * 3600))

    removed = clean_temp_dir(base, max_age_hours=48)

    assert removed == 1
    assert not old_dir.exists()
    assert recent_dir.exists()


def test_clean_temp_dir_respects_max_age_hours(tmp_path):
    base = tmp_path / "age_test"
    base.mkdir()

    almost_old = base / "almost_old"
    almost_old.mkdir()
    import os
    os.utime(almost_old, (time.time() - 47 * 3600, time.time() - 47 * 3600))

    removed = clean_temp_dir(base, max_age_hours=48)
    assert removed == 0
    assert almost_old.exists()


def test_clean_temp_dir_files_not_deleted(tmp_path):
    base = tmp_path / "files_test"
    base.mkdir()

    old_sub = base / "old_sub"
    old_sub.mkdir()
    import os
    os.utime(old_sub, (time.time() - 49 * 3600, time.time() - 49 * 3600))

    regular_file = base / "keep.txt"
    regular_file.write_text("keep me")

    removed = clean_temp_dir(base, max_age_hours=48)

    assert removed == 1
    assert not old_sub.exists()
    assert regular_file.exists()


def test_clean_temp_dir_ignores_regular_files_in_base(tmp_path):
    base = tmp_path / "regular_files"
    base.mkdir()

    f = base / "file.txt"
    f.write_text("content")

    result = clean_temp_dir(base, max_age_hours=48)
    assert result == 0
    assert f.exists()