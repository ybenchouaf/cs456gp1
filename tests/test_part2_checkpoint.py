import time
import pytest
from part2.checkpoint import CheckpointError, load_checkpoint, save_checkpoint


def test_round_trip_preserves_deadlines(tmp_path):
    path = tmp_path / "checkpoint.json"
    tickets = {"a": time.time() + 60}
    save_checkpoint(path, tickets)
    assert load_checkpoint(path) == tickets


def test_expired_tickets_are_discarded(tmp_path):
    path = tmp_path / "checkpoint.json"
    live = time.time() + 60
    save_checkpoint(path, {"live": live, "expired": time.time() - 1})
    assert load_checkpoint(path) == {"live": live}


def test_missing_file_raises(tmp_path):
    with pytest.raises(CheckpointError):
        load_checkpoint(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        '{"version": 1, "saved_at": 1.0}',
        '{"version": 2, "saved_at": 1.0, "tickets": {}}',
        '{"version": 1, "saved_at": 1.0, "tickets": {"a": "soon"}}',
    ],
    ids=["bad-json", "missing-field", "wrong-version", "bad-ticket-value"],
)
def test_invalid_contents_raise(tmp_path, raw):
    path = tmp_path / "checkpoint.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(CheckpointError):
        load_checkpoint(path)