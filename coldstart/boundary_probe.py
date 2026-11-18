"""Scripted unsupported-header MCP observation; not an LLM cold-start test."""

import argparse
import asyncio
import csv
import importlib.metadata
import io
import json
import shutil
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .launch import stop_owned
from ._support import (
    ROOT, base_environment, command_output, digest, inventory, positive, prepare_output,
    proxy_environment, proxy_parameters, read_text, records, snapshot, with_signals, write_json,
)


REQUIRED = ["Order", "Units", "Price"]
TABLES = ("jobs", "agreement_versions", "acceptances", "submissions", "check_results",
          "challenges", "settlement_events")


def assess_diagnostic(payload, source):
    headers = next((row for row in csv.reader(io.StringIO(source, newline="")) if row), [])
    missing = [name for name in REQUIRED if name not in headers]
    error = payload.get("error") if isinstance(payload, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    missing_match = isinstance(details, dict) and details.get("missing_columns") == missing
    received_match = isinstance(details, dict) and details.get("received_columns") == headers
    if not isinstance(error, dict):
        classification = "no_business_error"
    elif missing_match and received_match:
        classification = "structured"
    elif isinstance(details, dict) and {"missing_columns", "received_columns"} & details.keys():
        classification = "partial_structured"
    else:
        classification = "generic"
    return {
        "classification": classification,
        "expected": {"required_columns": REQUIRED, "missing_columns": missing, "received_columns": headers},
        "observed_details": details, "missing_columns_identified": missing_match,
        "received_columns_identified": received_match,
    }


def inspect_state(path):
    if not path.exists():
        raise ValueError("snapshot unavailable; zero state changes cannot be verified")
    deadline = time.monotonic() + 2
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
        db.execute("PRAGMA query_only=ON")
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        counts = {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in TABLES}
        events = dict(db.execute("SELECT event_type, COUNT(*) FROM settlement_events GROUP BY event_type"))
    return {"read_only_verified": True, "table_counts": counts, "settlement_events": events,
            "zero_state_changes_verified": all(value == 0 for value in counts.values())}


async def worker(out):
    config = json.loads((out / "worker-config.json").read_text())
    timeout = config["startup_seconds"]
    result = {"completed": False, "started_at": time.time(), "request": config["request"]}
    write_json(out / "worker.json", result)
    # Register the SDK's separate transport session before executing the proxy.
    register = (
        "import json,os,sys,time\n"
        "with open(sys.argv[1], 'a') as f:\n"
        " f.write(json.dumps({'timestamp':time.time(),'event':'proxy_started',"
        "'pid':os.getpid(),'pgid':os.getpgrp()})+'\\n')\n"
        "os.execv(sys.argv[2],sys.argv[2:])\n"
    )
    try:
        async with stdio_client(StdioServerParameters(
            command=config["python"], args=["-c", register, str(out / "buyer-control.jsonl"),
                                           config["python"], *config["proxy_args"]],
            cwd=ROOT, env=proxy_environment(),
        )) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timeout) as client:
                await asyncio.wait_for(client.initialize(), timeout)
                tools = await asyncio.wait_for(client.list_tools(), timeout)
                result["inventory"] = [tool.model_dump(mode="json", by_alias=True, exclude_none=True) for tool in tools.tools]
                if not inventory([tool.name for tool in tools.tools]):
                    raise ValueError("inventory is not exactly the eleven TermsMet tools")
                (out / ".buyer-inventory-ok").touch()
                write_json(out / "worker.json", result)
                result["request_started_at"] = time.time()
                response = await asyncio.wait_for(client.call_tool(
                    config["request"]["name"], config["request"]["arguments"],
                ), timeout)
                result["response_received_at"] = time.time()
                result["sdk_response"] = response.model_dump(mode="json", by_alias=True, exclude_none=True)
                result["business_response"] = response.structured_content
                if response.is_error or not isinstance(response.structured_content, dict):
                    raise ValueError("request did not return an ordinary structured business response")
                result["completed"] = True
                write_json(out / "worker.json", result)
    except Exception as exc:
        result.update(completed=False, reason=str(exc), exception_type=type(exc).__name__)
    finally:
        result["finished_at"] = time.time()
        write_json(out / "worker.json", result)
    return 0 if result["completed"] else 1


