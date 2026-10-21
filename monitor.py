import socket
import time
from datetime import datetime


TIMEOUT = 3.5


def log_transition(state):
    message = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {state}"
    if state == "FAILED":
        message += ": No heartbeat received for 3.5 seconds"
    print(message, flush=True)
    with open("incidents.log", "a", encoding="utf-8") as log:
        log.write(message + "\n")


def main():
    state = "WAITING"
    last_heartbeat = None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("127.0.0.1", 9999))
        log_transition(state)
        while True:
            if state == "HEALTHY":
                remaining = TIMEOUT - (time.monotonic() - last_heartbeat)
                if remaining <= 0:
                    state = "FAILED"
                    log_transition(state)
                    continue
                sock.settimeout(remaining)
            else:
                sock.settimeout(None)

            try:
                message, _ = sock.recvfrom(1024)
            except socket.timeout:
                continue

            if message == b"HEARTBEAT":
                last_heartbeat = time.monotonic()
                timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
                print(f"[{timestamp}] HEALTHY: HEARTBEAT received", flush=True)
                if state != "HEALTHY":
                    state = "HEALTHY"
                    log_transition(state)


if __name__ == "__main__":
    main()
