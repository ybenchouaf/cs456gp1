# Part 2 Audit Results

## Heartbeat loss

**Expected:** The primary stops sending heartbeats but stays alive and serves HTTP. The controller logs a disruption but does not promote the standby, which stays inactive.

**Observed:**

```text
[2026-11-01T17:39:43.544-07:00] Primary ready (pid 47845); heartbeats stop after 5s
[2026-11-01T17:39:51.120-07:00] Controller logged heartbeat disruption; checking the primary for 5s
[2026-11-01T17:39:56.272-07:00] PASS: Primary alive and serving HTTP
[2026-11-01T17:39:56.272-07:00] PASS: Standby not promoted
[2026-11-01T17:39:43.444-07:00] [Starting] primary pid=47845; secondary pid=47844
[2026-11-01T17:39:43.815-07:00] [Started] Primary ready; secondary waiting
[2026-11-01T17:39:48.568-07:00] [AUDIT] Heartbeats suppressed; HTTP service remains running.
[2026-11-01T17:39:51.076-07:00] [Heartbeat Disruption] Primary is alive; promotion withheld
```

No `[Crash Detected]` or `[Failover Triggered]` was logged, and `/login` and `/validate` succeeded during the disruption.

**Result:** PASS

## Corrupt checkpoint

**Expected:** The standby loads the corrupted checkpoint after the primary crashes and fails with an error. The controller never logs `[Service Restored]`.

**Observed:**

```text
[2026-11-01T17:51:12.838-07:00] Primary ready (pid 48202); ticket issued; waiting for its crash
[2026-11-01T17:51:47.345-07:00] Primary crashed; wrote corrupted checkpoint
[2026-11-01T17:51:50.805-07:00] Controller exited with code 1
[2026-11-01T17:51:50.805-07:00] PASS: Corruption written before promotion
[2026-11-01T17:51:50.805-07:00] PASS: Standby attempted to load the checkpoint
[2026-11-01T17:51:50.805-07:00] PASS: Recovery failed explicitly
[2026-11-01T17:51:50.805-07:00] PASS: No [Service Restored], nothing served
[2026-11-01T17:51:50.805-07:00] PASS: Corruption not overwritten
[2026-11-01T17:51:12.732-07:00] [Starting] primary pid=48202; secondary pid=48201
[2026-11-01T17:51:13.105-07:00] [Started] Primary ready; secondary waiting
[2026-11-01T17:51:47.339-07:00] [FAULT] Simulated service crash
[2026-11-01T17:51:50.471-07:00] [Crash Detected] Primary exited (code 1)
[2026-11-01T17:51:50.474-07:00] [Failover Triggered] Promoting secondary
[2026-11-01T17:51:50.476-07:00] [PROMOTING] Loading checkpoint.
[2026-11-01T17:51:50.477-07:00] [ERROR] Could not read checkpoint /private/var/folders/gr/w924__0d31l8w13c_7gmn5hr0000gn/T/part2-audit-7er_2utw/checkpoint.json: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)
[2026-11-01T17:51:50.730-07:00] [ERROR] Secondary exited during recovery (code 1)
```
The standby logged "[PROMOTING] Loading checkpoint.", then a checkpoint [ERROR]. The controller exited with code 1 and never logged [Service Restored].

**Result:** PASS

## Limitations

- Heartbeats are unauthenticated, so a local process can forge or block them.
- Checkpoint validation is structural only, so a valid-looking tampered checkpoint would be restored without detection.