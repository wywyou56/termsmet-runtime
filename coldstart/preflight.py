"""Unscored actual-SDK connectivity and one restricted Claude tool check."""

import argparse
import asyncio
import json
import shutil
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import launch
from ._support import (
    ROOT, base_environment, digest, inventory, prepare_output, proxy_environment, proxy_parameters,
    records, redact, snapshot, with_signals, write_json,
)


async def sdk_worker(out):
    """Official SDK work, isolated because SDK teardown can shield cancellation."""
    config = json.loads((out / "sdk-config.json").read_text())
    timeout = config["startup_seconds"]
    record = {"started_at": time.time(), "passed": False, "steps": []}
    write_json(out / "sdk-worker.json", record)
    # The SDK starts its transport child in a new session. Register before exec
    # so the supervisor can also stop a child that never initializes the SDK.
    register = (
        "import json,os,sys,time\n"
        "with open(sys.argv[1], 'a') as f:\n"
        " f.write(json.dumps({'timestamp':time.time(),'event':'proxy_started',"
        "'pid':os.getpid(),'pgid':os.getpgrp()})+'\\n')\n"
        "os.execv(sys.argv[2],sys.argv[2:])\n"
    )
    try:
        async with asyncio.timeout(timeout * 6):
            async with AsyncExitStack() as stack:
                sessions = {}
                for role in ("buyer", "provider"):
                    streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                        command=config["python"], args=["-c", register, str(out / f"{role}-control.jsonl"),
                                                      config["python"], *config["roles"][role]],
                        cwd=ROOT, env=proxy_environment(),
                    )))
                    client = await stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=timeout))
                    await asyncio.wait_for(client.initialize(), timeout)
                    tools = (await asyncio.wait_for(client.list_tools(), timeout)).tools
                    names = [tool.name for tool in tools]
                    if not inventory(names):
                        raise ValueError("SDK tool inventory is not exactly the eleven TermsMet tools")
                    (out / f".{role}-inventory-ok").touch()
                    record["steps"].append({"role": role, "initialized": True, "tools": names})
                    write_json(out / "sdk-worker.json", record)
                    sessions[role] = client

                async def call(role, tool, arguments):
                    result = await asyncio.wait_for(sessions[role].call_tool(tool, arguments), timeout)
                    if result.is_error or not isinstance(result.structured_content, dict) or "error" in result.structured_content:
                        raise ValueError("SDK setup tool failed: " + tool)
                    return result.structured_content

                source = "Order,Units,Price\nSETUP-19,2,$4.125\n"
                proposal = await call("buyer", "propose_agreement", {
                    "template_id": "order_extraction_v1", "source_csv": source,
                })
                job = await call("provider", "get_job", {"job_id": proposal["job_id"]})
                if job["source_csv"] != source or job["status"] != "PROPOSED" or job["current_submission_version"] != 0:
                    raise ValueError("provider did not observe the buyer's unchanged shared-state proposal")
                record.update(passed=True, shared_job_id=proposal["job_id"], source_sha256=digest(source.encode("utf-8")))
    except asyncio.CancelledError:
        record.update(status="interrupted", passed=False)
    except Exception as exc:
        record.update(status="failed", reason=redact(str(exc)), exception_type=type(exc).__name__)
    finally:
        record.setdefault("status", "passed" if record["passed"] else "failed")
        write_json(out / "sdk-worker.json", record)
    return 0 if record["passed"] else 1


