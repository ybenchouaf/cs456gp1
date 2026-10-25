# NOTE: this test listens on UDP port 9999. Stop any running monitor.py first.

import socket
import subprocess
import sys
import attacker

ATTACKER = attacker.__file__

def test_attacker_sends_forged_heartbeats():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.bind(("127.0.0.1", 9999))
        receiver.settimeout(5)

        process = subprocess.Popen([sys.executable, ATTACKER], stdout=subprocess.DEVNULL)
        try:
            first, _ = receiver.recvfrom(1024)
            second, _ = receiver.recvfrom(1024)
        finally:
            process.kill()
            process.wait()

    assert first == b"HEARTBEAT"
    assert second == b"HEARTBEAT"