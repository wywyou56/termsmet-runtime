"""Small shared execution/evidence helpers, independent of the HW7 harness."""

import asyncio
import hashlib
import json
import math
import os
import signal
import sqlite3
import subprocess
import time
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "list_templates", "propose_agreement", "list_jobs", "get_job",
    "counter_agreement", "accept_agreement", "fund_job", "submit_delivery",
    "get_result", "challenge_result", "retrieve_delivery",
}
FLAGS = [
    "--bare", "--setting-sources", "--strict-mcp-config", "--tools",
    "--allowedTools", "--permission-mode", "--no-chrome",
    "--disable-slash-commands", "--no-session-persistence", "--effort",
    "--output-format", "--verbose",
]


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("duration must be positive and finite")
    return number


def tool_limit(value):
    number = int(value)
    if number < 1:
        raise ValueError("tool limit must be a positive integer")
    return number


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_text(path):
    # Path.read_text() would translate CRLF and change the agreed source hash.
    return Path(path).read_bytes().decode("utf-8")


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append(path, value):
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(value, ensure_ascii=False) + "\n")
        output.flush()


def records(path):
    if not path.exists():
        return []
    # Readers may race an append. Only complete lines have been published.
    return [json.loads(line) for line in path.read_text().split("\n")[:-1] if line]


def prepare_output(path):
    path = Path(path).absolute()
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise ValueError("output must be an absent or empty, nonsymlink directory")
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def base_environment():
    names = ("PATH", "HOME", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT")
    return {name: os.environ[name] for name in names if name in os.environ}


def client_environment():
    env = base_environment()
    if os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
    env["ANTHROPIC_BASE_URL"] = os.environ.get("ANTHROPIC_BASE_URL", "https://parley.api.mit.edu")
    env["MCP_CONNECTION_NONBLOCKING"] = "false"
    return env


def proxy_environment():
    # MCP config env overlays the Claude environment rather than replacing it.
    return {**base_environment(), "ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": "",
            "ANTHROPIC_BASE_URL": "", "MCP_CONNECTION_NONBLOCKING": ""}


def redact(value):
    secret = os.environ.get("ANTHROPIC_API_KEY")
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]") if secret else value
    if isinstance(value, dict):
        return {redact(key): redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def contains_credential(value):
    return redact(value) != value


async def with_signals(coroutine):
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    try:
        return await coroutine
    finally:
        loop.remove_signal_handler(signal.SIGTERM)


def inventory(names, prefix=""):
    return (isinstance(names, list) and len(names) == len(TOOLS)
            and all(isinstance(name, str) for name in names)
            and set(names) == {prefix + name for name in TOOLS})


def proxy_parameters(args, out, role):
    return [
        str(ROOT / "coldstart" / "mcp_proxy.py"),
        "--identity", role, "--out", str(out), "--runtime-dir", str(ROOT),
        "--python", str(Path(args.python).absolute()),
        "--db", str(out / ".work" / "live.sqlite"),
        "--review-seconds", str(args.review_seconds),
        "--first-submit-minutes", str(args.first_submit_minutes),
        "--tool-limit", str(args.tool_limit), "--startup-seconds", str(args.startup_seconds),
    ]


def signal_group(group, sig):
    if group == os.getpgrp():
        raise ValueError("refusing to signal the operator's process group")
    try:
        os.killpg(group, sig)
    except ProcessLookupError:
        pass


def command_output(command, cwd, timeout=5):
    """Bound metadata commands and kill their own descendants on timeout."""
    process = subprocess.Popen(command, cwd=cwd, env=base_environment(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
        if process.returncode:
            raise ValueError("metadata command failed: " + command[-1])
        return stdout.decode("utf-8").strip()
    finally:
        signal_group(process.pid, signal.SIGKILL)
        if process.poll() is None:
            process.wait(timeout=2)
        process.stdout.close()
        process.stderr.close()


def snapshot(live, final, timeout=5):
    """Never open a missing live DB in a mode that could create one."""
    if not live.exists() or live.stat().st_size == 0:
        return {"status": "unavailable", "reason": "server did not create a nonempty database"}
    partial = final.with_name(final.name + ".partial")
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if time.monotonic() >= deadline:
            raise TimeoutError("SQLite backup exceeded its deadline")

    try:
        with closing(sqlite3.connect(live.as_uri() + "?mode=ro", uri=True, timeout=1)) as source:
            with closing(sqlite3.connect(partial, timeout=1)) as destination:
                source.backup(destination, pages=128, progress=progress, sleep=0.05)
        partial.replace(final)
        return {"status": "available", "path": final.name, "sha256": digest(final.read_bytes())}
    except (OSError, sqlite3.Error, TimeoutError) as exc:
        return {"status": "failed", "reason": redact(str(exc)), "partial_path": partial.name}
