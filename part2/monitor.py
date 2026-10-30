import argparse
import json
import queue
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from . import config
from .service import nonnegative_seconds, valid_port


def log(message):
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    line = f"[{timestamp}] {message}"
    print(line, flush=True)
    config.INCIDENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.INCIDENT_LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def ready(process, node_id, port):
    if process.poll() is not None:
        return False
    try:
        with urlopen(f"http://{config.HOST}:{port}/health", timeout=0.25) as response:
            if response.status != 200:
                return False
            health = json.load(response)
        return (
            isinstance(health, dict)
            and health.get("status") == "ready"
            and health.get("node_id") == node_id
            and health.get("pid") == process.pid
            and process.poll() is None
        )
    except (OSError, URLError, ValueError):
        return False


def relay_output(process, waiting):
    for line in process.stdout:
        print(line, end="", flush=True)
        if "[STANDBY] Waiting for PROMOTE on stdin." in line:
            waiting.set()


def launch(args, mode, children, waiting):
    command = [
        sys.executable, "-u", "-m", "part2.service", "--mode", mode,
        "--node-id", "primary" if mode == "primary" else "secondary",
        "--service-port", str(args.service_port),
        "--heartbeat-port", str(args.heartbeat_port),
        "--checkpoint", str(args.checkpoint.resolve()),
    ]
    if mode == "primary" and args.suppress_heartbeats_after is not None:
        command += ["--suppress-heartbeats-after", str(args.suppress_heartbeats_after)]
    process = subprocess.Popen(
        command, cwd=config.REPO_ROOT, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    children.append(process)
    threading.Thread(target=relay_output, args=(process, waiting), daemon=True).start()
    return process


def promote(secondary):
    # Bound even a failed pipe write; the command is attempted exactly once.
    result = queue.Queue()

    def send():
        try:
            secondary.stdin.write(config.PROMOTION_COMMAND)
            secondary.stdin.flush()
            result.put(None)
        except (OSError, ValueError) as exc:
            result.put(exc)

    threading.Thread(target=send, daemon=True).start()
    try:
        error = result.get(timeout=config.RESTORE_TIMEOUT)
    except queue.Empty:
        raise RuntimeError("Promotion command timed out") from None
    if error is not None:
        raise RuntimeError(f"Promotion command failed: {error}")


def supervise(args, children):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((config.HOST, args.heartbeat_port))
        sock.settimeout(config.MONITOR_POLL_INTERVAL)
        waiting = threading.Event()
        secondary = launch(args, "standby", children, waiting)
        primary = launch(args, "primary", children, threading.Event())
        log(f"[Starting] primary pid={primary.pid}; secondary pid={secondary.pid}")
        deadline = time.monotonic() + config.STARTUP_TIMEOUT
        last_heartbeat = time.monotonic()
        started = False
        disrupted = False
        while True:
            try:
                payload, _ = sock.recvfrom(1024)
                if payload == config.HEARTBEAT_PAYLOAD:
                    last_heartbeat = time.monotonic()
                    if disrupted:
                        log("[Heartbeat Resumed] Primary heartbeats resumed")
                        disrupted = False
            except socket.timeout:
                pass

            if secondary.poll() is not None:
                raise RuntimeError(f"Standby exited before promotion (code {secondary.returncode})")
            if not started:
                if primary.poll() is not None:
                    raise RuntimeError(f"Primary exited during startup (code {primary.returncode})")
                if waiting.is_set() and ready(primary, "primary", args.service_port):
                    started = True
                    log("[Started] Primary ready; secondary waiting")
                elif time.monotonic() >= deadline:
                    raise RuntimeError("Startup timed out waiting for primary readiness and waiting standby")
                continue

            if time.monotonic() - last_heartbeat < config.HEARTBEAT_TIMEOUT:
                continue
            if primary.poll() is None:
                if not disrupted:
                    log("[Heartbeat Disruption] Primary is alive; promotion withheld")
                    disrupted = True
                continue

            log(f"[Crash Detected] Primary exited (code {primary.returncode})")
            log("[Failover Triggered] Promoting secondary")
            promote(secondary)
            deadline = time.monotonic() + config.RESTORE_TIMEOUT
            while not ready(secondary, "secondary", args.service_port):
                if secondary.poll() is not None:
                    raise RuntimeError(f"Secondary exited during recovery (code {secondary.returncode})")
                if time.monotonic() >= deadline:
                    raise RuntimeError("Recovery timed out: expected secondary /health identity was not ready")
                time.sleep(config.MONITOR_POLL_INTERVAL)
            log(f"[Service Restored] secondary pid={secondary.pid} ready")
            # A single standby is available; do not attempt a second promotion.
            while secondary.poll() is None:
                time.sleep(config.MONITOR_POLL_INTERVAL)
            raise RuntimeError(f"Active secondary exited (code {secondary.returncode}); no standby remains")


def cleanup(children):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)
        if child.stdin:
            child.stdin.close()
        if child.stdout:
            child.stdout.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Launch and supervise the Part 2 primary and standby")
    parser.add_argument("--service-port", type=valid_port, default=config.SERVICE_PORT)
    parser.add_argument("--heartbeat-port", type=valid_port, default=config.HEARTBEAT_PORT)
    parser.add_argument("--checkpoint", type=Path, default=config.CHECKPOINT_PATH)
    parser.add_argument("--suppress-heartbeats-after", type=nonnegative_seconds)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    children = []
    previous_handler = signal.getsignal(signal.SIGTERM)

    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        supervise(args, children)
    except KeyboardInterrupt:
        log("[Stopped] Controller shutdown requested")
        return 0
    except (OSError, RuntimeError) as exc:
        log(f"[ERROR] {exc}")
        return 1
    finally:
        try:
            cleanup(children)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
