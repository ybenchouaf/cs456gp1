# Part 2: Recovery

## Status

The architecture, shared configuration, and interfaces are defined in Issue #19.

Checkpoint storage, the primary/standby service, and the failover controller are implemented in Issues #20–#22. The adversarial audit script remains planned through its assigned issue.

## Overview

Part 2 extends the Part 1 authentication service with passive redundancy, a warm standby, checkpointing, and automatic failover.

The primary handles client requests and saves session tickets to a checkpoint. A secondary process waits for promotion. After heartbeat timeout and confirmation that the primary process has exited, the controller promotes the secondary.

The secondary restores the checkpoint and serves requests at the same client address. Tickets retain their original expiration deadlines.

The original Part 1 scripts remain available at the repository root. The completed Part 1 baseline is tagged `v1.0`.

## Architecture and Interfaces

See [design.md](design.md) for the architecture diagram, process interfaces, checkpoint format, and failure behavior.

## Components and Ownership

| Component | Location | Owner | Issue |
|---|---|---|---|
| Architecture and shared configuration | `part2/config.py`, `docs/part2/` | Youssef Benchouaf | [#19](https://github.com/ybenchouaf/cs456gp1/issues/19) |
| Checkpoint storage | `part2/checkpoint.py` | Youssef Benchouaf | [#20](https://github.com/ybenchouaf/cs456gp1/issues/20) |
| Primary and standby service | `part2/service.py` | Youssef Benchouaf | [#21](https://github.com/ybenchouaf/cs456gp1/issues/21) |
| Failover controller | `part2/monitor.py` | Mark Robinson | [#22](https://github.com/ybenchouaf/cs456gp1/issues/22) |
| Unit and integration tests | `tests/test_part2_*.py` | Jane Rassadina | [#23](https://github.com/ybenchouaf/cs456gp1/issues/23) |
| Adversarial audit | `part2/audit.py` | Jane Rassadina | [#24](https://github.com/ybenchouaf/cs456gp1/issues/24) |
| Report and contributions | `docs/part2/report.pdf`, `CONTRIBUTIONS.md` | Nadya Radaeva | [#25](https://github.com/ybenchouaf/cs456gp1/issues/25) |
| Demonstration video | Final video or shared link | Nadya Radaeva | [#26](https://github.com/ybenchouaf/cs456gp1/issues/26) |

Dependencies and priorities are maintained through GitHub issue relationships and labels.

## Environment Setup

Requires Python 3.11 or newer. Run commands from the repository root.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Activate the environment in each terminal used for the project.

## Service Processes

The primary and warm standby service modes are available through `part2/service.py`.

For a standalone service check, use three terminals from the repository root with the virtual environment active.

### Terminal 1: Waiting Standby

```bash
python -m part2.service --mode standby --node-id secondary
```

The standby waits for a promotion command on stdin. While waiting, it does not bind the HTTP port, send heartbeats, or write checkpoints.

### Terminal 2: Primary

```bash
python -m part2.service --mode primary --node-id primary
```

The primary initializes its checkpoint, serves requests, sends heartbeats, and crashes randomly after 20–40 seconds.

### Terminal 3: Client

Use the client requests below to obtain and validate a ticket while the primary is running.

After the primary crashes, type `PROMOTE` and press Enter in the standby terminal. Then validate the same ticket again before its original expiration.

This manual promotion exercises the service interface during component testing. Use the controller below for automatic promotion.

### Service Behavior

- Successful login persists the new ticket before returning HTTP 200.
- Failed persistence rolls back the new ticket and returns HTTP 503.
- Invalid credentials return HTTP 401.
- Login and validation require a JSON object; other body types return HTTP 400.
- `GET /health` identifies the ready node and its PID.
- Restored tickets retain their original expiration deadlines.
- The promoted secondary continues checkpointing and sending heartbeats without random crash injection.
- Unrecognized standby input is ignored. Closing stdin exits without promotion.
- Missing or invalid checkpoints prevent promotion from reaching a ready state.

### Configuration Overrides

Both modes support:

- `--service-port PORT`
- `--heartbeat-port PORT`
- `--checkpoint PATH`

Primary mode additionally supports:

```bash
python -m part2.service --mode primary --node-id primary --suppress-heartbeats-after 5
```

After five seconds, heartbeat transmission stops while HTTP processing continues. The primary's random crash remains enabled.

Stop a running service with Ctrl+C.

## Cluster Execution

One command starts the controller, primary, and waiting standby:

```bash
python -m part2.monitor
```

Do not separately launch service processes during controller execution.

Stop the controller with Ctrl+C. It terminates and waits for both managed processes, escalating to a kill if necessary. Use Ctrl+C on Windows; forcibly terminating the controller with Task Manager cannot run Python cleanup.

### Controller Verification

1. Run `python -m part2.monitor`. Wait for `[Started]` and request `/health`
   from another terminal: `Invoke-RestMethod http://127.0.0.1:8080/health`.
   It should identify `primary` and the PID printed by the controller.
2. Issue a ticket using the client commands below. After the primary's random
   crash (20–40 seconds), expect timestamped `[Crash Detected]`,
   `[Failover Triggered]`, and `[Service Restored]` in that order, once each.
   Repeat `/health`: it must identify `secondary` with the expected PID.
   Validate the ticket before its original 60-second expiration.
3. Read the recovery log with `Get-Content runtime/part2/incidents.log`.
   Stop the controller with Ctrl+C. Requests to `/health` should now fail,
   and neither PID printed by the controller should remain running.
4. Start a fresh run with
   `python -m part2.monitor --suppress-heartbeats-after 5`.
   After the 3.5-second timeout, expect `[Heartbeat Disruption]` with no promotion
   while `/health` still identifies the primary. Leave the controller running:
   even without another heartbeat, the primary's eventual crash must trigger
   promotion and verified secondary readiness.

The controller supports `--service-port`, `--heartbeat-port`, and `--checkpoint`
and forwards them to both children. It forwards heartbeat suppression only to
the primary. Startup and standby confirmation are bounded by the shared
10-second startup timeout. Promotion writes and secondary readiness each have
a 10-second bound. Early child exits, pipe errors, port conflicts, and readiness
timeouts produce `[ERROR]` and shut down the managed processes. A restoration
message requires HTTP 200 and matching ready status, node ID, and secondary PID.

Missing heartbeats alone never authorize promotion. The controller keeps polling
the managed primary's process handle every 0.25 seconds. This local process-exit
policy avoids split-brain during heartbeat disruption but does not recover an
alive but hung primary. Only one failover is supported; a later secondary exit
is an explicit error, not another promotion.

Run the controller tests with `python -m pytest tests/test_part2_monitor.py -q`.
They use real child processes on temporary ports with accelerated crash timing,
retain the 3.5-second heartbeat timeout, and verify normal recovery, heartbeat
suppression, identity checks, one promotion, and cleanup.

Part 1 and Part 2 use the same default ports. Stop existing service, monitor, and attacker processes before starting another demonstration or running integration tests.

## Client Requests

Use another terminal while the cluster is running.

Windows PowerShell:

```powershell
$session = Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8080/login `
    -ContentType "application/json" `
    -Body '{"username":"demo","password":"password123"}'

$session

Invoke-RestMethod `
    -Method Post `
    -Uri http://127.0.0.1:8080/validate `
    -ContentType "application/json" `
    -Body (@{ticket=$session.ticket} | ConvertTo-Json)

Invoke-RestMethod -Uri http://127.0.0.1:8080/health
```

After the primary crashes and the standby is promoted, repeat the validation and health requests.

Expected behavior:

- The same unexpired ticket remains valid.
- The client address remains unchanged.
- The health response identifies the secondary.
- Recovery does not extend the ticket's original expiration.

## Checkpoint Storage

`part2/checkpoint.py` provides:

- `save_checkpoint(path, tickets)` to save a versioned JSON snapshot.
- `load_checkpoint(path)` to restore unexpired tickets without extending their expiration.
- `CheckpointError` for invalid checkpoints and filesystem failures.

Saving creates the parent directory if needed, writes and closes a temporary file in that directory, and atomically replaces the destination.

Loading validates the format version, required fields, ticket values, and finite numeric timestamps. Missing or invalid checkpoints raise an explicit error. A valid checkpoint containing no unexpired tickets returns an empty dictionary.

The service must serialize state mutations and checkpoint writes using the shared lock described in the design. This integration is implemented in Issue #21.

Structural validation does not authenticate valid-looking malicious checkpoint replacements.

### Checkpoint Verification

Run this PowerShell block from the repository root with the virtual environment active. It uses a temporary directory and cleans up afterward.

```powershell
@'
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from part2.checkpoint import CheckpointError, load_checkpoint, save_checkpoint


def expect_error(action):
    try:
        action()
    except CheckpointError:
        return
    raise AssertionError("Expected CheckpointError")


with TemporaryDirectory() as directory:
    path = Path(directory) / "checkpoint.json"
    deadline = time.time() + 60

    save_checkpoint(path, {"live": deadline, "expired": time.time() - 1})
    assert load_checkpoint(path) == {"live": deadline}

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["tickets"]["live"] == deadline

    document["version"] = 2
    path.write_text(json.dumps(document), encoding="utf-8")
    expect_error(lambda: load_checkpoint(path))

    save_checkpoint(path, {"live": deadline})
    previous = path.read_bytes()

    with patch("part2.checkpoint.os.replace", side_effect=OSError("simulated")):
        expect_error(lambda: save_checkpoint(path, {"new": deadline}))

    assert path.read_bytes() == previous
    assert not list(path.parent.glob("*.tmp"))

    expect_error(lambda: save_checkpoint(path, {"bad": float("nan")}))
    assert path.read_bytes() == previous

    path.write_text("{broken", encoding="utf-8")
    expect_error(lambda: load_checkpoint(path))
    expect_error(lambda: load_checkpoint(path.parent / "missing.json"))

print("Checkpoint checks passed.")
'@ | python -
```

Expected output:

```text
Checkpoint checks passed.
```

Jane's shared pytest coverage for Part 2 is tracked in Issue #23.

## Testing

Stop demonstration processes before running tests:

```bash
python -m pytest
```

Existing Part 1 tests remain available. Controller tests are in `tests/test_part2_monitor.py`; broader Part 2 coverage is tracked in Issue #23.

## Planned Adversarial Audits

These commands will become available after Issue #24 is implemented:

```bash
python -m part2.audit --scenario heartbeat-loss
python -m part2.audit --scenario corrupt-checkpoint
```

Each scenario will manage its test processes and temporary data.

The heartbeat-loss scenario checks whether missing heartbeats cause promotion while the primary remains alive and responsive.

The checkpoint-corruption scenario checks whether invalid recovery state produces an explicit failure without reporting successful restoration.

Record actual results in `audit-results.md`.

## Runtime Files

Generated files are stored under `runtime/part2/` and excluded from Git:

- `checkpoint.json`
- `incidents.log`

A fresh demonstration initializes a new primary session store. During failover, the checkpoint must remain available for the standby to restore.

## Scope and Limitations

This is a local educational prototype using demonstration credentials.

Recovery covers one primary-to-secondary failover. Automatic failback and recovery from an alive but hung primary are outside the initial implementation.

Heartbeat messages remain unauthenticated. Checkpoint structural validation detects malformed data but does not authenticate valid-looking malicious replacements.

The design has a nonzero recovery delay. Recovery timings and adversarial findings will be reported from actual measurements.

## Deliverables

- Original Part 1 scripts.
- Part 2 service, checkpoint module, controller, and audit script.
- PDF report.
- Narrated video strictly under three minutes.
- Updated `CONTRIBUTIONS.md`.
- Individual reflections submitted separately through Canvas.
