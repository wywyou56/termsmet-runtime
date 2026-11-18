"""Independent HW9 main-run checker (Sheila S2).

Reads only saved evidence from one launcher output directory: ``manifest.json``,
client stdout JSONL, MCP JSONL, proxy control JSONL and the ``termsmet.sqlite``
snapshot opened read-only. It never imports or calls the service, never edits
the run's files, and never advances a job. Criteria: ``coldstart/criteria.md``.
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROLES = ("buyer", "provider")
DELIVERY_FIELDS = {"order_id", "quantity", "unit_price_cents", "total_cents"}
REPORT_FIELDS = {"job_id", "order_count", "total_quantity", "total_amount_usd", "approval_orders"}
USD = re.compile(r"^(0|[1-9]\d*)\.\d{2}$")
FENCE = re.compile(r"^```(?:json|JSON)?[ \t]*\r?\n(.*?)\r?\n?```$", re.DOTALL)
TOOL_LIMIT = 60
WALL_SECONDS = 900


class Incomplete(Exception):
    """Evidence is missing, malformed or contradictory."""


def outcome(status, reason, **details):
    return {"status": status, "reason": reason, **details}


def is_int(value):
    return type(value) is int


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Incomplete(f"missing {path.name}") from exc
    except (OSError, ValueError) as exc:
        raise Incomplete(f"unreadable {path.name}: {exc}") from exc


def read_jsonl(path):
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise Incomplete(f"missing {path.name}") from exc
    rows = []
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError as exc:
            raise Incomplete(f"malformed {path.name} line {number}") from exc
    return rows


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def payload_of(message):
    """Return (payload, protocol_error) for a JSON-RPC response to tools/call."""
    if "error" in message:
        return None, message["error"]
    result = message.get("result")
    if not isinstance(result, dict):
        return None, "response without result"
    if result.get("isError"):
        return None, result.get("content")
    payload = result.get("structuredContent")
    if payload is None:
        try:
            payload = json.loads(result["content"][0]["text"])
        except (KeyError, IndexError, TypeError, ValueError):
            return None, "unparseable tool result"
    return payload, None


def tool_calls(rows):
    """Pair each tools/call request with the next response carrying its ID."""
    calls, pending = [], {}
    for row in rows:
        message = row.get("message")
        if not isinstance(message, dict):
            raise Incomplete("MCP record without message")
        key = json.dumps(message.get("id"))
        if row.get("direction") == "request" and message.get("method") == "tools/call":
            params = message.get("params") or {}
            call = {"tool": params.get("name"), "arguments": params.get("arguments") or {},
                    "request_ts": row.get("timestamp"), "response_ts": None,
                    "payload": None, "protocol_error": None, "business_error": None}
            pending[key] = call
            calls.append(call)
        elif row.get("direction") == "response" and "id" in message and key in pending:
            call = pending.pop(key)
            call["response_ts"] = row.get("timestamp")
            call["payload"], call["protocol_error"] = payload_of(message)
            if isinstance(call["payload"], dict) and isinstance(call["payload"].get("error"), dict):
                call["business_error"] = call["payload"]["error"]
    return calls


def ok(call):
    return (call["response_ts"] is not None and call["protocol_error"] is None
            and call["business_error"] is None and isinstance(call["payload"], dict))


def delivery_problems(delivery, expected):
    if not isinstance(delivery, list):
        return ["delivery is not a list"]
    problems, seen = [], Counter()
    for index, record in enumerate(delivery):
        if not isinstance(record, dict) or set(record) != DELIVERY_FIELDS:
            problems.append(f"record {index} does not have exactly the four delivery fields")
            continue
        if type(record["order_id"]) is not str:
            problems.append(f"record {index} order_id is not a string")
            continue
        for field in ("quantity", "unit_price_cents", "total_cents"):
            if not is_int(record[field]):
                problems.append(f"{record['order_id']} {field} is not an integer")
        seen[record["order_id"]] += 1
    expected_by_id = {record["order_id"]: record for record in expected}
    for order_id, count in seen.items():
        if count > 1:
            problems.append(f"duplicate order {order_id}")
        if order_id not in expected_by_id:
            problems.append(f"unexpected order {order_id}")
    for order_id in expected_by_id:
        if order_id not in seen:
            problems.append(f"missing order {order_id}")
    if not problems:
        for record in delivery:
            if record != expected_by_id[record["order_id"]]:
                problems.append(f"{record['order_id']} values differ from expected")
    return problems


def reject_duplicates(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate JSON key")
    return dict(pairs)


def parse_report(text):
    """Exactly one JSON object, optionally in one enclosing Markdown JSON fence."""
    if not isinstance(text, str):
        raise ValueError("final result is not text")
    body = text.strip()
    fenced = FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    value = json.loads(body, object_pairs_hook=reject_duplicates)
    if not isinstance(value, dict):
        raise ValueError("final result is not a JSON object")
    return value


def report_problems(report, expected, job_id):
    if set(report) != REPORT_FIELDS:
        return [f"report fields are {sorted(report)}, expected {sorted(REPORT_FIELDS)}"]
    problems = []
    if report["job_id"] != job_id:
        problems.append("job_id does not match the evaluated job")
    for field in ("order_count", "total_quantity"):
        if not is_int(report[field]):
            problems.append(f"{field} is not an integer")
        elif report[field] != expected[field]:
            problems.append(f"{field} is {report[field]}, expected {expected[field]}")
    amount = report["total_amount_usd"]
    if not isinstance(amount, str) or not USD.match(amount):
        problems.append("total_amount_usd is not a two-decimal string")
    elif amount != expected["total_amount_usd"]:
        problems.append(f"total_amount_usd is {amount}, expected {expected['total_amount_usd']}")
    approvals = report["approval_orders"]
    if not isinstance(approvals, list):
        return problems + ["approval_orders is not a list"]
    observed = {}
    for item in approvals:
        if (not isinstance(item, dict) or set(item) != {"order_id", "total_amount_usd"}
                or type(item["order_id"]) is not str or not isinstance(item["total_amount_usd"], str)
                or not USD.match(item["total_amount_usd"])):
            problems.append("approval_orders entry has the wrong shape or types")
            continue
        if item["order_id"] in observed:
            problems.append(f"approval order {item['order_id']} is duplicated")
        observed[item["order_id"]] = item["total_amount_usd"]
    wanted = {item["order_id"]: item["total_amount_usd"] for item in expected["approval_orders"]}
    if observed != wanted:
        problems.append(f"approval_orders {observed} differ from expected {wanted}")
    return problems


def final_result(rows):
    """Last stream-json result event: (text, received_at, event, count)."""
    results = []
    for row in rows:
        try:
            event = json.loads(row.get("line", ""))
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            results.append((event.get("result"), row.get("received_at"), event))
    if not results:
        return None, None, None, 0
    text, received, event = results[-1]
    return text, received, event, len(results)


def load_evidence(run):
    evidence = {"manifest": read_json(run / "manifest.json")}
    for role in ROLES:
        evidence[f"stdout_{role}"] = read_jsonl(run / f"{role}.jsonl")
        evidence[f"calls_{role}"] = tool_calls(read_jsonl(run / f"mcp-{role}.jsonl"))
        evidence[f"control_{role}"] = read_jsonl(run / f"{role}-control.jsonl")
    return evidence


def load_snapshot(run):
    path = run / "termsmet.sqlite"
    if not path.is_file():
        raise Incomplete("missing termsmet.sqlite snapshot")
    # A completed backup is self-contained; read-only mode cannot create or modify it.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {}
        for table in ("jobs", "agreement_versions", "acceptances", "submissions",
                      "check_results", "challenges", "settlement_events"):
            tables[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
    return tables


def evaluated_job(db, report):
    job_ids = [job["job_id"] for job in db["jobs"]]
    if isinstance(report, dict) and report.get("job_id") in job_ids:
        return report["job_id"], "named by buyer report"
    if len(job_ids) == 1:
        return job_ids[0], "only job in snapshot"
    raise Incomplete(f"cannot identify one evaluated job among {len(job_ids)} jobs")


def check_c1(db, job, calls):
    version = job["current_version"]
    identities = {row["identity"] for row in db["acceptances"]
                  if row["job_id"] == job["job_id"] and row["version"] == version}
    if identities != set(ROLES):
        return outcome("failed", f"agreement v{version} accepted by {sorted(identities)}", version=version)
    missing = [role for role in ROLES if not any(
        ok(call) and call["tool"] == "accept_agreement" and call["arguments"].get("job_id") == job["job_id"]
        and call["arguments"].get("version") == version for call in calls[role])]
    if missing:
        return outcome("incomplete", f"no successful accept_agreement call logged for {missing}", version=version)
    return outcome("passed", f"buyer and provider both accepted agreement v{version}", version=version)


def check_c2(db, job_id):
    funding = [e for e in db["settlement_events"] if e["job_id"] == job_id and e["event_type"] == "SIMULATED_FUNDING"]
    if len(funding) != 1:
        return outcome("failed", f"{len(funding)} simulated funding events")
    submitted = [parse_time(s["submitted_at"]) for s in db["submissions"] if s["job_id"] == job_id]
    if submitted and parse_time(funding[0]["created_at"]) > min(submitted):
        return outcome("failed", "a submission precedes funding")
    return outcome("passed", "one simulated funding event, not after any submission",
                   funded_at=funding[0]["created_at"])


def check_c3(db, job, calls):
    job_id, current = job["job_id"], job["current_submission_version"]
    if current < 1:
        return outcome("failed", "no submission")
    submission = next((s for s in db["submissions"] if s["job_id"] == job_id
                       and s["submission_version"] == current), None)
    result = next((r for r in db["check_results"] if r["job_id"] == job_id
                   and r["submission_version"] == current), None)
    if submission is None or result is None:
        return outcome("incomplete", f"submission {current} or its check result is missing from the snapshot")
    if submission["submitted_by"] != "provider" or submission["agreement_version"] != job["current_version"]:
        return outcome("failed", "current submission is not a provider submission on the current agreement")
    if result["verdict"] != "PASS":
        return outcome("failed", f"current submission {current} verdict {result['verdict']}")
    logged = any(ok(call) and call["tool"] == "submit_delivery" and call["arguments"].get("job_id") == job_id
                 and call["payload"].get("submission_version") == current and call["payload"].get("verdict") == "PASS"
                 for call in calls["provider"])
    if not logged:
        return outcome("incomplete", f"provider MCP log lacks the PASS response for submission {current}")
    return outcome("passed", f"provider submission {current} has a persisted server PASS", submission_version=current)


def check_c4(db, job):
    events = Counter(e["event_type"] for e in db["settlement_events"] if e["job_id"] == job["job_id"])
    if job["status"] != "RELEASED":
        return outcome("failed", f"job status {job['status']}")
    if events["SIMULATED_RELEASE"] != 1 or events["SIMULATED_REFUND"] != 0:
        return outcome("failed", f"release/refund events {dict(events)}")
    release = next(e for e in db["settlement_events"] if e["job_id"] == job["job_id"]
                   and e["event_type"] == "SIMULATED_RELEASE")
    if not job["review_deadline"]:
        return outcome("incomplete", "released job has no stored review deadline")
    if parse_time(release["created_at"]) < parse_time(job["review_deadline"]):
        return outcome("failed", "release recorded before the review deadline")
    return outcome("passed", "exactly one simulated release after the review deadline, no refund",
                   released_at=release["created_at"], review_deadline=job["review_deadline"])


def first_retrieval(calls, job_id):
    return next((call for call in calls["buyer"] if ok(call) and call["tool"] == "retrieve_delivery"
                 and call["arguments"].get("job_id") == job_id and "delivery" in call["payload"]), None)


def check_c5(retrieval, expected_delivery):
    if retrieval is None:
        return outcome("failed", "no successful retrieve_delivery response for the job in the buyer MCP log")
    problems = delivery_problems(retrieval["payload"]["delivery"], expected_delivery)
    if problems:
        return outcome("failed", "retrieved delivery differs from the independent expectation", problems=problems)
    return outcome("passed", "retrieved delivery equals the independent expected delivery",
                   retrieved_at=retrieval["response_ts"])


def check_c6(report, report_error, received_at, retrieval, expected_report, job_id):
    if report is None:
        return outcome("failed", f"buyer final answer is not one JSON object: {report_error}")
    problems = report_problems(report, expected_report, job_id)
    if retrieval is None:
        problems.append("no successful retrieval precedes the report")
    elif not isinstance(received_at, (int, float)) or received_at <= retrieval["response_ts"]:
        problems.append("final report was not received after the retrieval response")
    if problems:
        return outcome("failed", "buyer report does not satisfy C6", problems=problems)
    return outcome("passed", "buyer report matches the independent expected report and follows retrieval",
                   report_received_at=received_at)


def check_c7(manifest, controls):
    problems = []
    if not isinstance(manifest.get("manual_help"), str) or not manifest["manual_help"].strip():
        problems.append("manual help is not disclosed")
    agents = manifest.get("agents") or {}
    for role in ROLES:
        state = agents.get(role) or {}
        attempts, blocked = state.get("tool_attempts"), state.get("blocked_calls")
        if not is_int(attempts) or not is_int(blocked):
            return outcome("incomplete", f"{role} call counts missing from manifest")
        if attempts > TOOL_LIMIT or blocked:
            problems.append(f"{role} attempted {attempts} calls with {blocked} blocked")
        if any(row.get("event") == "tool_budget_exhausted" for row in controls[role]):
            problems.append(f"{role} exhausted its call budget")
    exits = [(agents.get(role) or {}).get("exit_observed_at") for role in ROLES]
    if not all(isinstance(value, (int, float)) for value in exits) or not isinstance(manifest.get("started_at"), (int, float)):
        return outcome("incomplete", "client exit times missing from manifest")
    span = max(exits) - manifest["started_at"]
    if span > WALL_SECONDS or manifest.get("execution_status") == "wall_timeout":
        problems.append(f"client execution span {span:.1f}s or wall-cap failure")
    if problems:
        return outcome("failed", "; ".join(problems), client_span_seconds=span)
    return outcome("passed", "manual help disclosed; call and time limits respected",
                   client_span_seconds=span, manual_help=manifest["manual_help"])


def friction(evidence, db, job_id):
    data = {"jobs_created": len(db["jobs"]), "roles": {}}
    for role in ROLES:
        calls = evidence[f"calls_{role}"]
        state = (evidence["manifest"].get("agents") or {}).get(role) or {}
        errors = [{"tool": c["tool"], "code": c["business_error"].get("code"),
                   "message": c["business_error"].get("message")} for c in calls if c["business_error"]]
        text, received, event, count = final_result(evidence[f"stdout_{role}"])
        data["roles"][role] = {
            "tool_calls_logged": len(calls), "tool_counts": dict(Counter(c["tool"] for c in calls)),
            "tool_attempts": state.get("tool_attempts", "N/A"), "blocked_calls": state.get("blocked_calls", "N/A"),
            "unanswered_calls": sum(c["response_ts"] is None for c in calls),
            "protocol_errors": sum(c["protocol_error"] is not None for c in calls),
            "business_errors": errors, "business_error_counts": dict(Counter(e["code"] for e in errors)),
            "exit_code": state.get("exit_code", "N/A"),
            "elapsed_seconds": (state["exit_observed_at"] - state["started_at"]
                                if is_num(state.get("exit_observed_at")) and is_num(state.get("started_at")) else "N/A"),
            "total_cost_usd": state.get("total_cost_usd", "N/A"),
            "num_turns": event.get("num_turns", "N/A") if event else "N/A",
            "result_events": count, "final_result_text": text,
        }
    if job_id is not None:
        rows = [r for r in db["check_results"] if r["job_id"] == job_id]
        data["agreement_versions"] = sum(a["job_id"] == job_id for a in db["agreement_versions"])
        data["submissions"] = [{"submission_version": r["submission_version"], "verdict": r["verdict"],
                                "errors": json.loads(r["errors_json"])} for r in
                               sorted(rows, key=lambda r: r["submission_version"])]
        first_fail = next((r["submission_version"] for r in data["submissions"] if r["verdict"] == "FAIL"), None)
        data["repairs"] = (sum(r["submission_version"] > first_fail and r["verdict"] != "UNKNOWN"
                               for r in data["submissions"]) if first_fail else 0)
        data["unknown_verdicts"] = sum(r["verdict"] == "UNKNOWN" for r in data["submissions"])
        data["challenges"] = sum(c["job_id"] == job_id for c in db["challenges"])
    return data


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(run, expected_delivery, expected_report):
    checks = {f"C{n}": outcome("incomplete", "not evaluated") for n in range(1, 8)}
    result = {"schema_version": 1, "run": run.name, "checked_at": time.time(),
              "checker": "coldstart/check_run.py", "service_calls_made": 0, "checks": checks}
    try:
        evidence = load_evidence(run)
    except Incomplete as exc:
        for key in checks:
            checks[key] = outcome("incomplete", str(exc))
        result.update(useful_result=False, evidence_error=str(exc))
        return result
    manifest = evidence["manifest"]
    result["launcher"] = {key: manifest.get(key) for key in (
        "kind", "execution_status", "runtime_commit", "working_tree_dirty", "model", "effort",
        "claude_version", "review_seconds", "first_submit_minutes", "wall_seconds", "tool_limit",
        "manual_help", "elapsed_seconds", "failures")}
    checks["C7"] = check_c7(manifest, {r: evidence[f"control_{r}"] for r in ROLES})
    if manifest.get("kind") != "launch":
        reason = f"run kind {manifest.get('kind')!r} is not a main cold-start run"
        for key in ("C1", "C2", "C3", "C4", "C5", "C6"):
            checks[key] = outcome("incomplete", reason)
        result.update(useful_result=False, evidence_error=reason)
        return result

    text, received_at, _, count = final_result(evidence["stdout_buyer"])
    report, report_error = None, None
    if text is None:
        report_error = "no final result event in buyer stdout"
    else:
        try:
            report = parse_report(text)
        except ValueError as exc:
            report_error = str(exc)
    result["buyer_report"] = {"result_events": count, "received_at": received_at,
                              "parsed": report, "parse_error": report_error}

    calls = {role: evidence[f"calls_{role}"] for role in ROLES}
    job_id = None
    try:
        db = load_snapshot(run)
        job_id, how = evaluated_job(db, report)
    except (Incomplete, sqlite3.Error) as exc:
        for key in ("C1", "C2", "C3", "C4"):
            checks[key] = outcome("incomplete", str(exc))
        db = None
        how = None
    retrieval = None
    if job_id is not None:
        job = next(j for j in db["jobs"] if j["job_id"] == job_id)
        result["evaluated_job"] = {"job_id": job_id, "selected": how, "status": job["status"],
                                   "agreement_version": job["current_version"],
                                   "current_submission_version": job["current_submission_version"]}
        checks["C1"] = check_c1(db, job, calls)
        checks["C2"] = check_c2(db, job_id)
        checks["C3"] = check_c3(db, job, calls)
        checks["C4"] = check_c4(db, job)
        retrieval = first_retrieval(calls, job_id)
        checks["C5"] = check_c5(retrieval, expected_delivery)
        expected = dict(expected_report, job_id=job_id)
        checks["C6"] = check_c6(report, report_error, received_at, retrieval, expected, job_id)
        result["expected_report_with_observed_job"] = expected
    else:
        for key in ("C5", "C6"):
            checks[key] = outcome("incomplete", "no evaluated job")
    result["useful_result"] = all(checks[f"C{n}"]["status"] == "passed" for n in range(1, 7))
    result["friction"] = friction(evidence, db, job_id) if db is not None else "N/A"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--expected-delivery", required=True, type=Path)
    parser.add_argument("--expected-report", required=True, type=Path)
    parser.add_argument("--output", type=Path, help="defaults to <run>/check.json; never overwritten")
    args = parser.parse_args(argv)
    if not args.run.is_dir():
        parser.error(f"{args.run} is not a run directory")
    expected_delivery = json.loads(args.expected_delivery.read_text(encoding="utf-8"))
    expected_report = json.loads(args.expected_report.read_text(encoding="utf-8"))
    result = evaluate(args.run, expected_delivery, expected_report)
    output = args.output or args.run / "check.json"
    with open(output, "x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    summary = {key: value["status"] for key, value in result["checks"].items()}
    print(json.dumps({"useful_result": result["useful_result"], "checks": summary, "output": str(output)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
