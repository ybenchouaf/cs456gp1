import json
import socket
import subprocess
import sys
import time
import urllib.request

from part2.checkpoint import load_checkpoint, save_checkpoint
from part2.service import TicketStore, create_app

CREDENTIALS = {"username": "demo", "password": "password123"}


def make_client(tmp_path):
    store = TicketStore(tmp_path / "checkpoint.json")
    app = create_app("test-node", store)
    app.config["TESTING"] = True
    return app.test_client(), store


def test_login_valid_persists_ticket(tmp_path):
    client, store = make_client(tmp_path)
    response = client.post("/login", json=CREDENTIALS)
    assert response.status_code == 200
    assert response.get_json()["ticket"] in load_checkpoint(store.checkpoint_path)


def test_login_invalid_credentials_rejected(tmp_path):
    client, store = make_client(tmp_path)
    response = client.post("/login", json={"username": "demo", "password": "wrong"})
    assert response.status_code == 401
    assert store.tickets == {}


def test_validate_valid_unknown_and_expired(tmp_path):
    client, store = make_client(tmp_path)
    ticket = client.post("/login", json=CREDENTIALS).get_json()["ticket"]
    assert client.post("/validate", json={"ticket": ticket}).get_json() == {"valid": True}
    assert client.post("/validate", json={"ticket": "unknown"}).get_json() == {"valid": False}

    store.tickets[ticket] = time.time() - 1  # force expiry instead of waiting 60s
    assert client.post("/validate", json={"ticket": ticket}).get_json() == {"valid": False}


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1) as response:
        return json.load(response)


def serving(port):
    try:
        return call(port, "/health")
    except OSError:
        return None


def test_standby_waits_then_promotes_and_serves(tmp_path):
    checkpoint = tmp_path / "checkpoint.json"
    deadline = time.time() + 45
    save_checkpoint(checkpoint, {"live": deadline, "expired": time.time() - 5})
    port = free_port(socket.SOCK_STREAM)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "part2.service",
            "--mode", "standby", "--node-id", "secondary",
            "--service-port", str(port),
            "--heartbeat-port", str(free_port(socket.SOCK_DGRAM)),
            "--checkpoint", str(checkpoint),
        ],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        time.sleep(1)
        assert proc.poll() is None and serving(port) is None  # waiting, not serving

        proc.stdin.write("PROMOTE\n")
        proc.stdin.flush()
        end = time.monotonic() + 10
        while serving(port) is None and time.monotonic() < end:
            time.sleep(0.1)

        assert serving(port)["node_id"] == "secondary"
        assert call(port, "/validate", {"ticket": "live"}) == {"valid": True}
        assert call(port, "/validate", {"ticket": "expired"}) == {"valid": False}
        assert load_checkpoint(checkpoint)["live"] == deadline  # not extended
        ticket = call(port, "/login", CREDENTIALS)["ticket"]
        assert call(port, "/validate", {"ticket": ticket}) == {"valid": True}
    finally:
        proc.kill()
        proc.wait(timeout=5)
        proc.stdin.close()