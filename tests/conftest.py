"""conftest.py — shared test fixtures and setup."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# osxphotos is not installed on this machine; pre-populate the module
# so archive_videos.discover (and any module that imports osxphotos)
# can still be imported in tests without triggering ImportError.
if "osxphotos" not in sys.modules:
    sys.modules["osxphotos"] = MagicMock(name="osxphotos")