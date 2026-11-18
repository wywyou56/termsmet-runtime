"""B1 is read statically only; live pre-freeze tests use unrelated source data."""

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from coldstart import boundary_probe as probe
from coldstart._support import ROOT, append, prepare_output, records


SOURCE = "sku,count,cost\r\nUNRELATED-8,2,$9.125\r\n"
GENERIC = {"error": {"code": "INVALID_TERMS", "message": "source_csv must contain valid, unambiguous order data"}}


class AssessmentTests(unittest.TestCase):
    def test_committed_b1_bytes_and_final_newline(self):
        self.assertEqual((ROOT / "coldstart/data/B1.csv").read_bytes(),
                         b"order_no,client,qty,unit_price\nB901,Synthetic-A,2,$3.125\nB902,Synthetic-B,1,$120.00\n")

    def test_generic_response_is_an_observation(self):
        result = probe.assess_diagnostic(GENERIC, SOURCE)
        self.assertEqual(result["classification"], "generic")
        self.assertFalse(result["missing_columns_identified"])
        self.assertFalse(result["received_columns_identified"])
        self.assertEqual(result["expected"]["received_columns"], ["sku", "count", "cost"])
        self.assertEqual(GENERIC["error"]["code"], "INVALID_TERMS")

    def test_structured_diagnostic_uses_only_synthetic_response_fixtures(self):
        payload = {"error": {"code": "INVALID_TERMS", "message": "Synthetic missing-column diagnostic", "details": {
            "missing_columns": ["Order", "Units", "Price"], "received_columns": ["sku", "count", "cost"],
        }}}
        original = json.dumps(payload, sort_keys=True)
        result = probe.assess_diagnostic(payload, SOURCE)
        self.assertEqual(result["classification"], "structured")
        self.assertTrue(result["missing_columns_identified"])
        self.assertTrue(result["received_columns_identified"])
        self.assertEqual(json.dumps(payload, sort_keys=True), original)

    def test_partial_and_incorrect_details_are_not_complete_diagnostics(self):
        for details in ({"missing_columns": ["Order", "Units", "Price"]},
                        {"missing_columns": ["Order"], "received_columns": ["sku", "count", "cost"]},
                        {"missing_columns": "Order,Units,Price", "received_columns": ["sku"]}):
            with self.subTest(details=details):
                result = probe.assess_diagnostic({"error": {"code": "INVALID_TERMS", "details": details}}, SOURCE)
                self.assertEqual(result["classification"], "partial_structured")
        self.assertEqual(probe.assess_diagnostic({"job_id": "unexpected"}, SOURCE)["classification"], "no_business_error")

    def test_read_only_counts_distinguish_zero_nonzero_and_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.sqlite"
            with self.assertRaises(ValueError):
                probe.inspect_state(missing)
            self.assertFalse(missing.exists())
            path = root / "state.sqlite"
            with sqlite3.connect(path) as db:
                for table in probe.TABLES:
                    db.execute(f"CREATE TABLE {table} (event_type TEXT)")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertTrue(probe.inspect_state(path)["zero_state_changes_verified"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
            with sqlite3.connect(path) as db:
                db.execute("INSERT INTO jobs VALUES ('unexpected job')")
                db.execute("INSERT INTO settlement_events VALUES ('SIMULATED_FUNDING')")
            state = probe.inspect_state(path)
            self.assertFalse(state["zero_state_changes_verified"])
            self.assertEqual(state["table_counts"]["jobs"], 1)
            self.assertEqual(state["settlement_events"], {"SIMULATED_FUNDING": 1})

    def test_partial_database_cannot_establish_zero_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "partial.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE jobs (job_id TEXT)")
            with self.assertRaises(sqlite3.OperationalError):
                probe.inspect_state(path)

    def test_response_fixture_must_match_protocol_id_and_complete_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            expected = {"name": "propose_agreement", "arguments": {"template_id": "order_extraction_v1", "source_csv": SOURCE}}
            protocol = out / "mcp-buyer.jsonl"
            append(protocol, {"timestamp": 1, "direction": "request", "message": {"jsonrpc": "2.0", "id": "probe-1", "method": "tools/call", "params": expected}})
            append(protocol, {"timestamp": 2, "direction": "response", "message": {"jsonrpc": "2.0", "id": "wrong-id", "result": {"structuredContent": GENERIC}}})
            control = out / "buyer-control.jsonl"
            append(control, {"timestamp": 1, "event": "tool_attempt"})
            append(control, {"timestamp": 1, "event": "tool_forwarded"})
            with self.assertRaises(ValueError):
                probe.verify_exchange(out, expected, GENERIC)
            text = protocol.read_text().replace('"wrong-id"', '"probe-1"')
            protocol.write_text(text)
            self.assertEqual(probe.verify_exchange(out, expected, GENERIC)["request_id"], "probe-1")
            protocol.write_text(text + '{"incomplete":')
            with self.assertRaises(ValueError):
                probe.verify_exchange(out, expected, GENERIC)


class ActualMCPProbeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="termsmet-y3-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "unrelated.csv"
        self.source.write_bytes(SOURCE.encode("utf-8"))

    async def asyncSetUp(self):
        asyncio.get_running_loop().slow_callback_duration = 5

    async def test_actual_generic_rejection_completes_and_preserves_exact_request(self):
        out = prepare_output(self.root / "actual")
        args = SimpleNamespace(source_csv=self.source, python=sys.executable, startup_seconds=4)
        self.assertEqual(await probe.run(args, out), 0)
        report = json.loads((out / "probe.json").read_text())
        self.assertEqual(report["execution_status"], "completed", report)
        self.assertTrue(report["unsupported_input_correctly_rejected"])
        self.assertTrue(report["zero_state_changes_verified"])
        self.assertEqual(report["diagnostic_richness_observed"]["classification"], "generic")
        self.assertEqual(report["business_response"], GENERIC)
        self.assertEqual((out / "source.csv").read_bytes(), self.source.read_bytes())
        self.assertEqual(report["source_sha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertTrue(report["fresh_database_verified"])
        self.assertEqual(len(report["worker"]["inventory"]), 11)
        self.assertTrue(report["exchange"]["matched"])
        calls = [row["message"] for row in records(out / "mcp-buyer.jsonl")
                 if row["direction"] == "request" and row["message"].get("method") == "tools/call"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["params"], {"name": "propose_agreement", "arguments": {
            "template_id": "order_extraction_v1", "source_csv": SOURCE,
        }})
        self.assertEqual(report["state"]["table_counts"], {table: 0 for table in probe.TABLES})
        self.assertEqual(report["state"]["settlement_events"], {})
        self.assertEqual(report["snapshot"]["status"], "available")
        self.assertFalse((out / ".work").exists())
        before = (out / "probe.json").read_bytes()
        process = subprocess.run([
            sys.executable, "-m", "coldstart.boundary_probe", "--source-csv", str(self.source), "--out", str(out),
        ], cwd=ROOT, capture_output=True, timeout=5)
        self.assertEqual(process.returncode, 2)
        self.assertEqual((out / "probe.json").read_bytes(), before)

    async def test_worker_timeout_is_bounded_and_does_not_manufacture_database(self):
        executable = self.root / "silent-worker"
        executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        executable.chmod(0o755)
        out = prepare_output(self.root / "timeout")
        args = SimpleNamespace(source_csv=self.source, python=str(executable), startup_seconds=0.4)
        started = time.monotonic()
        self.assertEqual(await probe.run(args, out), 1)
        self.assertLess(time.monotonic() - started, 6)
        report = json.loads((out / "probe.json").read_text())
        self.assertEqual(report["execution_status"], "failed")
        self.assertIsNone(report["unsupported_input_correctly_rejected"])
        self.assertIsNone(report["zero_state_changes_verified"])
        self.assertEqual(report["snapshot"]["status"], "unavailable")
        self.assertFalse((out / "termsmet.sqlite").exists())

    async def test_missing_source_is_setup_failure_with_unknown_state(self):
        out = prepare_output(self.root / "missing-source")
        args = SimpleNamespace(source_csv=self.root / "absent.csv", python=sys.executable, startup_seconds=4)
        self.assertEqual(await probe.run(args, out), 2)
        report = json.loads((out / "probe.json").read_text())
        self.assertEqual(report["execution_status"], "failed")
        self.assertIsNone(report["zero_state_changes_verified"])
        self.assertFalse((out / "termsmet.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
