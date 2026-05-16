"""Tests for state DB transitions."""

from pathlib import Path

from archive_videos.state import State, StateDB, VideoRecord


def test_init_db(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    db = StateDB(db_path)
    assert db_path.exists()


def test_insert_and_get(tmp_path: Path) -> None:
    db = StateDB(tmp_path / "state.db")
    record = VideoRecord(uuid="abc-123", filename="IMG_001.MOV", state=State.DISCOVERED)
    db.insert_or_update(record)

    fetched = db.get("abc-123")
    assert fetched is not None
    assert fetched.uuid == "abc-123"
    assert fetched.filename == "IMG_001.MOV"
    assert fetched.state == State.DISCOVERED


def test_state_transition(tmp_path: Path) -> None:
    db = StateDB(tmp_path / "state.db")
    record = VideoRecord(uuid="abc-123", filename="IMG_001.MOV", state=State.DISCOVERED)
    db.insert_or_update(record)

    record.state = State.EXPORTED
    record.original_path = "/tmp/IMG_001.MOV"
    db.insert_or_update(record)

    fetched = db.get("abc-123")
    assert fetched is not None
    assert fetched.state == State.EXPORTED
    assert fetched.original_path == "/tmp/IMG_001.MOV"


def test_list_pending_and_done(tmp_path: Path) -> None:
    db = StateDB(tmp_path / "state.db")
    db.insert_or_update(VideoRecord(uuid="a", filename="a.mov", state=State.DONE))
    db.insert_or_update(VideoRecord(uuid="b", filename="b.mov", state=State.COMPRESSED))
    db.insert_or_update(VideoRecord(uuid="c", filename="c.mov", state=State.ERROR))

    pending = db.list_pending()
    assert len(pending) == 2
    uuids = {r.uuid for r in pending}
    assert uuids == {"b", "c"}

    done = db.list_by_state(State.DONE)
    assert len(done) == 1
    assert done[0].uuid == "a"


def test_reset_to(tmp_path: Path) -> None:
    db = StateDB(tmp_path / "state.db")
    db.insert_or_update(VideoRecord(uuid="a", filename="a.mov", state=State.ERROR))
    db.reset_to("a", State.DISCOVERED)

    fetched = db.get("a")
    assert fetched is not None
    assert fetched.state == State.DISCOVERED
