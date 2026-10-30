import argparse
import math
import os
import random
import secrets
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

from . import config
from .checkpoint import CheckpointError, load_checkpoint, save_checkpoint


USERNAME = "demo"
PASSWORD = "password123"


def log(message):
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"[{timestamp}] {message}", flush=True)


class TicketStore:
    def __init__(self, checkpoint_path, tickets=None):
        self.checkpoint_path = Path(checkpoint_path)
        self.tickets = dict(tickets or {})
        self.lock = threading.Lock()

    def issue(self):
        with self.lock:
            ticket = secrets.token_urlsafe(24)
            self.tickets[ticket] = time.time() + config.TICKET_LIFETIME
            try:
                save_checkpoint(self.checkpoint_path, self.tickets)
            except CheckpointError:
                del self.tickets[ticket]
                raise
            return ticket

    def validate(self, ticket):
        with self.lock:
            return (
                isinstance(ticket, str)
                and ticket in self.tickets
                and time.time() < self.tickets[ticket]
            )

    def checkpoint(self):
        with self.lock:
            now = time.time()
            self.tickets = {
                ticket: deadline
                for ticket, deadline in self.tickets.items()
                if deadline > now
            }
            save_checkpoint(self.checkpoint_path, self.tickets)


def create_app(node_id, store):
    app = Flask(__name__)

    @app.post("/login")
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object"}), 400
        if data.get("username") != USERNAME or data.get("password") != PASSWORD:
            return jsonify({"error": "Invalid credentials"}), 401
        try:
            ticket = store.issue()
        except CheckpointError as exc:
            log(f"[CHECKPOINT ERROR] {exc}")
            return jsonify({"error": "Could not persist session"}), 503
        return jsonify({"ticket": ticket, "expires_in": config.TICKET_LIFETIME})

    @app.post("/validate")
    def validate():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Expected a JSON object"}), 400
        return jsonify({"valid": store.validate(data.get("ticket"))})

    @app.get("/health")
    def health():
        return jsonify({"status": "ready", "node_id": node_id, "pid": os.getpid()})

    return app


def send_heartbeats(stop, port, suppress_after):
    started = time.monotonic()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        while not stop.is_set():
            if suppress_after is not None and time.monotonic() - started >= suppress_after:
                log("[AUDIT] Heartbeats suppressed; HTTP service remains running.")
                return
            try:
                sock.sendto(config.HEARTBEAT_PAYLOAD, (config.HOST, port))
            except OSError as exc:
                log(f"[HEARTBEAT ERROR] {exc}")
            if stop.wait(config.HEARTBEAT_INTERVAL):
                return


def checkpoint_periodically(stop, store):
    while not stop.wait(config.CHECKPOINT_INTERVAL):
        try:
            store.checkpoint()
        except CheckpointError as exc:
            log(f"[CHECKPOINT ERROR] {exc}")


def inject_random_crash(stop):
    delay = random.uniform(config.CRASH_DELAY_MIN, config.CRASH_DELAY_MAX)
    if not stop.wait(delay):
        log("[FAULT] Simulated service crash")
        os._exit(1)


def wait_for_promotion():
    log("[STANDBY] Waiting for PROMOTE on stdin.")
    for line in sys.stdin:
        if line == config.PROMOTION_COMMAND:
            log("[PROMOTING] Loading checkpoint.")
            return True
        log("[STANDBY] Ignored unrecognized command.")
    log("[STANDBY] Stdin closed; exiting without promotion.")
    return False


def valid_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535.")
    return port


def nonnegative_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds < 0:
        raise argparse.ArgumentTypeError("Seconds must be finite and nonnegative.")
    return seconds


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Part 2 authentication service")
    parser.add_argument("--mode", choices=("primary", "standby"), required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--service-port", type=valid_port, default=config.SERVICE_PORT)
    parser.add_argument("--heartbeat-port", type=valid_port, default=config.HEARTBEAT_PORT)
    parser.add_argument("--checkpoint", type=Path, default=config.CHECKPOINT_PATH)
    parser.add_argument("--suppress-heartbeats-after", type=nonnegative_seconds)
    args = parser.parse_args(argv)
    if args.mode == "standby" and args.suppress_heartbeats_after is not None:
        parser.error("Heartbeat suppression is only supported in primary mode.")
    return args


def main(argv=None):
    args = parse_args(argv)
    stop = threading.Event()
    server = None
    workers = []

    try:
        if args.mode == "standby" and not wait_for_promotion():
            return 0

        tickets = load_checkpoint(args.checkpoint) if args.mode == "standby" else {}
        store = TicketStore(args.checkpoint, tickets)
        app = create_app(args.node_id, store)

        # Bind before writing so a port conflict cannot overwrite a live node's state.
        server = make_server(config.HOST, args.service_port, app, threaded=True)
        store.checkpoint()

        jobs = [
            (send_heartbeats, (stop, args.heartbeat_port, args.suppress_heartbeats_after)),
            (checkpoint_periodically, (stop, store)),
        ]
        if args.mode == "primary":
            jobs.append((inject_random_crash, (stop,)))

        for target, arguments in jobs:
            worker = threading.Thread(target=target, args=arguments, daemon=True)
            workers.append(worker)
            worker.start()

        log(f"[READY] {args.node_id} pid={os.getpid()} at http://{config.HOST}:{args.service_port}")
        server.serve_forever(poll_interval=config.MONITOR_POLL_INTERVAL)
        return 0
    except KeyboardInterrupt:
        log("[STOPPED] Service stopped.")
        return 0
    except (CheckpointError, OSError) as exc:
        log(f"[ERROR] {exc}")
        return 1
    finally:
        stop.set()
        if server is not None:
            server.server_close()
        for worker in workers:
            worker.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
