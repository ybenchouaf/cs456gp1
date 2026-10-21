import secrets
import time
import os
import random
import socket
import threading


from flask import Flask, jsonify, request

app = Flask(__name__)

# Demo credentials and session storage
USERNAME = "demo"
PASSWORD = "password123"
TICKET_LIFETIME = 60  # seconds
tickets = {}


@app.post("/login")
def login():
    data = request.get_json(silent=True) or {}

    if data.get("username") != USERNAME or data.get("password") != PASSWORD:
        return jsonify({"error": "Invalid credentials"}), 401

    ticket = secrets.token_urlsafe(24)
    tickets[ticket] = time.monotonic() + TICKET_LIFETIME

    return jsonify({
        "ticket": ticket,
        "expires_in": TICKET_LIFETIME
    })


@app.post("/validate")
def validate():
    data = request.get_json(silent=True) or {}
    ticket = data.get("ticket")

    valid = (
        isinstance(ticket, str)
        and ticket in tickets
        and time.monotonic() < tickets[ticket]
    )

    return jsonify({"valid": valid})



def send_heartbeats():
    """Send a heartbeat to the monitor every second."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        while True:
            sock.sendto(b"HEARTBEAT", ("127.0.0.1", 9999))
            print("[HEARTBEAT] Sent", flush=True)
            time.sleep(1)


def inject_random_crash():
    """Simulate an unpredictable service failure."""
    time.sleep(random.uniform(20, 40))
    print("[FAULT] Simulated service crash", flush=True)
    os._exit(1)



if __name__ == "__main__":
    threading.Thread(target=send_heartbeats, daemon=True).start()
    threading.Thread(target=inject_random_crash, daemon=True).start()

    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)

