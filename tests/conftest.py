"""conftest.py — shared test fixtures and setup."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# osxphotos and boto3 are not installed on this machine; pre-populate
# the modules so archive_videos modules can still be imported in tests.
if "osxphotos" not in sys.modules:
    sys.modules["osxphotos"] = MagicMock(name="osxphotos")
if "boto3" not in sys.modules:
    sys.modules["boto3"] = MagicMock(name="boto3")
if "botocore" not in sys.modules:
    sys.modules["botocore"] = MagicMock(name="botocore")