def verify_exchange(out, expected, payload):
    for name in ("mcp-buyer.jsonl", "buyer-control.jsonl"):
        data = (out / name).read_bytes()
        if data and not data.endswith(b"\n"):
            raise ValueError("truncated boundary evidence: " + name)
    rows = records(out / "mcp-buyer.jsonl")
    requests = [row for row in rows if row["direction"] == "request"
                and row["message"].get("method") == "tools/call"]
    if len(requests) != 1 or requests[0]["message"].get("params") != expected:
        raise ValueError("expected exactly one unchanged boundary tool request")
    request = requests[0]["message"]
    if request.get("id") is None:
        raise ValueError("boundary request lacks its protocol ID")
    responses = [row for row in rows if row["direction"] == "response"
                 and row["message"].get("id") == request.get("id")]
    if len(responses) != 1 or "error" in responses[0]["message"]:
        raise ValueError("boundary request lacks one matched successful JSON-RPC response")
    response = responses[0]["message"].get("result", {})
    if response.get("isError") or response.get("structuredContent") != payload:
        raise ValueError("SDK business response does not match the recorded MCP response")
    control = records(out / "buyer-control.jsonl")
    if (sum(row["event"] == "tool_attempt" for row in control) != 1
            or sum(row["event"] == "tool_forwarded" for row in control) != 1
            or any(row["event"] in ("tool_budget_exhausted", "proxy_failure", "cleanup_failure") for row in control)):
        raise ValueError("proxy control evidence is incomplete or reports an execution failure")
    return {"request_id": request["id"], "request_at": requests[0]["timestamp"],
            "response_at": responses[0]["timestamp"], "matched": True}


