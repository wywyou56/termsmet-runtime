"""Synthetic-evidence tests for the independent main-run checker.

All runs below are hand-built fixtures, never live Claude or cold-start evidence.
The snapshot schema is taken from server.storage only to build fixtures; the
checker itself does not import the service.
"""

import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from coldstart import check_run
from server.storage import SCHEMA

DATA = Path(__file__).resolve().parents[1] / "coldstart" / "data"
EXPECTED_DELIVERY = json.loads((DATA / "H9_expected_delivery.json").read_text(encoding="utf-8"))
EXPECTED_REPORT = json.loads((DATA / "H9_expected_report.json").read_text(encoding="utf-8"))
JOB = "job-synthetic"
T = "2026-11-18T10:00:{:02d}.000000Z"
GOOD_REPORT = {"job_id": JOB, "order_count": 8, "total_quantity": 48, "total_amount_usd": "610.76",
               "approval_orders": [{"order_id": "K307", "total_amount_usd": "125.00"},
                                   {"order_id": "K303", "total_amount_usd": "149.99"},
                                   {"order_id": "K304", "total_amount_usd": "100.80"}]}


def call(request_id, tool, arguments, payload, at):
    request = {"timestamp": at, "direction": "request", "message": {
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": tool, "arguments": arguments}}}
    response = {"timestamp": at + 0.1, "direction": "response", "message": {
        "jsonrpc": "2.0", "id": request_id, "result": {
            "content": [{"type": "text", "text": json.dumps(payload)}], "isError": False,
            "structuredContent": payload}}}
    return [request, response]


def scenario():
    """A complete valid synthetic transaction with one FAIL and one repair."""
    delivery = copy.deepcopy(EXPECTED_DELIVERY)
    return {
        "manifest": {"schema_version": 1, "kind": "launch", "started_at": 900.0, "execution_status": "completed",
                     "manual_help": "none reported", "model": "synthetic", "failures": [],
                     "agents": {"buyer": {"tool_attempts": 5, "blocked_calls": 0, "started_at": 900.5,
                                          "exit_observed_at": 1002.0, "exit_code": 0},
                                "provider": {"tool_attempts": 4, "blocked_calls": 0, "started_at": 900.5,
                                             "exit_observed_at": 1003.0, "exit_code": 0}}},
        "mcp_buyer": (call(1, "propose_agreement", {"template_id": "order_extraction_v1", "source_csv": "..."},
                           {"job_id": JOB, "version": 1, "status": "PROPOSED"}, 910.0)
                      + call(2, "accept_agreement", {"job_id": JOB, "version": 1},
                             {"job_id": JOB, "version": 1, "status": "COUNTERED"}, 920.0)
                      + call(3, "fund_job", {"job_id": JOB}, {"job_id": JOB, "status": "FUNDED", "simulated": True}, 930.0)
                      + call(4, "get_job", {"job_id": JOB}, {"job_id": JOB, "status": "IN_REVIEW"}, 980.0)
                      + call(5, "retrieve_delivery", {"job_id": JOB}, {"job_id": JOB, "delivery": delivery}, 1000.0)),
        "mcp_provider": (call(7, "list_jobs", {}, {"jobs": []}, 905.0)
                         + call(8, "accept_agreement", {"job_id": JOB, "version": 1},
                                {"job_id": JOB, "version": 1, "status": "ACCEPTED"}, 925.0)
                         + call(9, "submit_delivery", {"job_id": JOB, "delivery": delivery[1:]},
                                {"job_id": JOB, "submission_version": 1, "verdict": "FAIL"}, 940.0)
                         + call(10, "submit_delivery", {"job_id": JOB, "delivery": delivery},
                                {"job_id": JOB, "submission_version": 2, "verdict": "PASS"}, 960.0)),
        "buyer_result": json.dumps(GOOD_REPORT), "buyer_result_at": 1001.0,
        "provider_result": "Job released.",
        "db": {
            "job": {"status": "RELEASED", "current_version": 1, "current_submission_version": 2,
                    "review_deadline": T.format(30)},
            "acceptances": ["buyer", "provider"],
            "submissions": [(1, "FAIL"), (2, "PASS")],
            "events": [("SIMULATED_FUNDING", T.format(5)), ("SIMULATED_RELEASE", T.format(31))],
        },
        "control_extra": [],
    }


def write_run(root, spec, name="main-01", snapshot=True, constrained=True):
    run = root / name
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps(spec["manifest"]), encoding="utf-8")
    for role in ("buyer", "provider"):
        rows = spec[f"mcp_{role}"]
        (run / f"mcp-{role}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        lines = [{"received_at": 901.0, "line": json.dumps({"type": "system", "subtype": "init"})}]
        text = spec[f"{role}_result"]
        if text is not None:
            at = spec["buyer_result_at"] if role == "buyer" else 1002.5
            lines.append({"received_at": at, "line": json.dumps({"type": "result", "result": text, "num_turns": 9})})
        (run / f"{role}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
        control = [{"timestamp": 901.0, "event": "tool_attempt", "count": 1, "request_id": 1}]
        control += [row for row in spec["control_extra"] if row.get("role") == role]
        (run / f"{role}-control.jsonl").write_text("".join(json.dumps(r) + "\n" for r in control), encoding="utf-8")
    if snapshot:
        build_db(run / "termsmet.sqlite", spec["db"], constrained)
    return run


def build_db(path, db, constrained):
    with closing(sqlite3.connect(path)) as connection:
        for statement in SCHEMA:
            if not constrained and "settlement_events" in statement:
                if "CREATE TABLE" in statement:
                    connection.execute("CREATE TABLE settlement_events (job_id TEXT, event_type TEXT, "
                                       "simulated INTEGER, created_at TEXT)")
                continue
            connection.execute(statement)
        job = db["job"]
        connection.execute(
            "INSERT INTO jobs (job_id, current_version, current_submission_version, status, review_deadline, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (JOB, job["current_version"], job["current_submission_version"], job["status"],
             job["review_deadline"], T.format(0), T.format(31)))
        connection.execute("INSERT INTO agreement_versions VALUES (?, 1, '{}', 'csv', 'hash', 'order_extraction_v1.0', ?)",
                           (JOB, T.format(1)))
        for identity in db["acceptances"]:
            connection.execute("INSERT INTO acceptances VALUES (?, 1, ?, ?)", (JOB, identity, T.format(3)))
        for version, verdict in db["submissions"]:
            connection.execute("INSERT INTO submissions VALUES (?, ?, 1, '[]', 'provider', ?, ?)",
                               (JOB, version, T.format(10 + version), T.format(59)))
            connection.execute("INSERT INTO check_results VALUES (?, ?, 'hash', 'order_extraction_v1.0', ?, '[]', ?)",
                               (JOB, version, verdict, T.format(10 + version)))
        for event_type, at in db["events"]:
            connection.execute("INSERT INTO settlement_events VALUES (?, ?, 1, ?)", (JOB, event_type, at))
        connection.commit()


def hashes(run):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(run.iterdir())}


class CheckRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def evaluate(self, spec, **options):
        run = write_run(self.root, spec, **options)
        return check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)

    def statuses(self, result):
        return {key: value["status"] for key, value in result["checks"].items()}

    def test_valid_synthetic_run_passes_and_files_are_untouched(self):
        run = write_run(self.root, scenario())
        before = hashes(run)
        self.assertEqual(check_run.main(["--run", str(run), "--expected-delivery", str(DATA / "H9_expected_delivery.json"),
                                         "--expected-report", str(DATA / "H9_expected_report.json")]), 0)
        result = json.loads((run / "check.json").read_text(encoding="utf-8"))
        self.assertTrue(result["useful_result"])
        self.assertEqual(set(self.statuses(result).values()), {"passed"})
        self.assertEqual(result["friction"]["repairs"], 1)
        self.assertEqual(result["friction"]["roles"]["provider"]["tool_counts"]["submit_delivery"], 2)
        after = hashes(run)
        after.pop("check.json")
        self.assertEqual(before, after)
        with self.assertRaises(FileExistsError):
            check_run.main(["--run", str(run), "--expected-delivery", str(DATA / "H9_expected_delivery.json"),
                            "--expected-report", str(DATA / "H9_expected_report.json")])

    def test_fenced_report_is_accepted(self):
        spec = scenario()
        spec["buyer_result"] = "```json\n" + json.dumps(GOOD_REPORT, indent=2) + "\n```"
        self.assertTrue(self.evaluate(spec)["useful_result"])

    def test_wrong_total_fails_c6(self):
        spec = scenario()
        spec["buyer_result"] = json.dumps(dict(GOOD_REPORT, total_amount_usd="610.75"))
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C6"]["status"], "failed")
        self.assertFalse(result["useful_result"])

    def test_wrong_report_types_fail_c6(self):
        for change in ({"order_count": "8"}, {"total_quantity": True}, {"total_amount_usd": 610.76},
                       {"approval_orders": [{"order_id": "K303", "total_amount_usd": "149.99"}]}):
            with self.subTest(change=change):
                spec = scenario()
                spec["buyer_result"] = json.dumps(dict(GOOD_REPORT, **change))
                self.assertEqual(self.evaluate(spec, name=f"r{len(list(self.root.iterdir()))}")["checks"]["C6"]["status"], "failed")

    def test_boolean_or_float_delivery_values_fail_c5(self):
        for field, value in (("quantity", True), ("total_cents", 10000.0), ("unit_price_cents", "2500")):
            with self.subTest(field=field):
                spec = scenario()
                bad = copy.deepcopy(EXPECTED_DELIVERY)
                bad[0][field] = value
                spec["mcp_buyer"][-1]["message"]["result"]["structuredContent"]["delivery"] = bad
                result = self.evaluate(spec, name=f"d{len(list(self.root.iterdir()))}")
                self.assertEqual(result["checks"]["C5"]["status"], "failed")

    def test_missing_and_duplicate_orders_fail_c5(self):
        spec = scenario()
        bad = copy.deepcopy(EXPECTED_DELIVERY)
        bad[1] = copy.deepcopy(bad[0])
        spec["mcp_buyer"][-1]["message"]["result"]["structuredContent"]["delivery"] = bad
        problems = self.evaluate(spec)["checks"]["C5"]["problems"]
        self.assertIn("duplicate order K301", problems)
        self.assertIn("missing order K302", problems)

    def test_absent_retrieval_fails_c5_and_c6(self):
        spec = scenario()
        spec["mcp_buyer"] = spec["mcp_buyer"][:-2]
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C5"]["status"], "failed")
        self.assertEqual(result["checks"]["C6"]["status"], "failed")

    def test_denied_retrieval_is_not_a_retrieval(self):
        spec = scenario()
        spec["mcp_buyer"][-1]["message"]["result"]["structuredContent"] = {
            "error": {"code": "PERMISSION_DENIED", "message": "delivery available only after RELEASED"}}
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C5"]["status"], "failed")
        self.assertEqual(result["friction"]["roles"]["buyer"]["business_error_counts"], {"PERMISSION_DENIED": 1})

    def test_report_before_retrieval_fails_c6(self):
        spec = scenario()
        spec["buyer_result_at"] = 999.0
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C5"]["status"], "passed")
        self.assertEqual(result["checks"]["C6"]["status"], "failed")

    def test_missing_or_malformed_final_json_fails_c6(self):
        for text in (None, "Here is the report: " + json.dumps(GOOD_REPORT),
                     json.dumps(GOOD_REPORT) + "\n" + json.dumps(GOOD_REPORT), "[1, 2]",
                     '{"job_id": "a", "job_id": "b"}',
                     json.dumps({"job_id": JOB, "status": "incomplete", "reason": "no release"})):
            with self.subTest(text=text):
                spec = scenario()
                spec["buyer_result"] = text
                result = self.evaluate(spec, name=f"m{len(list(self.root.iterdir()))}")
                self.assertEqual(result["checks"]["C6"]["status"], "failed")
                self.assertFalse(result["useful_result"])

    def test_duplicate_release_fails_c4(self):
        spec = scenario()
        spec["db"]["events"].append(("SIMULATED_RELEASE", T.format(40)))
        result = self.evaluate(spec, constrained=False)
        self.assertEqual(result["checks"]["C4"]["status"], "failed")

    def test_refund_or_early_release_or_unreleased_fails_c4(self):
        cases = {"refund": lambda s: s["db"]["events"].append(("SIMULATED_REFUND", T.format(41))),
                 "early": lambda s: s["db"]["job"].update(review_deadline=T.format(45)),
                 "unreleased": lambda s: (s["db"]["job"].update(status="IN_REVIEW"), s["db"]["events"].pop())}
        for name, mutate in cases.items():
            with self.subTest(name=name):
                spec = scenario()
                mutate(spec)
                result = self.evaluate(spec, name=name, constrained=False)
                self.assertEqual(result["checks"]["C4"]["status"], "failed")

    def test_single_acceptance_fails_c1_and_missing_pass_fails_c3(self):
        spec = scenario()
        spec["db"]["acceptances"] = ["buyer"]
        spec["db"]["submissions"] = [(1, "FAIL"), (2, "FAIL")]
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C1"]["status"], "failed")
        self.assertEqual(result["checks"]["C3"]["status"], "failed")

    def test_funding_after_submission_fails_c2(self):
        spec = scenario()
        spec["db"]["events"][0] = ("SIMULATED_FUNDING", T.format(20))
        self.assertEqual(self.evaluate(spec)["checks"]["C2"]["status"], "failed")

    def test_missing_snapshot_is_incomplete(self):
        result = self.evaluate(scenario(), snapshot=False)
        for key in ("C1", "C2", "C3", "C4", "C5", "C6"):
            self.assertEqual(result["checks"][key]["status"], "incomplete")
        self.assertFalse(result["useful_result"])

    def test_missing_manifest_or_truncated_mcp_is_incomplete(self):
        run = write_run(self.root, scenario())
        (run / "manifest.json").unlink()
        result = check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)
        self.assertEqual(set(self.statuses(result).values()), {"incomplete"})
        run = write_run(self.root, scenario(), name="main-02")
        with open(run / "mcp-provider.jsonl", "a", encoding="utf-8") as handle:
            handle.write('{"timestamp": 1, "direction": "resp')
        self.assertEqual(set(self.statuses(check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)).values()),
                         {"incomplete"})

    def test_unanswered_pass_is_incomplete_not_passed(self):
        spec = scenario()
        spec["mcp_provider"] = spec["mcp_provider"][:-1]
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C3"]["status"], "incomplete")
        self.assertFalse(result["useful_result"])

    def test_preflight_trace_never_scores_as_transaction(self):
        spec = scenario()
        spec["manifest"]["kind"] = "preflight_claude"
        result = self.evaluate(spec)
        self.assertFalse(result["useful_result"])
        for key in ("C1", "C2", "C3", "C4", "C5", "C6"):
            self.assertEqual(result["checks"][key]["status"], "incomplete")

    def test_budget_exhaustion_and_undisclosed_help_fail_c7(self):
        spec = scenario()
        spec["manifest"]["agents"]["provider"].update(tool_attempts=61, blocked_calls=1)
        spec["control_extra"] = [{"timestamp": 950.0, "event": "tool_budget_exhausted", "count": 61,
                                  "request_id": 99, "role": "provider"}]
        spec["manifest"]["manual_help"] = ""
        result = self.evaluate(spec)
        self.assertEqual(result["checks"]["C7"]["status"], "failed")
        self.assertTrue(result["useful_result"])  # C7 is reported separately from C1-C6

    def test_report_naming_unknown_job_with_several_jobs_is_incomplete(self):
        run = write_run(self.root, scenario())
        with closing(sqlite3.connect(run / "termsmet.sqlite")) as connection:
            connection.execute("INSERT INTO jobs (job_id, status, created_at, updated_at) VALUES "
                               "('job-other', 'PROPOSED', ?, ?)", (T.format(0), T.format(0)))
            connection.commit()
        spec_report = dict(GOOD_REPORT, job_id="job-missing")
        lines = (run / "buyer.jsonl").read_text(encoding="utf-8").splitlines()
        last = json.loads(lines[-1])
        last["line"] = json.dumps({"type": "result", "result": json.dumps(spec_report)})
        lines[-1] = json.dumps(last)
        (run / "buyer.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)
        self.assertEqual(result["checks"]["C1"]["status"], "incomplete")
        self.assertFalse(result["useful_result"])

    def test_recorded_state_export_reproduces_snapshot_result(self):
        run = write_run(self.root, scenario())
        from_snapshot = check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)
        tables = check_run.export_tables(run / "termsmet.sqlite")
        (run / "termsmet.sqlite").unlink()
        (run / "state.json").write_text(json.dumps({"tables": tables}), encoding="utf-8")
        from_export = check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)
        self.assertEqual(self.statuses(from_export), self.statuses(from_snapshot))
        self.assertIn("recorded state export", from_export["state_source"])
        (run / "state.json").write_text(json.dumps({"tables": {"jobs": []}}), encoding="utf-8")
        self.assertEqual(check_run.evaluate(run, EXPECTED_DELIVERY, EXPECTED_REPORT)["checks"]["C1"]["status"],
                         "incomplete")

    def test_package_and_verify_roundtrip(self):
        from coldstart import package_main
        run = write_run(self.root, scenario())
        for role in ("buyer", "provider"):
            (run / f"prompt-{role}.md").write_text("synthetic prompt\n", encoding="utf-8")
        check_run.main(["--run", str(run), "--expected-delivery", str(DATA / "H9_expected_delivery.json"),
                        "--expected-report", str(DATA / "H9_expected_report.json")])
        package_root = self.root / "package"
        package_main.package(run, package_root / run.name)
        self.assertFalse((package_root / run.name / "termsmet.sqlite").exists())
        self.assertEqual(package_main.verify(package_root), 0)
        with open(package_root / run.name / "buyer.jsonl", "a", encoding="utf-8") as handle:
            handle.write("\n")
        with self.assertRaises(SystemExit):
            package_main.verify(package_root)

    def test_checker_does_not_import_service(self):
        source = (Path(check_run.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("from server", source)
        self.assertNotIn("import server", source)
        self.assertNotIn("mcp", source.split('"""', 2)[2].split("ROLES")[0])


if __name__ == "__main__":
    unittest.main()
