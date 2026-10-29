# Part 2: Recovery

## Status

The architecture, shared configuration, and interfaces are defined in Issue #19.

The service, checkpoint module, controller, and audit script will be implemented through their assigned issues. Commands marked as planned become runnable when those components are merged.

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

## Planned Cluster Execution

The following command will become available after Issues #21 and #22 are implemented:

```bash
python -m part2.monitor
```

The controller will launch both the primary and waiting standby. During normal cluster execution, users will not separately launch those processes.

Stop the controller with Ctrl+C. It will clean up its managed processes.

Part 1 and Part 2 use the same default ports. Stop existing service, monitor, and attacker processes before starting another demonstration or running integration tests.

## Planned Client Demonstration

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

After the primary's random crash and automatic recovery, repeat the validation and health requests.

Expected behavior:

- The same unexpired ticket remains valid.
- The client address remains unchanged.
- The health response identifies the secondary.
- Recovery does not extend the ticket's original expiration.

## Testing

Stop demonstration processes before running tests:

```bash
python -m pytest
```

Existing Part 1 tests remain available. Part 2 tests will be added through Issue #23.

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
