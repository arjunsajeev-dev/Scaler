"""Host-side `scaler` CLI: start/stop the orchestrator and query its HTTP API."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.config import ROOT

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
HEALTH_TIMEOUT_SECONDS = 15.0
STOP_WAIT_SECONDS = 20.0
MANAGED_LABEL_FILTER = "orchestrator.managed=true"


def _pid_path() -> Path:
    override = os.environ.get("SCALER_PID_FILE")
    if override:
        return Path(override)
    return ROOT / ".scaler" / "orchestrator.pid"


def _log_path() -> Path:
    override = os.environ.get("SCALER_LOG_FILE")
    if override:
        return Path(override)
    return ROOT / ".scaler" / "orchestrator.log"


def _api_url(ns: argparse.Namespace) -> str:
    return ns.url.rstrip("/")


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text().strip()
    except FileNotFoundError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _write_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{pid}\n")


def _remove_pid(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _api_get(path: str, base: str, timeout: float = 5.0) -> tuple[int, str]:
    url = base.rstrip("/") + path
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        return int(exc.code), body
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise SystemExit(f"orchestrator not reachable at {base}: {reason}") from exc


def _api_healthy(base: str, timeout: float = 1.0) -> bool:
    try:
        status, _ = _api_get("/health", base, timeout=timeout)
        return status == 200
    except SystemExit:
        return False


def _wait_healthy(base: str, timeout: float = HEALTH_TIMEOUT_SECONDS) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _api_healthy(base, timeout=1.0):
            return True
        time.sleep(0.1)
    return False


def _print_table(rows: list[dict[str, object]], columns: list[tuple[str, str]]) -> None:
    if not rows:
        print("no containers")
        return
    headers = [header for header, _ in columns]
    str_rows = [
        [str(row.get(key, "") if row.get(key) is not None else "") for _, key in columns]
        for row in rows
    ]
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    header_line = "  ".join(h.upper().ljust(widths[i]) for i, h in enumerate(headers))
    print(header_line)
    for row in str_rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def cmd_start(ns: argparse.Namespace) -> int:
    url = _api_url(ns)
    path = _pid_path()
    existing = _read_pid(path)
    if existing is not None and _pid_alive(existing):
        print(f"already running (pid {existing})", file=sys.stderr)
        return 1
    if existing is not None:
        _remove_pid(path)
    if _api_healthy(url):
        print(
            f"API already listening at {url}; stop that process before scaler start",
            file=sys.stderr,
        )
        return 1

    log_path = _log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = open(log_path, "ab")  # noqa: SIM115 - kept open for the child process
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            DEFAULT_HOST,
            "--port",
            str(DEFAULT_PORT),
        ],
        cwd=str(ROOT),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        close_fds=True,
    )
    _write_pid(path, proc.pid)
    ready = _wait_healthy(url)
    if not _pid_alive(proc.pid):
        _remove_pid(path)
        print(
            f"orchestrator process {proc.pid} exited; see {log_path}",
            file=sys.stderr,
        )
        return 1
    if not ready:
        print(
            f"started pid {proc.pid} but /health did not become ready; see {log_path}",
            file=sys.stderr,
        )
        return 1
    print(f"started pid {proc.pid}")
    return 0


def _docker_stop_managed() -> list[str]:
    """Fallback when the API is already down: stop leftovers via the docker CLI."""
    try:
        listed = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                f"label={MANAGED_LABEL_FILTER}",
                "--format",
                "{{.Names}}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    names = [line.strip().lstrip("/") for line in listed.stdout.splitlines() if line.strip()]
    if not names:
        return []
    subprocess.run(
        ["docker", "stop", "--time", "10", *names],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    subprocess.run(
        ["docker", "rm", "-f", *names],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return names


def _stop_process(pid: int) -> None:
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_WAIT_SECONDS
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def cmd_stop(ns: argparse.Namespace) -> int:
    path = _pid_path()
    pid = _read_pid(path)
    process_stopped = False
    if pid is not None and _pid_alive(pid):
        _stop_process(pid)
        process_stopped = True
    if pid is not None:
        _remove_pid(path)

    leftover = _docker_stop_managed()
    if leftover:
        print(f"stopped managed containers: {', '.join(leftover)}")
    if process_stopped:
        print(f"stopped pid {pid}")
        return 0
    if leftover:
        print("orchestrator was not running; leftover managed containers removed")
        return 0
    print("not running", file=sys.stderr)
    return 1


def cmd_health(ns: argparse.Namespace) -> int:
    path = _pid_path()
    pid = _read_pid(path)
    if pid is not None and _pid_alive(pid):
        print(f"process: running (pid {pid})")
        process_ok = True
    elif pid is not None:
        print("process: not running (stale pid file)")
        process_ok = False
    else:
        print("process: not running")
        process_ok = False
    try:
        status, body = _api_get("/health", _api_url(ns))
    except SystemExit as exc:
        print(f"api: unreachable ({exc})")
        return 1
    if status == 200:
        print("api: ok")
        return 0 if process_ok else 1
    print(f"api: status {status} {body.strip()}")
    return 1


def cmd_list(ns: argparse.Namespace) -> int:
    if ns.name:
        return _print_container_detail(ns, ns.name)
    status, body = _api_get("/containers", _api_url(ns))
    if status != 200:
        print(body.strip() or f"http {status}", file=sys.stderr)
        return 1
    rows = json.loads(body)
    _print_table(
        rows,
        [("name", "name"), ("id", "id"), ("service", "service"), ("index", "index"), ("status", "status")],
    )
    return 0


def _print_container_detail(ns: argparse.Namespace, name: str) -> int:
    status, body = _api_get(f"/containers/{urllib.parse.quote(name)}", _api_url(ns))
    if status == 404:
        print(f"container {name!r} not found", file=sys.stderr)
        return 1
    if status != 200:
        print(body.strip() or f"http {status}", file=sys.stderr)
        return 1
    detail = json.loads(body)
    fields = [
        "name",
        "id",
        "service",
        "index",
        "status",
        "state",
        "image",
        "created",
        "cpu_percent",
        "memory_bytes",
    ]
    width = max(len(f) for f in fields)
    for field in fields:
        print(f"{field.ljust(width)}  {detail.get(field)}")
    labels = detail.get("labels") or {}
    if labels:
        print("labels:")
        for key in sorted(labels):
            print(f"  {key}={labels[key]}")
    return 0


def cmd_log(ns: argparse.Namespace) -> int:
    path = f"/containers/{urllib.parse.quote(ns.name)}/logs?tail={int(ns.tail)}"
    status, body = _api_get(path, _api_url(ns))
    if status == 404:
        print(f"container {ns.name!r} not found", file=sys.stderr)
        return 1
    if status != 200:
        print(body.strip() or f"http {status}", file=sys.stderr)
        return 1
    sys.stdout.write(body)
    if body and not body.endswith("\n"):
        sys.stdout.write("\n")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scaler",
        description="Start/stop the Docker autoscaler orchestrator and inspect managed containers.",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("SCALER_API_URL", DEFAULT_API_URL),
        help=f"orchestrator API base URL (default: {DEFAULT_API_URL})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("start", help="start the orchestrator in the background")
    sub.add_parser("stop", help="stop the background orchestrator")
    sub.add_parser("health", help="check process + API health")

    list_p = sub.add_parser("list", help="list managed containers, or show one by name")
    list_p.add_argument("name", nargs="?", help="container name (optional)")

    log_p = sub.add_parser("log", aliases=["logs"], help="print logs for a managed container")
    log_p.add_argument("name", help="container name")
    log_p.add_argument("--tail", type=int, default=200, help="number of log lines (default: 200)")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(argv)
    commands = {
        "start": cmd_start,
        "stop": cmd_stop,
        "health": cmd_health,
        "list": cmd_list,
        "log": cmd_log,
        "logs": cmd_log,
    }
    return commands[ns.command](ns)


if __name__ == "__main__":
    raise SystemExit(main())
