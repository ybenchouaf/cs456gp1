import json
import math
import os
import tempfile
import time
from pathlib import Path

from .config import CHECKPOINT_VERSION


class CheckpointError(Exception):
    """A checkpoint could not be saved or restored."""


def _validate_timestamp(value, name):
    if type(value) not in (int, float):
        raise CheckpointError(f"{name} must be a finite number.")

    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False

    if not finite:
        raise CheckpointError(f"{name} must be a finite number.")


def _validate_tickets(tickets):
    if not isinstance(tickets, dict):
        raise CheckpointError("tickets must be a dictionary.")

    snapshot = tickets.copy()
    for ticket, expires_at in snapshot.items():
        if not isinstance(ticket, str) or not ticket:
            raise CheckpointError("Ticket values must be nonempty strings.")
        _validate_timestamp(expires_at, "Ticket expiration")

    return snapshot


def save_checkpoint(path, tickets):
    """Save a snapshot atomically; the caller serializes state and writes."""
    path = Path(path)
    snapshot = _validate_tickets(tickets)
    document = {
        "version": CHECKPOINT_VERSION,
        "saved_at": time.time(),
        "tickets": snapshot,
    }
    temporary_path = None

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(document, temporary, allow_nan=False)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())

        os.replace(temporary_path, path)
        temporary_path = None
    except (OSError, TypeError, ValueError) as exc:
        raise CheckpointError(f"Could not save checkpoint {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass


def load_checkpoint(path):
    """Restore unexpired tickets without changing their deadlines."""
    path = Path(path)

    try:
        with path.open("r", encoding="utf-8") as checkpoint:
            document = json.load(checkpoint)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise CheckpointError(f"Could not read checkpoint {path}: {exc}") from exc

    required_fields = {"version", "saved_at", "tickets"}
    if not isinstance(document, dict) or set(document) != required_fields:
        raise CheckpointError("Checkpoint must contain version, saved_at, and tickets.")

    version = document["version"]
    if type(version) is not int or version != CHECKPOINT_VERSION:
        raise CheckpointError("Unsupported checkpoint version.")

    _validate_timestamp(document["saved_at"], "saved_at")
    tickets = _validate_tickets(document["tickets"])
    now = time.time()

    return {
        ticket: expires_at
        for ticket, expires_at in tickets.items()
        if expires_at > now
    }
