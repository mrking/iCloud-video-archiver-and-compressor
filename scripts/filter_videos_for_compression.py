#!/usr/bin/env python3
"""
Filter videos for compression using ffprobe duration.
Skips videos without local file/duration (not yet synced).
Categorizes by bitrate to detect already-compressed videos.
"""
import json
import os
import subprocess
from pathlib import Path

import osxphotos


def get_duration_ffprobe(path):
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

def bitrate_mbps(size_mb, duration_s):
    """Calculate bitrate in MB per minute."""
    if not duration_s or duration_s <= 0:
        return None
    return (size_mb / duration_s) * 60

def main():
    db = osxphotos.PhotosDB()
    videos = db.photos(movies=True, images=False)
    print(f"Total videos in library: {len(videos)}")
    print()

    # Thresholds (MB per minute)
    COMPRESSED_THRESHOLD = 15    # Below this = already heavily compressed
    # Above this = worth compressing
    _NEEDS_COMPRESSION = 40

    results = {
        "already_compressed": [],
        "needs_compression": [],
        "no_duration": [],
        "no_file": [],
    }

    for p in videos:
        path = getattr(p, 'path_original', None) or getattr(p, 'path', '')
        if not path or not os.path.exists(path):
            results["no_file"].append({"uuid": p.uuid, "filename": p.filename})
            continue

        duration = get_duration_ffprobe(path)
        if not duration:
            results["no_duration"].append({"uuid": p.uuid, "filename": p.filename, "path": path})
            continue

        size_mb = os.path.getsize(path) / (1024 * 1024)
        bitrate = bitrate_mbps(size_mb, duration)

        video_info = {
            "uuid": p.uuid,
            "filename": p.filename,
            "duration_s": round(duration, 1),
            "size_mb": round(size_mb, 1),
            "bitrate_mbpm": round(bitrate, 1) if bitrate else None,
            "path": path,
        }

        if bitrate and bitrate < COMPRESSED_THRESHOLD:
            results["already_compressed"].append(video_info)
        else:
            results["needs_compression"].append(video_info)

    # Summary
    print("=" * 60)
    print("FILTERING RESULTS")
    print("=" * 60)
    print()
    print(f"Already compressed (bitrate < {COMPRESSED_THRESHOLD} MB/min): "
          f"{len(results['already_compressed'])}")
    print(f"Needs compression (bitrate >= {COMPRESSED_THRESHOLD} MB/min): "
          f"{len(results['needs_compression'])}")
    print(f"No duration available (not synced?): "
          f"{len(results['no_duration'])}")
    print(f"No local file: {len(results['no_file'])}")
    print()

    # Show samples
    print("Sample - Already compressed (first 5):")
    for v in results["already_compressed"][:5]:
        print(f"  {v['filename']}: {v['duration_s']}s, {v['size_mb']}MB, {v['bitrate_mbpm']}MB/min")
    print()

    print("Sample - Needs compression (first 5):")
    for v in results["needs_compression"][:5]:
        print(f"  {v['filename']}: {v['duration_s']}s, {v['size_mb']}MB, {v['bitrate_mbpm']}MB/min")
    print()

    if results["no_duration"]:
        print(f"Sample - No duration (first 5 of {len(results['no_duration'])}):")
        for v in results["no_duration"][:5]:
            print(f"  {v['filename']}: {v['path']}")
        print()

    # Save JSON for downstream pipeline use
    output_path = Path("video_compression_queue.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Full results saved to: {output_path}")
    print()
    print("Next steps:")
    print("  - 'needs_compression' list: feed into ffmpeg compress pipeline")
    print("  - 'no_duration' list: retry after iCloud sync completes")
    print("  - 'already_compressed': skip or optionally re-encode with stricter settings")

if __name__ == "__main__":
    main()
