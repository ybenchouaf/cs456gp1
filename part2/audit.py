import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from . import config

CREDENTIALS = {"username": "demo", "password": "password123"}
CORRUPT = "{corrupted by audit"

LAUNCHER = (
    "import sys; from pathlib import Path; from part2 import config, monitor; "
    "config.INCIDENT_LOG_PATH = Path(sys.argv[1]); "
    "raise SystemExit(monitor.main(sys.argv[2:]))"
)

results = []


def log(text):
    timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
    print(f"[{timestamp}] {text}", flush=True)

def check(name, ok):
    results.append(bool(ok))
    log(f"{'PASS' if ok else 'FAIL'}: {name}")


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


def health(port):
    try:
        return call(port, "/health")
    except (OSError, ValueError):
        return None


def wait_for(check_fn, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check_fn()
        if value:
            return value
        time.sleep(0.05)
    raise TimeoutError(f"condition not met within {timeout}s")


def has(lines, text):
    return any(text in line for line in lines)


def start(work, extra_args):
    port = free_port(socket.SOCK_STREAM)
    checkpoint = work / "checkpoint.json"
    process = subprocess.Popen(
        [
            sys.executable, "-u", "-c", LAUNCHER, str(work / "incidents.log"),
            "--service-port", str(port),
            "--heartbeat-port", str(free_port(socket.SOCK_DGRAM)),
            "--checkpoint", str(checkpoint),
            *extra_args,
        ],
        cwd=config.REPO_ROOT, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    lines = []
    threading.Thread(target=lambda: [lines.append(l.rstrip()) for l in process.stdout], daemon=True).start()
    return process, lines, port, checkpoint


def stop(process):
    if process.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def heartbeat_loss(process, lines, port, checkpoint):
    primary = wait_for(lambda: (h := health(port)) and h["node_id"] == "primary" and h, 15)
    log(f"Primary ready (pid {primary['pid']}); heartbeats stop after 5s")
    wait_for(lambda: has(lines, "[Heartbeat Disruption]"), 20)
    log("Controller logged heartbeat disruption; checking the primary for 5s")

    samples = []
    end = time.monotonic() + 5
    while time.monotonic() < end:
        samples.append(health(port))
        time.sleep(0.25)
    ticket = call(port, "/login", CREDENTIALS)["ticket"]
    valid = call(port, "/validate", {"ticket": ticket}) == {"valid": True}

    check("Primary alive and serving HTTP",
          all(samples) and {s["pid"] for s in samples} == {primary["pid"]} and valid)
    check("Standby not promoted",
          not has(lines, "[Crash Detected]") and not has(lines, "[Failover Triggered]"))


def corrupt_checkpoint(process, lines, port, checkpoint):
    primary = wait_for(lambda: (h := health(port)) and h["node_id"] == "primary" and h, 15)
    call(port, "/login", CREDENTIALS)
    log(f"Primary ready (pid {primary['pid']}); ticket issued; waiting for its crash")

    wait_for(lambda: health(port) is None, 50)
    # The dead primary can't rewrite the file, and the controller waits 3.5s before promoting.
    checkpoint.write_text(CORRUPT, encoding="utf-8")
    early = not has(lines, "[Failover Triggered]")
    log("Primary crashed; wrote corrupted checkpoint")
    exit_code = process.wait(timeout=30)
    log(f"Controller exited with code {exit_code}")
    check("Corruption written before promotion", early)
    check("Standby attempted to load the checkpoint", has(lines, "[PROMOTING] Loading checkpoint."))
    check("Recovery failed explicitly", exit_code == 1 and has(lines, "[ERROR]"))
    check("No [Service Restored], nothing served", not has(lines, "[Service Restored]") and health(port) is None)
    check("Corruption not overwritten", checkpoint.read_text(encoding="utf-8") == CORRUPT)


SCENARIOS = {"heartbeat-loss": heartbeat_loss, "corrupt-checkpoint": corrupt_checkpoint}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Part 2 adversarial audit")
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    args = parser.parse_args(argv)
    extra = ["--suppress-heartbeats-after", "5"] if args.scenario == "heartbeat-loss" else []

    with tempfile.TemporaryDirectory(prefix="part2-audit-", ignore_cleanup_errors=True) as directory:
        process, lines, port, checkpoint = start(Path(directory), extra)
        try:
            SCENARIOS[args.scenario](process, lines, port, checkpoint)
        except Exception as exc:
            check(f"Scenario completed ({exc!r})", False)
        finally:
            stop(process)
        log("Controller output:")
        print("\n".join(lines))

    log(f"Result: {'PASS' if results and all(results) else 'FAIL'}")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())