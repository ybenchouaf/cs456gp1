import json
import socket
import subprocess
from unittest.mock import Mock

import pytest

from part2 import config, monitor


def free_port(kind):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind((config.HOST, 0))
        return sock.getsockname()[1]


@pytest.mark.parametrize("suppression,corrupt", [(None, False), ("0", False), (None, True)])
def test_recovery_and_cleanup(tmp_path, monkeypatch, suppression, corrupt):
    """Real child processes, accelerated crash; retain the real 3.5s timeout."""
    original_popen = subprocess.Popen
    children = []

    def popen(command, **kwargs):
        # Change crash timing only in test children, without changing service code.
        bootstrap = (
            "import runpy; from part2 import config; "
            "config.CRASH_DELAY_MIN = config.CRASH_DELAY_MAX = 5; "
            "runpy.run_module('part2.service', run_name='__main__')"
        )
        child = original_popen(command[:2] + ["-c", bootstrap] + command[4:], **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(monitor.subprocess, "Popen", popen)
    monkeypatch.setattr(config, "INCIDENT_LOG_PATH", tmp_path / "incidents.log")
    messages = []
    original_log = monitor.log

    def log(message):
        original_log(message)
        messages.append(message)
        if "[Crash Detected]" in message and corrupt:
            (tmp_path / "checkpoint.json").write_text("{broken", encoding="utf-8")
        if "[Heartbeat Disruption]" in message:
            assert children[1].poll() is None
            assert not any("[Failover Triggered]" in item for item in messages)
        if "[Service Restored]" in message:
            assert monitor.ready(children[0], "secondary", port)
            assert children[1].poll() is not None
            raise KeyboardInterrupt

    monkeypatch.setattr(monitor, "log", log)
    port = free_port(socket.SOCK_STREAM)
    args = ["--service-port", str(port), "--heartbeat-port",
            str(free_port(socket.SOCK_DGRAM)), "--checkpoint", str(tmp_path / "checkpoint.json")]
    if suppression is not None:
        args += ["--suppress-heartbeats-after", suppression]
    assert monitor.main(args) == (1 if corrupt else 0)
    events = [item.split("]", 1)[0] + "]" for item in messages]
    assert events.count("[Failover Triggered]") == 1
    assert events.index("[Crash Detected]") < events.index("[Failover Triggered]")
    if corrupt:
        assert "[Service Restored]" not in events
        assert any("[ERROR] Secondary exited during recovery" in item for item in messages)
    else:
        assert events.index("[Failover Triggered]") < events.index("[Service Restored]")
    assert ("[Heartbeat Disruption]" in events) == (suppression is not None)
    assert all(child.poll() is not None for child in children)


@pytest.mark.parametrize("health", [
    {"status": "ready", "node_id": "primary", "pid": 123},
    {"status": "ready", "node_id": "secondary", "pid": 456},
    {"status": "starting", "node_id": "secondary", "pid": 123},
])
def test_readiness_rejects_wrong_identity(monkeypatch, health):
    from io import BytesIO
    response = BytesIO(json.dumps(health).encode())
    response.status = 200
    monkeypatch.setattr(monitor, "urlopen", lambda *args, **kwargs: response)
    process = Mock(pid=123)
    process.poll.return_value = None
    assert not monitor.ready(process, "secondary", 8080)


def test_promotion_pipe_failure():
    secondary = Mock()
    secondary.stdin.write.side_effect = BrokenPipeError("standby closed stdin")
    with pytest.raises(RuntimeError, match="Promotion command failed"):
        monitor.promote(secondary)
    secondary.stdin.write.assert_called_once_with(config.PROMOTION_COMMAND)


def test_startup_timeout_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STARTUP_TIMEOUT", 0.1)
    monkeypatch.setattr(config, "INCIDENT_LOG_PATH", tmp_path / "incidents.log")
    monkeypatch.setattr(monitor, "ready", lambda *args: False)
    children = []
    original_launch = monitor.launch

    def launch(*args):
        child = original_launch(*args)
        children.append(child)
        return child

    monkeypatch.setattr(monitor, "launch", launch)
    assert monitor.main([
        "--service-port", str(free_port(socket.SOCK_STREAM)),
        "--heartbeat-port", str(free_port(socket.SOCK_DGRAM)),
        "--checkpoint", str(tmp_path / "checkpoint.json"),
    ]) == 1
    assert "Startup timed out" in (tmp_path / "incidents.log").read_text()
    assert all(child.poll() is not None for child in children)


def test_promotion_timeout(monkeypatch):
    import time
    monkeypatch.setattr(config, "RESTORE_TIMEOUT", 0.01)
    secondary = Mock()
    secondary.stdin.write.side_effect = lambda command: time.sleep(0.1)
    with pytest.raises(RuntimeError, match="Promotion command timed out"):
        monitor.promote(secondary)


def test_readiness_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESTORE_TIMEOUT", 0)
    monkeypatch.setattr(config, "INCIDENT_LOG_PATH", tmp_path / "incidents.log")
    primary = Mock(pid=1, returncode=1)
    primary.poll.side_effect = [None, 1]
    secondary = Mock(pid=2)
    secondary.poll.return_value = None
    processes = iter([secondary, primary])
    monkeypatch.setattr(monitor, "launch", lambda *args: next(processes))
    # First iteration starts the primary; second sees timeout and its exit.
    ticks = iter([0, 0, 0, 4, 4, 4, 4])
    monkeypatch.setattr(monitor.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(monitor.threading.Event, "is_set", lambda self: True)
    monkeypatch.setattr(monitor, "ready", lambda process, *args: process is primary)
    monkeypatch.setattr(monitor, "promote", lambda process: None)
    sock = Mock()
    sock.recvfrom.side_effect = socket.timeout
    context = Mock()
    context.__enter__ = Mock(return_value=sock)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(monitor.socket, "socket", lambda *args: context)
    args = monitor.parse_args([])
    with pytest.raises(RuntimeError, match="Recovery timed out"):
        monitor.supervise(args, [])
    assert "[Service Restored]" not in (tmp_path / "incidents.log").read_text()
