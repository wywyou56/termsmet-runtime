"""Narrow integrity tests for the published boundary/setup evidence verifier."""

import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1] / "evidence" / "hw9"
spec = importlib.util.spec_from_file_location("hw9_evidence_verify", PACKAGE / "verify.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class EvidencePackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="termsmet-evidence-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "package"
        shutil.copytree(PACKAGE, self.root, ignore=shutil.ignore_patterns("__pycache__"))

    def rehash(self, relative):
        path = self.root / relative
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["files"][relative] = digest
        manifest["origins"][relative]["published_sha256"] = digest
        manifest_path.write_text(json.dumps(manifest))

    def test_reviewed_package_verifies_offline(self):
        result = verifier.verify(self.root)
        self.assertEqual(result["boundary_runs_checked"], 2)
        self.assertGreaterEqual(result["preflights_checked"], 1)
        self.assertIn("unpublished databases were not independently inspected", result["state_evidence"])

    def test_tampered_file_hash_is_rejected(self):
        (self.root / "b1-v1" / "source.csv").write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verifier.verify(self.root)

    def test_missing_response_is_rejected_even_with_updated_file_hash(self):
        path = self.root / "b1-v1" / "mcp-buyer.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        call_id = next(row["message"]["id"] for row in rows if row["message"].get("method") == "tools/call")
        rows = [row for row in rows if not (row["direction"] == "response" and row["message"].get("id") == call_id)]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.rehash("b1-v1/mcp-buyer.jsonl")
        with self.assertRaisesRegex(ValueError, "matched response"):
            verifier.verify(self.root)

    def test_nonzero_state_export_is_rejected(self):
        path = self.root / "b1-v1" / "state.json"
        state = json.loads(path.read_text())
        state["table_counts"]["jobs"] = 1
        path.write_text(json.dumps(state))
        self.rehash("b1-v1/state.json")
        with self.assertRaisesRegex(ValueError, "exported business counts"):
            verifier.verify(self.root)

    def test_incorrect_structured_diagnostic_is_rejected(self):
        relative = "b1-v1/mcp-buyer.jsonl"
        path = self.root / relative
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        report_path = self.root / "b1-v1/probe.json"
        report = json.loads(report_path.read_text())
        payload = report["business_response"]
        payload["error"]["details"]["missing_columns"] = ["Wrong"]
        for row in rows:
            result = row["message"].get("result", {})
            if result.get("structuredContent", {}).get("error"):
                result["structuredContent"] = payload
                result["content"][0]["text"] = json.dumps(payload)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        report_path.write_text(json.dumps(report))
        self.rehash(relative)
        self.rehash("b1-v1/probe.json")
        with self.assertRaisesRegex(ValueError, "structured diagnostic mismatch"):
            verifier.verify(self.root)

    def test_preflight_claim_without_actual_call_is_rejected(self):
        relative = "preflight-y2-04/claude/mcp-buyer.jsonl"
        path = self.root / relative
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows = [row for row in rows if row["message"].get("method") != "tools/call"]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        self.rehash(relative)
        with self.assertRaisesRegex(ValueError, "actual list_templates request"):
            verifier.verify(self.root)


if __name__ == "__main__":
    unittest.main()