async def run(args, out):
    report = {
        "kind": "scripted_mcp_boundary_not_cold_start", "schema_version": 1,
        "started_at": time.time(), "execution_status": "starting",
        "unsupported_input_correctly_rejected": None, "zero_state_changes_verified": None,
        "diagnostic_richness_observed": {"classification": "not_observed"},
        "snapshot": {"status": "unavailable", "reason": "no server database observed"},
        "cleanup": {"status": "not_started"},
    }
    write_json(out / "probe.json", report)
    process = None
    source = None
    work = out / ".work"
    try:
        source = read_text(args.source_csv)
        report["source_sha256"] = digest(source.encode("utf-8"))
        report["source_path"] = str(args.source_csv.absolute())
        report["runtime_commit"] = command_output(["git", "rev-parse", "HEAD"], ROOT)
        report["working_tree_dirty"] = bool(command_output(["git", "status", "--porcelain"], ROOT))
        try:
            baseline = command_output(["git", "rev-parse", "--verify", "refs/tags/hw9-docs-v0^{commit}"], ROOT)
        except ValueError:
            baseline = None
        report["baseline_tag"] = ({"name": "hw9-docs-v0", "commit": baseline,
                                   "matches_runtime": baseline == report["runtime_commit"]} if baseline else None)
        report["python"] = sys.version
        report["mcp_version"] = importlib.metadata.version("mcp")
        report["file_sha256"] = {name: digest((ROOT / name).read_bytes()) for name in (
            "coldstart/boundary_probe.py", "coldstart/boundary_criteria.md", "AGENT_GUIDE.md", "SOURCE_PROVENANCE.json",
        )}
        report["source_provenance"] = json.loads((ROOT / "SOURCE_PROVENANCE.json").read_text())
        report["settings"] = {"identity": "buyer", "review_seconds": 2, "first_submit_minutes": 5,
                              "tool_limit": 1, "startup_seconds": args.startup_seconds,
                              "worker_wall_seconds": args.startup_seconds * 3}
        request = {"name": "propose_agreement", "arguments": {
            "template_id": "order_extraction_v1", "source_csv": source,
        }}
        report["request"] = request
        (out / "source.csv").write_bytes(source.encode("utf-8"))
        work.mkdir()
        report["fresh_database_verified"] = not (work / "live.sqlite").exists()
        proxy_args = SimpleNamespace(python=args.python, review_seconds=2, first_submit_minutes=5,
                                     tool_limit=1, startup_seconds=args.startup_seconds)
        write_json(out / "worker-config.json", {
            "python": str(Path(args.python).absolute()), "startup_seconds": args.startup_seconds,
            "request": request, "proxy_args": proxy_parameters(proxy_args, out, "buyer"),
        })
        write_json(out / "probe.json", report)
        with (out / "worker.stdout.log").open("wb") as stdout, (out / "worker.stderr.log").open("wb") as stderr:
            process = await asyncio.wait_for(asyncio.create_subprocess_exec(
                args.python, "-m", "coldstart.boundary_probe", "--worker", str(out),
                cwd=ROOT, env=base_environment(), stdout=stdout, stderr=stderr, start_new_session=True,
            ), args.startup_seconds)
            await asyncio.wait_for(process.wait(), args.startup_seconds * 3)
        if process.returncode != 0:
            raise ValueError("SDK boundary worker did not complete successfully")
        report["execution_status"] = "completed"
    except asyncio.CancelledError:
        report["execution_status"] = "interrupted"
    except Exception as exc:
        report.update(execution_status="failed", reason=str(exc), exception_type=type(exc).__name__)
    finally:
        (out / ".stop-requested").touch()
        report["cleanup"] = await stop_owned({"worker": process} if process else {}, out, ("buyer",))
        try:
            if (out / "worker.json").exists():
                report["worker"] = json.loads((out / "worker.json").read_text())
                payload = report["worker"].get("business_response")
                if isinstance(payload, dict):
                    report["business_response"] = payload
                    report["unsupported_input_correctly_rejected"] = (
                        isinstance(payload.get("error"), dict) and payload["error"].get("code") == "INVALID_TERMS"
                    )
                    report["diagnostic_richness_observed"] = assess_diagnostic(payload, source)
            if report["execution_status"] == "completed":
                if not report.get("worker", {}).get("completed"):
                    raise ValueError("completed worker evidence unavailable")
                report["exchange"] = verify_exchange(out, request, report["business_response"])
            if report["cleanup"]["status"] != "completed":
                raise ValueError("cleanup was not confirmed; live state retained")
            report["snapshot"] = snapshot(work / "live.sqlite", out / "termsmet.sqlite")
            if report["snapshot"]["status"] == "available":
                report["state"] = inspect_state(out / "termsmet.sqlite")
                report["zero_state_changes_verified"] = report["state"]["zero_state_changes_verified"]
                shutil.rmtree(work)
            elif report["execution_status"] == "completed":
                raise ValueError("snapshot unavailable or failed; zero state changes cannot be verified")
        except Exception as exc:
            report.setdefault("reason", str(exc))
            if report["execution_status"] == "completed":
                report["execution_status"] = "failed"
        report["worker_exit_code"] = process.returncode if process else None
        report["finished_at"] = time.time()
        write_json(out / "probe.json", report)
    if report["execution_status"] == "interrupted":
        return 130
    if source is None:
        return 2
    return 0 if (report["execution_status"] == "completed" and report["unsupported_input_correctly_rejected"] is True
                 and report["zero_state_changes_verified"] is True) else 1


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        return asyncio.run(worker(Path(sys.argv[2])))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--startup-seconds", type=positive, default=15)
    parser.set_defaults(python=sys.executable)
    args = parser.parse_args()
    try:
        out = prepare_output(args.out)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    result = asyncio.run(with_signals(run(args, out)))
    report = json.loads((out / "probe.json").read_text())
    print(json.dumps({key: report[key] for key in (
        "execution_status", "unsupported_input_correctly_rejected", "zero_state_changes_verified", "diagnostic_richness_observed",
    )}, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