async def sdk_check(args, out):
    """Enforce the SDK stage deadline externally, including SDK cleanup waits."""
    (out / ".work").mkdir()
    write_json(out / "sdk-config.json", {
        "python": str(Path(args.python).absolute()), "startup_seconds": args.startup_seconds,
        "roles": {role: proxy_parameters(args, out, role) for role in ("buyer", "provider")},
    })
    record = {"started_at": time.time(), "passed": False, "steps": []}
    process = None
    status = None
    try:
        with (out / "sdk-worker.stdout.log").open("wb") as stdout, (out / "sdk-worker.stderr.log").open("wb") as stderr:
            process = await asyncio.wait_for(asyncio.create_subprocess_exec(
                args.python, "-m", "coldstart.preflight", "--sdk-worker", str(out), cwd=ROOT,
                env=base_environment(), stdout=stdout, stderr=stderr, start_new_session=True,
            ), args.startup_seconds)
            await asyncio.wait_for(process.wait(), args.startup_seconds * 6)
    except asyncio.CancelledError:
        status = "interrupted"
    except asyncio.TimeoutError:
        status = "sdk_startup_timeout"
    except Exception as exc:
        record.update(reason=redact(str(exc)), exception_type=type(exc).__name__)
        status = "failed"
    finally:
        (out / ".stop-requested").touch()
        cleanup = await launch.stop_owned({"sdk": process} if process else {}, out, ("buyer", "provider"))
        if (out / "sdk-worker.json").exists():
            record.update(json.loads((out / "sdk-worker.json").read_text()))
        if status:
            record.update(status=status, passed=False)
        if process is None or process.returncode != 0:
            record["passed"] = False
        record["worker_exit_code"] = process.returncode if process else None
        record["cleanup"] = cleanup
        if record["cleanup"]["status"] == "completed":
            record["snapshot"] = snapshot(out / ".work" / "live.sqlite", out / "termsmet.sqlite")
            if record["snapshot"]["status"] == "available":
                try:
                    shutil.rmtree(out / ".work")
                except OSError as exc:
                    record["cleanup"] = {"status": "failed", "errors": [redact(str(exc))]}
                    record["passed"] = False
            else:
                record["passed"] = False
        else:
            record["snapshot"] = {"status": "unavailable", "reason": "cleanup was not confirmed"}
            record["passed"] = False
        record.setdefault("status", "passed" if record["passed"] else "failed")
        if not record["passed"] and record["status"] == "passed":
            record["status"] = "failed"
        record["finished_at"] = time.time()
        write_json(out / "sdk.json", redact(record))
    return record


def actual_template_exchange(out):
    rows = records(out / "mcp-buyer.jsonl")
    responses = {row["message"]["id"]: row["message"] for row in rows
                 if row["direction"] == "response" and "id" in row["message"]}
    calls = [row["message"] for row in rows if row["direction"] == "request"
             and row["message"].get("method") == "tools/call"]
    if len(calls) != 1 or calls[0].get("params", {}).get("name") != "list_templates":
        return False
    response = responses.get(calls[0].get("id"), {})
    result = response.get("result", {})
    return (not response.get("error") and not result.get("isError", False)
            and result.get("structuredContent") == {
                "templates": [{"template_id": "order_extraction_v1", "negotiable": {"repair_window_minutes": [5, 10]}}],
            })


async def run(args, out):
    record = {"kind": "setup_preflight_not_cold_start", "started_at": time.time(), "passed": False}
    try:
        sdk_out = prepare_output(out / "sdk")
        record["sdk"] = await sdk_check(args, sdk_out)
        if record["sdk"]["status"] == "interrupted":
            record["status"] = "interrupted"
            return 130
        if not record["sdk"]["passed"]:
            record["status"] = "sdk_failure"
            return 1
        client_out = prepare_output(out / "claude")
        manifest = launch.initial_manifest(args, "preflight_claude")
        result = await launch.execute(args, client_out, {
            "buyer": "Call the TermsMet list_templates tool exactly once, report the result, and stop. This is an unscored connection check.",
        }, manifest)
        record["claude"] = {"execution_status": manifest["execution_status"], "manifest": "claude/manifest.json"}
        record["list_templates_exchange_verified"] = actual_template_exchange(client_out)
        record["passed"] = result == 0 and record["list_templates_exchange_verified"]
        record["status"] = ("passed" if record["passed"] else
                            "missing_template_exchange" if result == 0 else manifest["execution_status"])
        return 0 if record["passed"] else (2 if result == 2 else 1)
    except asyncio.CancelledError:
        record["status"] = "interrupted"
        return 130
    except Exception as exc:
        record.update(status="failed", reason=redact(str(exc)), exception_type=type(exc).__name__)
        return 1
    finally:
        record["finished_at"] = time.time()
        write_json(out / "preflight.json", redact(record))


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--sdk-worker":
        return asyncio.run(sdk_worker(Path(sys.argv[2])))
    parser = argparse.ArgumentParser(description=__doc__)
    launch.add_options(parser)
    parser.set_defaults(wall_seconds=60)
    args = parser.parse_args()
    try:
        out = prepare_output(args.out)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    result = asyncio.run(with_signals(run(args, out)))
    record = json.loads((out / "preflight.json").read_text())
    print("Preflight:", record["status"], "(setup verification, not a cold-start result)")
    return result


if __name__ == "__main__":
    sys.exit(main())
