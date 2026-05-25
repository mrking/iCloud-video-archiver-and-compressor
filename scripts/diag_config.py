#!/usr/bin/env python3
"""Diagnostic script for archive-config.toml."""
from pathlib import Path

import toml

cfg_path = Path("archive-config.toml")
if not cfg_path.exists():
    cfg_path = Path.home() / ".config" / "icloud-archiver" / "archive-config.toml"

print(f"Reading: {cfg_path}")
print()

raw = toml.loads(cfg_path.read_text(encoding="utf-8"))
print("=== Parsed TOML keys ===")
for k, v in raw.items():
    if isinstance(v, dict):
        print(f"  [{k}]")
        for sk, sv in v.items():
            print(f"    {sk} = {sv!r}")
    else:
        print(f"  {k} = {v!r}")

print()
print("=== Looking for temp_dir ===")
print(f"  Top-level: {raw.get('temp_dir', 'NOT FOUND')}")
for section, values in raw.items():
    if isinstance(values, dict) and 'temp_dir' in values:
        print(f"  In [{section}]: {values['temp_dir']!r}")
