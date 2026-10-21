import secrets
import time

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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)

