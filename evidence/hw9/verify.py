"""Offline checks of the reviewed HW9 subset; never runs agents or opens a DB."""

import csv
import hashlib
import io
import json
import re
from pathlib import Path


TOOLS = {"list_templates", "propose_agreement", "list_jobs", "get_job", "counter_agreement",
         "accept_agreement", "fund_job", "submit_delivery", "get_result", "challenge_result", "retrieve_delivery"}
TABLES = {"jobs", "agreement_versions", "acceptances", "submissions", "check_results", "challenges", "settlement_events"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_lines(path):
    data = path.read_bytes()
    require(not data or data.endswith(b"\n"), "truncated evidence: " + path.name)
    return [json.loads(line) for line in data.decode("utf-8").splitlines()]


def exchange(path, name, arguments):
    rows = read_lines(path)
    calls = [row for row in rows if row["direction"] == "request" and row["message"].get("method") == "tools/call"]
    require(len(calls) == 1, "expected exactly one actual " + name + " request")
    call = calls[0]["message"]
    params = call.get("params", {})
    require(call.get("id") is not None and params.get("name") == name and params.get("arguments") == arguments,
            "request arguments/ID mismatch")
    replies = [row for row in rows if row["direction"] == "response" and row["message"].get("id") == call["id"]]
    require(len(replies) == 1, "missing or duplicate matched response")
    reply = replies[0]["message"]
    require("error" not in reply and not reply.get("result", {}).get("isError", False), "protocol/tool execution error")
    require(replies[0]["timestamp"] >= calls[0]["timestamp"], "response precedes request")
    result = reply["result"]
    payload = result.get("structuredContent")
    require(isinstance(payload, dict), "structured response missing")
    require(json.loads(result["content"][0]["text"]) == payload, "text/structured response mismatch")
    return payload


def verify(root):
    root = Path(root).resolve()
    manifest = read_json(root / "manifest.json")
    require(manifest["schema_version"] == 1, "unknown package schema")
    for name, expected in manifest["files"].items():
        path = (root / name).resolve()
        require(path.is_relative_to(root), "package path escapes evidence directory")
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, "hash mismatch: " + name)
        origin = manifest["origins"][name]
        require(origin["published_sha256"] == expected, "published origin hash mismatch")
        require(re.fullmatch(r"[0-9a-f]{64}", origin["source_sha256"]) is not None, "missing original provenance hash")

    reports = []
    for label, diagnostic in (("b1-v0", "generic"), ("b1-v1", "structured")):
        directory = root / label
        report = read_json(directory / "probe.json")
        source = (directory / "source.csv").read_bytes()
        require(hashlib.sha256(source).hexdigest() == report["source_sha256"], "source hash mismatch")
        require(report["working_tree_dirty"] is False and report["execution_status"] == "completed", "boundary execution not a clean completed run")
        require(report["unsupported_input_correctly_rejected"] is True and report["zero_state_changes_verified"] is True, "boundary outcomes incomplete")
        arguments = {"template_id": "order_extraction_v1", "source_csv": source.decode("utf-8")}
        payload = exchange(directory / "mcp-buyer.jsonl", "propose_agreement", arguments)
        require(payload == report["business_response"], "recorded boundary response mismatch")
        require(payload.get("error", {}).get("code") == "INVALID_TERMS", "unsupported input was not rejected")
        error = payload["error"]
        if diagnostic == "generic":
            require(error == {"code": "INVALID_TERMS", "message": "source_csv must contain valid, unambiguous order data"}, "generic baseline response changed")
        else:
            headers = next(csv.reader(io.StringIO(source.decode("utf-8"), newline="")))
            require(error.get("message") == "Required source columns are missing" and error.get("details") == {
                "missing_columns": ["Order", "Units", "Price"], "received_columns": headers,
            }, "structured diagnostic mismatch")
        require(report["diagnostic_richness_observed"]["classification"] == diagnostic, "diagnostic classification mismatch")
        state = read_json(directory / "state.json")
        require(state["kind"] == "recorded_read_only_snapshot_export", "state must be labeled as recorded evidence")
        require(state["source_snapshot_sha256"] == report["snapshot"]["sha256"], "snapshot provenance mismatch")
        counts = state["table_counts"]
        require(set(counts) == TABLES and all(type(value) is int and value == 0 for value in counts.values()), "nonzero or invalid exported business counts")
        require(counts == report["state"]["table_counts"] and state["settlement_events"] == {}, "state export/report mismatch")
        reports.append(report)
    before, after = reports
    for key in ("source_sha256", "request", "settings", "python", "mcp_version"):
        require(before[key] == after[key], "before/after client input mismatch: " + key)
    for name in ("coldstart/boundary_probe.py", "coldstart/boundary_criteria.md"):
        require(before["file_sha256"][name] == after["file_sha256"][name], "protected probe/criteria changed")
    require(before["worker"]["inventory"] == after["worker"]["inventory"], "boundary inventories differ")

    for label in manifest["preflights"]:
        directory = root / label
        summary = read_json(directory / "preflight.json")
        agent = read_json(directory / "claude" / "manifest.json")
        require(summary["passed"] is True and summary["list_templates_exchange_verified"] is True, "preflight summary did not pass")
        require(agent["execution_status"] == "completed" and agent["working_tree_dirty"] is False, "preflight execution not clean/completed")
        buyer = agent["agents"]["buyer"]
        require(buyer["inventory_verified"] is True and len(buyer["advertised_tools"]) == 11 and
                set(buyer["advertised_tools"]) == {"mcp__termsmet__" + name for name in TOOLS}, "preflight inventory mismatch")
        require((buyer["tool_attempts"], buyer["forwarded_calls"], buyer["blocked_calls"], buyer["exit_code"]) == (1, 1, 0, 0), "preflight attempts/exit mismatch")
        payload = exchange(directory / "claude" / "mcp-buyer.jsonl", "list_templates", {})
        require(payload == {"templates": [{"template_id": "order_extraction_v1", "negotiable": {"repair_window_minutes": [5, 10]}}]}, "preflight actual result mismatch")
        output = [json.loads(row["line"]) for row in read_lines(directory / "claude" / "buyer.jsonl")]
        finals = [event for event in output if event.get("type") == "result"]
        require(len(finals) == 1 and finals[0].get("is_error") is False and buyer["stdout_complete"] is True, "complete successful preflight output missing")
    return {"files_checked": len(manifest["files"]), "boundary_runs_checked": 2,
            "preflights_checked": len(manifest["preflights"]),
            "state_evidence": "recorded exports and snapshot hashes; unpublished databases were not independently inspected"}


if __name__ == "__main__":
    try:
        print(json.dumps(verify(Path(__file__).parent), indent=2))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit("Evidence verification failed: " + str(exc))
