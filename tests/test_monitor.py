# NOTE: this test start its own monitor on UDP port 9999. Stop any running monitor.py first.

import socket
import subprocess
import sys
import time
import monitor

MONITOR = monitor.__file__

def send_heartbeat():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.sendto(b"HEARTBEAT", ("127.0.0.1", 9999))


def test_monitor_timeout_and_state_transitions(tmp_path):
    process = subprocess.Popen([sys.executable, str(MONITOR)], cwd=tmp_path)
    try:
        time.sleep(1)
        send_heartbeat()  # WAITING -> HEALTHY
        time.sleep(2)

        # 2s into the 3.5s timeout: check that the monitor hasn't failed too early
        lines = (tmp_path / "incidents.log").read_text(encoding="utf-8").splitlines()
        assert "FAILED" not in lines[-1]

        time.sleep(2.5)   # 4.5s total without a heartbeat > 3.5s timeout -> FAILED
        assert process.poll() is None  # check that monitor survived the failure
        send_heartbeat()  # FAILED -> HEALTHY (recovery)
        time.sleep(0.5)
    finally:
        process.kill()
        process.wait()

    lines = (tmp_path / "incidents.log").read_text(encoding="utf-8").splitlines()
    states = [line.split("] ", 1)[1].split(":")[0] for line in lines]
    assert states == ["WAITING", "HEALTHY", "FAILED", "HEALTHY"]