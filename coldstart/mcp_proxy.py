"""Byte-preserving MCP observer with an inventory gate and attempted-call cap."""

import argparse
import asyncio
import json
import os
import signal
import sys
import time
from pathlib import Path

# Claude executes this absolute script from an empty working directory.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from coldstart._support import append, base_environment, inventory, positive, tool_limit


async def serve(args):
    out, role = args.out, args.identity
    control = out / f"{role}-control.jsonl"

    def event(name, **fields):
        append(control, {"timestamp": time.time(), "event": name, **fields})

    def protocol(direction, message):
        append(out / f"mcp-{role}.jsonl", {
            "timestamp": time.time(), "direction": direction, "message": message,
        })

    if os.getpgrp() != os.getpid():
        os.setpgid(0, 0)
    event("proxy_started", pid=os.getpid(), pgid=os.getpgrp())
    if (out / ".stop-requested").exists():
        event("proxy_stopped", failed=False)
        return 0
    env = base_environment()
    env.update(TERMSMET_IDENTITY=role, TERMSMET_DB_PATH=str(args.db),
               TERMSMET_REVIEW_SECONDS=str(args.review_seconds),
               TERMSMET_FIRST_SUBMIT_MIN=str(args.first_submit_minutes), PYTHONUNBUFFERED="1")
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    child, transport, tasks = None, None, []
    failed = False
    try:
        with (out / f"server-{role}.stderr.log").open("ab") as err:
            child = await asyncio.wait_for(asyncio.create_subprocess_exec(
                args.python, "-m", "server.mcp_server", cwd=args.runtime_dir, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=err, limit=8 * 1024 * 1024,
            ), args.startup_seconds)
            event("server_started", pid=child.pid, pgid=os.getpgrp())
            reader = asyncio.StreamReader(limit=8 * 1024 * 1024)
            transport, _ = await asyncio.wait_for(loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer,
            ), args.startup_seconds)
            gate = out / f".{role}-inventory-ok"
            deadline = time.monotonic() + args.startup_seconds
            list_requests = set()

            async def incoming():
                count = 0
                while line := await reader.readline():
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("JSON-RPC message must be an object")
                    protocol("request", message)
                    if message.get("method") == "tools/list":
                        list_requests.add(message.get("id"))
                    if message.get("method") == "tools/call":
                        count += 1
                        event("tool_attempt", count=count, request_id=message.get("id"))
                        if count > args.tool_limit:
                            event("tool_budget_exhausted", count=count, request_id=message.get("id"))
                            raise ValueError("attempted-call cap exceeded")
                        while not gate.exists():
                            if stopped.is_set() or time.monotonic() >= deadline:
                                raise TimeoutError("inventory gate did not open before startup deadline")
                            await asyncio.sleep(0.02)
                        event("tool_forwarded", count=count, request_id=message.get("id"))
                    child.stdin.write(line)
                    await asyncio.wait_for(child.stdin.drain(), args.startup_seconds)

            async def outgoing():
                while line := await child.stdout.readline():
                    message = json.loads(line)
                    if not isinstance(message, dict):
                        raise ValueError("JSON-RPC message must be an object")
                    protocol("response", message)
                    if message.get("id") in list_requests:
                        list_requests.remove(message["id"])
                        result = message.get("result", {})
                        names = [tool.get("name") for tool in result.get("tools", [])]
                        if not inventory(names) or result.get("nextCursor"):
                            raise ValueError("unexpected server tool inventory")
                        event("server_inventory_verified", tools=names)
                    sys.stdout.buffer.write(line)
                    sys.stdout.buffer.flush()

            async def watchdog():
                while not stopped.is_set() and not (out / ".stop-requested").exists():
                    if not gate.exists() and time.monotonic() >= deadline:
                        raise TimeoutError("missing inventory before startup deadline")
                    await asyncio.sleep(0.02)

            tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing()),
                     asyncio.create_task(watchdog())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            if tasks[1] in done and tasks[0] not in done and not stopped.is_set() and not (out / ".stop-requested").exists():
                raise RuntimeError("server closed its output unexpectedly")
    except Exception as exc:
        failed = True
        event("proxy_failure", reason=str(exc), exception_type=type(exc).__name__)
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        if transport:
            transport.close()
        if child:
            if child.stdin:
                child.stdin.close()
            try:
                if child.returncode is None:
                    child.terminate()
                await asyncio.wait_for(child.wait(), 2)
            except asyncio.TimeoutError:
                child.kill()
                try:
                    await asyncio.wait_for(child.wait(), 2)
                except asyncio.TimeoutError:
                    failed = True
                    event("cleanup_failure", reason="server did not exit after KILL")
            except ProcessLookupError:
                pass
        event("proxy_stopped", failed=failed)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", choices=("buyer", "provider"), required=True)
    for name in ("out", "runtime-dir", "db"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--review-seconds", type=positive, required=True)
    parser.add_argument("--first-submit-minutes", type=positive, required=True)
    parser.add_argument("--tool-limit", type=tool_limit, required=True)
    parser.add_argument("--startup-seconds", type=positive, required=True)
    args = parser.parse_args()
    if not all(path.is_absolute() for path in (args.out, args.runtime_dir, args.db, Path(args.python))):
        parser.error("all runtime paths must be absolute")
    return asyncio.run(serve(args))


if __name__ == "__main__":
    raise SystemExit(main())
