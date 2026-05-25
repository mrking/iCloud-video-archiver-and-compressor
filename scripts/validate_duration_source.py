#!/usr/bin/env python3
"""
Validate whether video duration is stored in Photos DB vs file metadata.
Compares p.duration (DB) vs ffprobe (actual file) across all videos.
"""
import os
import subprocess

import osxphotos


def get_duration_ffprobe(path: str | None) -> float | None:
    """Get duration in seconds using ffprobe."""
    if not path or not os.path.exists(path):
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                path
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass
    return None

db = osxphotos.PhotosDB()
videos = db.photos(movies=True, images=False)
print(f"Total videos: {len(videos)}")
print()

# Counters
db_has_duration = 0
db_missing_duration = 0
ffprobe_has_duration = 0
ffprobe_missing = 0
mismatch = 0
sample_mismatches: list[dict[str, object]] = []

for p in videos:
    db_dur = getattr(p, 'duration', None)
    if db_dur and db_dur > 0:
        db_has_duration += 1
    else:
        db_missing_duration += 1

    path = getattr(p, 'path_original', None) or getattr(p, 'path', '')
    file_dur = get_duration_ffprobe(path)
    if file_dur and file_dur > 0:
        ffprobe_has_duration += 1
    else:
        ffprobe_missing += 1

    # Check for discrepancy when DB has a value
    if db_dur and db_dur > 0 and file_dur:
        if abs(db_dur - file_dur) > 1.0:  # More than 1 second difference
            mismatch += 1
            if len(sample_mismatches) < 5:
                sample_mismatches.append({
                    'filename': p.filename,
                    'db_dur': db_dur,
                    'file_dur': file_dur,
                    'diff': abs(db_dur - file_dur)
                })

print(f"DB duration present: {db_has_duration} "
      f"({db_has_duration / len(videos) * 100:.1f}%)")
print(f"DB duration missing: {db_missing_duration} "
      f"({db_missing_duration / len(videos) * 100:.1f}%)")
print()
print(f"ffprobe duration found: {ffprobe_has_duration} "
      f"({ffprobe_has_duration / len(videos) * 100:.1f}%)")
print(f"ffprobe duration miss: {ffprobe_missing} "
      f"({ffprobe_missing / len(videos) * 100:.1f}%)")
print()
print(f"DB vs file mismatch (>1s): {mismatch}")
if sample_mismatches:
    print("\nSample mismatches:")
    for m in sample_mismatches:
        print(f"  {m['filename']}: "
              f"DB={m['db_dur']:.1f}s, file={m['file_dur']:.1f}s, diff={m['diff']:.1f}s")

# Detailed sample of first 20
print("\n" + "="*70)
print("Detailed sample (first 20 videos):")
for p in videos[:20]:
    db_dur = getattr(p, 'duration', None)
    path = getattr(p, 'path_original', None) or getattr(p, 'path', '')
    file_dur = get_duration_ffprobe(path)
    size_mb = os.path.getsize(path) / (1024 * 1024) if path and os.path.exists(path) else 0

    db_str = f"{db_dur:.1f}s" if db_dur else "None"
    file_str = f"{file_dur:.1f}s" if file_dur else "None"

    print(f"  {p.filename}:")
    print(f"    DB duration:    {db_str}")
    print(f"    File duration:  {file_str}")
    print(f"    File size:      {size_mb:.1f}MB")
    print()
