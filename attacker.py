import socket
import time
from datetime import datetime


def main():
    """Send forged service heartbeats to the local monitor every second."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            while True:
                sock.sendto(b"HEARTBEAT", ("127.0.0.1", 9999))
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                print(f"[{timestamp}] Forged HEARTBEAT sent", flush=True)
                time.sleep(1)
        except KeyboardInterrupt:
            print("Attacker stopped", flush=True)


if __name__ == "__main__":
    main()
