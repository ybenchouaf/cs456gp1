import json
import socket
import subprocess
import threading
import time
import urllib.request

from part2 import config, monitor
from part2.checkpoint import load_checkpoint

CREDENTIALS = {"username": "demo", "password": "password123"}


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind((config.HOST, 0))
        return sock.getsockname()[1]


def call(port, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://{config.HOST}:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=1) as response:
        return json.load(response)


def serving(port):
    try:
        return call(port, "/health")
    except (OSError, ValueError):
        return None


def test_ticket_survives_automatic_failover_at_same_address(tmp_path, monkeypatch, capsys):
    original_popen = subprocess.Popen

    def popen(command, **kwargs):
        if command[2:4] != ["-m", "part2.service"]:
            return original_popen(command, **kwargs)
        bootstrap = (
            "import runpy; from part2 import config; "
            "config.CRASH_DELAY_MIN = config.CRASH_DELAY_MAX = 5; "
            "config.TICKET_LIFETIME = 20; "
            "runpy.run_module('part2.service', run_name='__main__')"
        )
        return original_popen(command[:2] + ["-c", bootstrap] + command[4:], **kwargs)

    monkeypatch.setattr(monitor.subprocess, "Popen", popen)
    monkeypatch.setattr(config, "INCIDENT_LOG_PATH", tmp_path / "incidents.log")

    checkpoint = tmp_path / "checkpoint.json"
    port = free_port(socket.SOCK_STREAM)
    seen, state = {}, {}

    def watch_for_crash():
        while "t_crash" not in state and "[Service Restored]" not in seen:
            if serving(port) is None:
                state["t_crash"] = time.time()
            time.sleep(0.05)

    original_log = monitor.log

    def log(message):
        original_log(message)
        marker = message.split("]", 1)[0] + "]"
        seen[marker] = time.time()

        if marker == "[Started]":  # primary is ready
            state["ticket"] = call(port, "/login", CREDENTIALS)["ticket"]
            state["deadline"] = load_checkpoint(checkpoint)[state["ticket"]]
            threading.Thread(target=watch_for_crash, daemon=True).start()

        if marker == "[Service Restored]":
            assert serving(port)["node_id"] == "secondary"
            assert call(port, "/validate", {"ticket": state["ticket"]}) == {"valid": True}
            assert load_checkpoint(checkpoint)[state["ticket"]] == state["deadline"]
            new_ticket = call(port, "/login", CREDENTIALS)["ticket"]
            assert call(port, "/validate", {"ticket": new_ticket}) == {"valid": True}

            # wait for the original deadline to pass: the ticket must now be invalid
            time.sleep(max(state["deadline"] - time.time(), 0) + 0.5)
            assert call(port, "/validate", {"ticket": state["ticket"]}) == {"valid": False}
            
            raise KeyboardInterrupt  # stops the controller, which cleans up its children
        

    monkeypatch.setattr(monitor, "log", log)
    args = [
        "--service-port", str(port),
        "--heartbeat-port", str(free_port(socket.SOCK_DGRAM)),
        "--checkpoint", str(checkpoint),
    ]
    assert monitor.main(args) == 0

    assert seen["[Crash Detected]"] <= seen["[Failover Triggered]"] <= seen["[Service Restored]"]
    timings = {
        "detection_delay_s": round(seen["[Crash Detected]"] - state["t_crash"], 3),
        "promotion_to_readiness_s": round(seen["[Service Restored]"] - seen["[Failover Triggered]"], 3),
        "overall_recovery_s": round(seen["[Service Restored]"] - state["t_crash"], 3),
    }
    with capsys.disabled():
        print("\nRecovery timings:", json.dumps(timings))