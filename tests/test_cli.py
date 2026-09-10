"""CLI argument parsing and PID-file start/stop lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import cli


def test_parse_list():
    ns = cli.parse_args(["list"])
    assert ns.command == "list"
    assert ns.name is None


def test_parse_list_name():
    ns = cli.parse_args(["list", "orch-demo-0"])
    assert ns.command == "list"
    assert ns.name == "orch-demo-0"


def test_parse_log_alias_and_tail():
    ns = cli.parse_args(["logs", "orch-demo-0", "--tail", "20"])
    assert ns.command == "logs"
    assert ns.name == "orch-demo-0"
    assert ns.tail == 20


def test_parse_requires_command():
    with pytest.raises(SystemExit):
        cli.parse_args([])


def test_start_writes_pid(tmp_path: Path, monkeypatch):
    pid_file = tmp_path / "orchestrator.pid"
    log_file = tmp_path / "orchestrator.log"
    monkeypatch.setenv("SCALER_PID_FILE", str(pid_file))
    monkeypatch.setenv("SCALER_LOG_FILE", str(log_file))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: pid == 4242)
    monkeypatch.setattr(cli, "_api_healthy", lambda url, timeout=1.0: False)
    monkeypatch.setattr(cli, "_wait_healthy", lambda url, timeout=cli.HEALTH_TIMEOUT_SECONDS: True)

    class FakePopen:
        def __init__(self, *args, **kwargs):
            self.pid = 4242

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    rc = cli.main(["start"])
    assert rc == 0
    assert pid_file.read_text().strip() == "4242"


def test_start_refuses_if_api_already_up(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("SCALER_PID_FILE", str(tmp_path / "orchestrator.pid"))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(cli, "_api_healthy", lambda url, timeout=1.0: True)
    called = {"popen": False}

    def boom(*args, **kwargs):
        called["popen"] = True
        raise AssertionError("should not spawn")

    monkeypatch.setattr(cli.subprocess, "Popen", boom)
    rc = cli.main(["start"])
    assert rc == 1
    assert called["popen"] is False
    assert "API already listening" in capsys.readouterr().err


def test_start_refuses_if_already_running(tmp_path: Path, monkeypatch, capsys):
    pid_file = tmp_path / "orchestrator.pid"
    pid_file.write_text("99\n")
    monkeypatch.setenv("SCALER_PID_FILE", str(pid_file))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: pid == 99)
    called = {"popen": False}

    def boom(*args, **kwargs):
        called["popen"] = True
        raise AssertionError("should not spawn")

    monkeypatch.setattr(cli.subprocess, "Popen", boom)
    rc = cli.main(["start"])
    assert rc == 1
    assert called["popen"] is False
    assert "already running" in capsys.readouterr().err


def test_stop_removes_pid(tmp_path: Path, monkeypatch, capsys):
    pid_file = tmp_path / "orchestrator.pid"
    pid_file.write_text("4242\n")
    monkeypatch.setenv("SCALER_PID_FILE", str(pid_file))
    alive = {"4242": True}

    monkeypatch.setattr(cli, "_pid_alive", lambda pid: alive.get(str(pid), False))
    monkeypatch.setattr(cli, "_docker_stop_managed", lambda: ["orch-demo-0"])

    def fake_kill(pid, sig):
        alive[str(pid)] = False

    monkeypatch.setattr(cli.os, "kill", fake_kill)
    rc = cli.main(["stop"])
    assert rc == 0
    assert not pid_file.exists()
    out = capsys.readouterr().out
    assert "stopped pid 4242" in out
    assert "orch-demo-0" in out


def test_stop_not_running(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("SCALER_PID_FILE", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(cli, "_docker_stop_managed", lambda: [])
    rc = cli.main(["stop"])
    assert rc == 1
    assert "not running" in capsys.readouterr().err


def test_stop_removes_leftover_containers_when_process_down(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("SCALER_PID_FILE", str(tmp_path / "missing.pid"))
    monkeypatch.setattr(cli, "_docker_stop_managed", lambda: ["orch-alpha-0", "orch-beta-0"])
    rc = cli.main(["stop"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "orch-alpha-0" in out
    assert "orch-beta-0" in out


def test_list_prints_table(monkeypatch, capsys):
    payload = json.dumps(
        [
            {
                "id": "abc123def456",
                "name": "orch-demo-0",
                "service": "demo",
                "index": 0,
                "status": "running",
            }
        ]
    )
    monkeypatch.setattr(cli, "_api_get", lambda path, base, timeout=5.0: (200, payload))
    rc = cli.main(["list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "orch-demo-0" in out
    assert "demo" in out
    assert "running" in out


def test_list_name_prints_detail(monkeypatch, capsys):
    payload = json.dumps(
        {
            "id": "abc123def456",
            "name": "orch-demo-0",
            "service": "demo",
            "index": 0,
            "status": "running",
            "state": "running",
            "image": "scaler-demo:latest",
            "created": "2026-09-10T10:00:00Z",
            "cpu_percent": 1.2,
            "memory_bytes": 1024,
            "labels": {"orchestrator.managed": "true"},
        }
    )
    monkeypatch.setattr(cli, "_api_get", lambda path, base, timeout=5.0: (200, payload))
    rc = cli.main(["list", "orch-demo-0"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "scaler-demo:latest" in out
    assert "orchestrator.managed=true" in out


def test_log_prints_body(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "_api_get", lambda path, base, timeout=5.0: (200, "hello from demo\n")
    )
    rc = cli.main(["log", "orch-demo-0"])
    assert rc == 0
    assert capsys.readouterr().out == "hello from demo\n"


def test_health_ok(tmp_path: Path, monkeypatch, capsys):
    pid_file = tmp_path / "orchestrator.pid"
    pid_file.write_text("7\n")
    monkeypatch.setenv("SCALER_PID_FILE", str(pid_file))
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: pid == 7)
    monkeypatch.setattr(cli, "_api_get", lambda path, base, timeout=5.0: (200, '{"status":"ok"}'))
    rc = cli.main(["health"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "process: running (pid 7)" in out
    assert "api: ok" in out
