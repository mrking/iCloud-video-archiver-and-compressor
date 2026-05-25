"""Tests for archive_videos.discover module."""

from __future__ import annotations

from unittest.mock import MagicMock

from archive_videos.config import FilterConfig
from archive_videos.discover import discover_videos


def _make_photo(
    uuid="uuid-1",
    filename="IMG_0001.MOV",
    path="/tmp/photo.mov",
    duration=10.0,
    codec="hevc",
    width=1920,
    height=1080,
    date="2024-01-01",
    title="Test",
    keywords=None,
    albums=None,
    favorite=False,
    latitude=None,
    longitude=None,
):
    photo = MagicMock()
    photo.uuid = uuid
    photo.filename = filename
    photo.path = path
    photo.path_original = path
    photo.duration = duration
    photo.codec = codec
    photo.original_width = width
    photo.original_height = height
    photo.date = date
    photo.title = title
    photo.keywords = keywords or []
    photo.albums = albums or []
    photo.favorite = favorite
    photo.latitude = latitude
    photo.longitude = longitude
    return photo


class MockPhotosDB:
    def __init__(self, photos):
        self._photos = photos

    def photos(self, images=False, movies=True):
        return self._photos


class TestDiscoverVideos:
    def test_empty_target_codecs_includes_all(self, tmp_path, caplog):
        """Empty target_codecs list should include all videos regardless of codec."""
        photo = _make_photo(codec="h264")
        # Write a real file so size measurement works
        p = tmp_path / "photo.mov"
        p.write_bytes(b"x" * 1024 * 1024 * 10)  # 10 MB
        photo.path = str(p)
        photo.path_original = str(p)

        db = MockPhotosDB([photo])
        filt = FilterConfig(min_file_size_mb=0, min_bitrate_mbps=0, target_codecs=[])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1
        assert assets[0].codec == "h264"

    def test_empty_string_codec_not_skipped_when_no_filter(self, tmp_path, caplog):
        """Empty string codec should not cause skip when no codec filter is set."""
        photo = _make_photo(codec="")
        p = tmp_path / "photo.mov"
        p.write_bytes(b"x" * 1024 * 1024 * 10)
        photo.path = str(p)
        photo.path_original = str(p)

        db = MockPhotosDB([photo])
        filt = FilterConfig(min_file_size_mb=0, min_bitrate_mbps=0, target_codecs=[])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1
        assert assets[0].codec is None

    def test_target_codecs_filter(self, tmp_path):
        """Only videos with codecs in target_codecs should be included."""
        photo_hevc = _make_photo(uuid="u1", codec="hevc")
        photo_h264 = _make_photo(uuid="u2", codec="h264")
        photo_prores = _make_photo(uuid="u3", codec="apcn")

        for ph in (photo_hevc, photo_h264, photo_prores):
            p = tmp_path / ph.filename
            p.write_bytes(b"x" * 1024 * 1024 * 10)
            ph.path = str(p)
            ph.path_original = str(p)

        db = MockPhotosDB([photo_hevc, photo_h264, photo_prores])
        filt = FilterConfig(target_codecs=["hevc"])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1
        assert assets[0].uuid == "u1"

    def test_min_file_size_mb_filter(self, tmp_path):
        """Videos smaller than min_file_size_mb should be skipped."""
        photo_big = _make_photo(uuid="u1", filename="big.mov")
        photo_small = _make_photo(uuid="u2", filename="small.mov")

        p_big = tmp_path / "big.mov"
        p_big.write_bytes(b"x" * 1024 * 1024 * 20)  # 20 MB
        photo_big.path = str(p_big)
        photo_big.path_original = str(p_big)

        p_small = tmp_path / "small.mov"
        p_small.write_bytes(b"x" * 1024 * 1024 * 2)  # 2 MB
        photo_small.path = str(p_small)
        photo_small.path_original = str(p_small)

        db = MockPhotosDB([photo_big, photo_small])
        filt = FilterConfig(min_file_size_mb=5, min_bitrate_mbps=0, target_codecs=[])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1
        assert assets[0].uuid == "u1"

    def test_min_bitrate_mbps_filter(self, tmp_path):
        """Videos with bitrate below min_bitrate_mbps should be skipped."""
        photo_high = _make_photo(uuid="u1", filename="high.mov", duration=10.0)
        photo_low = _make_photo(uuid="u2", filename="low.mov", duration=10.0)

        # 20 MB -> ~16.78 Mbps; 5 MB -> ~4.19 Mbps
        p_high = tmp_path / "high.mov"
        p_high.write_bytes(b"x" * 1024 * 1024 * 20)
        photo_high.path = str(p_high)
        photo_high.path_original = str(p_high)

        p_low = tmp_path / "low.mov"
        p_low.write_bytes(b"x" * 1024 * 1024 * 5)
        photo_low.path = str(p_low)
        photo_low.path_original = str(p_low)

        db = MockPhotosDB([photo_high, photo_low])
        filt = FilterConfig(min_file_size_mb=0, min_bitrate_mbps=10, target_codecs=[])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1
        assert assets[0].uuid == "u1"

    def test_zero_filters_include_all(self, tmp_path):
        """All filters at 0/empty should include every video."""
        photo = _make_photo(codec="anything")
        p = tmp_path / "photo.mov"
        p.write_bytes(b"x" * 1024 * 1024 * 1)
        photo.path = str(p)
        photo.path_original = str(p)

        db = MockPhotosDB([photo])
        filt = FilterConfig(min_file_size_mb=0, min_bitrate_mbps=0, target_codecs=[])
        assets = discover_videos(db=db, filter_config=filt)

        assert len(assets) == 1

    def test_legacy_args_still_work(self, tmp_path):
        """Deprecated min_bitrate_mbps and codecs args still function."""
        photo = _make_photo(codec="hevc")
        p = tmp_path / "photo.mov"
        p.write_bytes(b"x" * 1024 * 1024 * 10)
        photo.path = str(p)
        photo.path_original = str(p)

        db = MockPhotosDB([photo])
        assets = discover_videos(db=db, min_bitrate_mbps=0, codecs={"hevc"})
        assert len(assets) == 1
