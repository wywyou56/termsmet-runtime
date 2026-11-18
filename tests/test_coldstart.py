"""Deterministic execution tests; fake CLI runs are not live LLM preflight."""

import asyncio
import hashlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from coldstart import launch, preflight
from coldstart._support import (
    ROOT, base_environment, client_environment, command_output,
    prepare_output, proxy_parameters, read_text, records, signal_group, snapshot,
)


def options(out, executable, **overrides):
    values = dict(out=out, python=sys.executable, claude_bin=str(executable), model="synthetic-model",
                  effort="medium", review_seconds=2, first_submit_minutes=5, wall_seconds=10,
                  tool_limit=60, startup_seconds=4, manual_help="none; synthetic test")
    values.update(overrides)
    return SimpleNamespace(**values)


class InputAndBackupTests(unittest.TestCase):
    def test_templates_preserve_original_text_and_buyer_only_source(self):
        source = 'Order,Customer,Units,Price\r\n"€-19","{{literal}}",2,$3.125\r\n'
        guide = "guide\r\n{{literal guide}}\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            path.write_bytes(source.encode("utf-8"))
            self.assertEqual(read_text(path), source)
        prompts = launch.render_tasks("{{AGENT_GUIDE}}\nCSV={{SOURCE_CSV_JSON}}", "{{AGENT_GUIDE}}", guide, source)
        encoded = prompts["buyer"].split("CSV=", 1)[1].split("\nThe source JSON", 1)[0]
        self.assertEqual(json.loads(encoded).encode("utf-8"), source.encode("utf-8"))
        self.assertIn(guide, prompts["buyer"])
        self.assertEqual(prompts["provider"], guide)
        for buyer, provider in (("no guide", "{{AGENT_GUIDE}}"),
                                ("{{AGENT_GUIDE}}{{AGENT_GUIDE}}{{SOURCE_CSV_JSON}}", "{{AGENT_GUIDE}}"),
                                ("{{AGENT_GUIDE}}{{SOURCE_CSV_JSON}}{{OTHER}}", "{{AGENT_GUIDE}}"),
                                ("{{AGENT_GUIDE}}{{SOURCE_CSV_JSON}}{{unclosed", "{{AGENT_GUIDE}}"),
                                ("{{AGENT_GUIDE}}{{SOURCE_CSV_JSON}}", "{{AGENT_GUIDE}}{{SOURCE_CSV_JSON}}")):
            with self.subTest(buyer=buyer, provider=provider), self.assertRaises(ValueError):
                launch.render_tasks(buyer, provider, guide, source)

    def test_nonempty_output_refused_without_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "original").write_text("retain")
            with self.assertRaises(ValueError):
                prepare_output(root)
            self.assertEqual((root / "original").read_text(), "retain")

    def test_backup_includes_committed_wal_without_creating_missing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live, final = root / "live.sqlite", root / "termsmet.sqlite"
            self.assertEqual(snapshot(live, final)["status"], "unavailable")
            self.assertFalse(live.exists())
            self.assertFalse(final.exists())
            source = sqlite3.connect(live)
            self.addCleanup(source.close)
            source.execute("PRAGMA journal_mode=WAL")
            source.execute("PRAGMA wal_autocheckpoint=0")
            source.execute("CREATE TABLE evidence (value TEXT)")
            source.execute("INSERT INTO evidence VALUES ('committed-in-WAL')")
            source.commit()
            self.assertTrue(Path(str(live) + "-wal").stat().st_size)
            result = snapshot(live, final)
            self.assertEqual(result["status"], "available")
            self.assertEqual(result["sha256"], hashlib.sha256(final.read_bytes()).hexdigest())
            with sqlite3.connect(final.as_uri() + "?mode=ro", uri=True) as saved:
                self.assertEqual(saved.execute("SELECT value FROM evidence").fetchone()[0], "committed-in-WAL")

    def test_backup_failure_preserves_live_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "live.sqlite"
            live.write_bytes(b"not a database")
            self.assertEqual(snapshot(live, root / "termsmet.sqlite")["status"], "failed")
            self.assertEqual(live.read_bytes(), b"not a database")
            self.assertFalse((root / "termsmet.sqlite").exists())

    def test_client_and_server_environment_separation(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-secret", "CLAUDE_BAD": "bad",
                                     "ANTHROPIC_AUTH_TOKEN": "other", "TERMSMET_IDENTITY": "wrong"}):
            self.assertEqual(client_environment()["ANTHROPIC_API_KEY"], "synthetic-secret")
            self.assertNotIn("CLAUDE_BAD", client_environment())
            self.assertNotIn("ANTHROPIC_API_KEY", base_environment())
            self.assertNotIn("TERMSMET_IDENTITY", base_environment())

    def test_metadata_command_timeout_kills_its_group(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            command_output([sys.executable, "-c", "import time; time.sleep(30)"], ROOT, timeout=0.1)
        self.assertLess(time.monotonic() - started, 3)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Metadata checks deliberately use bounded synchronous subprocesses.
        asyncio.get_running_loop().slow_callback_duration = 5

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="termsmet-y2-tests-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fake = self.root / "fake-claude"
        self.fake.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(ROOT / 'tests' / 'fake_claude.py')!r}, run_name='__main__')\n")
        self.fake.chmod(0o755)
        self.counter = 0
        self.enterContext(patch.dict(os.environ, {"ANTHROPIC_API_KEY": "synthetic-test-key", "ANTHROPIC_BASE_URL": "https://example.invalid"}))

    async def execute(self, mode, roles=("buyer",), **overrides):
        self.counter += 1
        out = prepare_output(self.root / f"run-{self.counter}")
        args = options(out, self.fake, **overrides)
        manifest = launch.initial_manifest(args, "synthetic_cli_test_not_live_preflight")
        prompts = {role: json.dumps({"mode": mode, "role": role}) for role in roles}
        code = await launch.execute(args, out, prompts, manifest)
        self.assertEqual(json.loads((out / "manifest.json").read_text()), manifest)
        return code, out, manifest

    async def test_actual_proxy_call_and_exact_evidence_schema(self):
        code, out, manifest = await self.execute("templates")
        self.assertEqual(code, 0, manifest)
        self.assertEqual(manifest["agents"]["buyer"]["tool_attempts"], 1)
        self.assertEqual(manifest["snapshot"]["status"], "available")
        self.assertTrue(preflight.actual_template_exchange(out))
        for row in records(out / "buyer.jsonl"):
            self.assertEqual(set(row), {"received_at", "line"})
        for row in records(out / "mcp-buyer.jsonl"):
            self.assertEqual(set(row), {"timestamp", "direction", "message"})
        self.assertEqual(manifest["transaction_status"], "not_evaluated")
        self.assertEqual(manifest["agents"]["buyer"]["usage"], "N/A")
        self.assertFalse((out / ".work").exists())

    async def test_business_errors_count_and_attempt_61_is_blocked(self):
        code, out, manifest = await self.execute("business_errors")
        self.assertEqual(code, 0, manifest)
        self.assertEqual(manifest["agents"]["buyer"]["tool_attempts"], 2)
        code, out, manifest = await self.execute("cap")
        self.assertEqual(code, 1)
        self.assertEqual(manifest["execution_status"], "tool_budget_exhausted", manifest)
        state = manifest["agents"]["buyer"]
        self.assertEqual((state["tool_attempts"], state["forwarded_calls"], state["blocked_calls"]), (61, 60, 1))
        calls = [row for row in records(out / "mcp-buyer.jsonl")
                 if row["direction"] == "request" and row["message"].get("method") == "tools/call"]
        self.assertEqual(len(calls), 61)

    async def test_missing_inventory_extra_tools_and_missing_final_fail(self):
        for mode, expected in (("missing_inventory", "inventory_timeout"), ("extra_tool", "tool_isolation_failure"),
                               ("missing_final", "missing_final_output"), ("wrong_model", "model_mismatch")):
            with self.subTest(mode=mode):
                code, _, manifest = await self.execute(mode, startup_seconds=0.8)
                self.assertEqual(code, 1)
                self.assertEqual(manifest["execution_status"], expected, manifest)
                self.assertEqual(manifest["snapshot"]["status"], "unavailable")

    async def test_inventory_gate_expires_without_forwarding(self):
        code, out, manifest = await self.execute("closed_gate", startup_seconds=2)
        self.assertEqual(code, 1)
        self.assertEqual(manifest["agents"]["buyer"]["forwarded_calls"], 0)
        self.assertLess(manifest["elapsed_seconds"], 6)

    async def test_role_can_finish_while_other_continues_and_no_db_is_invented(self):
        code, out, manifest = await self.execute("early", roles=("buyer", "provider"))
        self.assertEqual(code, 0, manifest)
        self.assertLess(manifest["agents"]["buyer"]["result_received_at"], manifest["agents"]["provider"]["result_received_at"])
        self.assertEqual(manifest["snapshot"]["status"], "unavailable")
        self.assertFalse((out / "termsmet.sqlite").exists())
        self.assertFalse(preflight.actual_template_exchange(out))

    async def test_missing_credential_and_missing_binary_are_recorded(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            code, out, manifest = await self.execute("plain")
        self.assertEqual((code, manifest["execution_status"]), (2, "blocked_missing_credential"))
        self.assertFalse((out / "termsmet.sqlite").exists())
        code, _, manifest = await self.execute("plain", claude_bin=str(self.root / "missing"))
        self.assertEqual((code, manifest["execution_status"]), (1, "startup_failure"))

    async def test_hanging_cli_version_is_bounded_and_recorded(self):
        hanging = self.root / "hanging-version"
        hanging.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
        hanging.chmod(0o755)
        code, out, manifest = await self.execute("plain", claude_bin=str(hanging), wall_seconds=0.4)
        self.assertEqual((code, manifest["execution_status"]), (1, "startup_failure"))
        self.assertEqual(manifest["exception_type"], "TimeoutExpired")
        self.assertLess(manifest["elapsed_seconds"], 3)
        self.assertFalse((out / "termsmet.sqlite").exists())

    async def test_secret_output_fails_and_diagnostics_are_redacted(self):
        code, out, manifest = await self.execute("secret_output")
        self.assertEqual((code, manifest["execution_status"]), (1, "credential_output_blocked"))
        for path in out.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"synthetic-test-key", path.read_bytes(), path)
        for line in (out / "client-buyer.stderr.log").read_text().splitlines():
            if line.startswith("{"):
                self.assertNotIn("synthetic-test-key", str(json.loads(line)))

    async def test_wall_timeout_kills_only_trial_descendants(self):
        sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        try:
            code, out, manifest = await self.execute("descendant", wall_seconds=2)
            self.assertEqual((code, manifest["execution_status"]), (1, "wall_timeout"))
            self.assertIsNone(sentinel.poll())
            events = [json.loads(row["line"]) for row in records(out / "buyer.jsonl")]
            child = next(event["pid"] for event in events if event.get("type") == "fixture_child")
            for _ in range(100):
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.02)
            else:
                self.fail("trial descendant survived cleanup")
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=2)

    async def test_cancellation_records_interruption_and_cleans_up(self):
        out = prepare_output(self.root / "interrupted")
        args = options(out, self.fake)
        manifest = launch.initial_manifest(args, "synthetic_cli_test_not_live_preflight")
        task = asyncio.create_task(launch.execute(args, out, {"buyer": '{"mode":"interrupt"}'}, manifest))
        for _ in range(100):
            if manifest["agents"].get("buyer", {}).get("inventory_verified"):
                break
            await asyncio.sleep(0.02)
        self.assertTrue(manifest["agents"]["buyer"]["inventory_verified"])
        task.cancel()
        self.assertEqual(await asyncio.wait_for(task, 5), 130)
        self.assertEqual(manifest["execution_status"], "interrupted")
        self.assertEqual(manifest["cleanup"]["status"], "completed")

    async def test_configuration_and_no_observer_settlement(self):
        code, out, manifest = await self.execute("transaction", roles=("buyer", "provider"), review_seconds=0.05, first_submit_minutes=3)
        self.assertEqual(code, 0, manifest)
        databases = []
        for role in ("buyer", "provider"):
            parameters = json.loads((out / f"mcp-{role}.json").read_text())["mcpServers"]["termsmet"]["args"]
            self.assertEqual(parameters[parameters.index("--identity") + 1], role)
            self.assertEqual(parameters[parameters.index("--review-seconds") + 1], "0.05")
            self.assertEqual(parameters[parameters.index("--first-submit-minutes") + 1], "3")
            databases.append(parameters[parameters.index("--db") + 1])
        self.assertEqual(databases[0], databases[1])
        with sqlite3.connect((out / "termsmet.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            job = db.execute("SELECT * FROM jobs").fetchone()
            self.assertEqual(job["status"], "IN_REVIEW")
            deadline = datetime.fromisoformat(job["first_submission_deadline"])
            funded = datetime.fromisoformat(job["funded_at"])
            self.assertEqual((deadline - funded).total_seconds(), 180)
            checked = datetime.fromisoformat(db.execute("SELECT checked_at FROM check_results").fetchone()[0])
            review = datetime.fromisoformat(job["review_deadline"])
            self.assertAlmostEqual((review - checked).total_seconds(), 0.05)
            self.assertGreater(time.time(), review.timestamp())
            self.assertEqual(db.execute("SELECT event_type FROM settlement_events").fetchall()[0][0], "SIMULATED_FUNDING")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0], 1)

    async def test_backup_failure_preserves_live_database_and_marks_execution(self):
        with patch.object(launch, "snapshot", return_value={"status": "failed", "reason": "injected disk failure"}):
            code, out, manifest = await self.execute("templates")
        self.assertEqual((code, manifest["execution_status"]), (1, "backup_failure"))
        self.assertTrue((out / ".work" / "live.sqlite").exists())

    async def test_cleanup_failure_preserves_live_database_without_snapshot(self):
        async def incomplete(*args):
            return {"status": "failed", "errors": ["injected verification failure"]}
        with patch.object(launch, "stop_owned", side_effect=incomplete):
            code, out, manifest = await self.execute("templates")
        self.assertEqual((code, manifest["execution_status"]), (1, "cleanup_failure"))
        self.assertTrue((out / ".work" / "live.sqlite").exists())
        self.assertEqual(manifest["snapshot"]["status"], "unavailable")
        self.assertFalse((out / "termsmet.sqlite").exists())

    async def test_sdk_initialization_is_bounded_when_server_never_responds(self):
        out = prepare_output(self.root / "sdk-timeout")
        hanging = self.root / "silent.py"
        hanging.write_text("import time\ntime.sleep(30)\n")
        args = options(out, self.fake, startup_seconds=0.4)
        started = time.monotonic()
        with patch.object(preflight, "proxy_parameters", return_value=[str(hanging)]):
            record = await asyncio.wait_for(preflight.sdk_check(args, out), 6)
        self.assertFalse(record["passed"])
        self.assertLess(time.monotonic() - started, 6)
        self.assertEqual(record["snapshot"]["status"], "unavailable")
        self.assertFalse((out / "termsmet.sqlite").exists())
        self.assertTrue(records(out / "buyer-control.jsonl"))

    async def test_proxy_preserves_wire_bytes_in_both_directions(self):
        out = prepare_output(self.root / "wire")
        (out / ".work").mkdir()
        (out / ".buyer-inventory-ok").touch()
        runtime = self.root / "echo-runtime"
        (runtime / "server").mkdir(parents=True)
        (runtime / "server" / "__init__.py").touch()
        response = b' { "jsonrpc" : "2.0", "id" : "echo", "result" : {"ok":true} }\n'
        request = b' { "jsonrpc" : "2.0", "id" : "echo", "method" : "ping" }\n'
        captured = runtime / "received"
        (runtime / "server" / "mcp_server.py").write_text(
            "import sys\nfrom pathlib import Path\n"
            f"for line in sys.stdin.buffer:\n Path({str(captured)!r}).write_bytes(line)\n sys.stdout.buffer.write({response!r})\n sys.stdout.buffer.flush()\n"
        )
        args = options(out, self.fake)
        command = proxy_parameters(args, out, "buyer")
        command[command.index("--runtime-dir") + 1] = str(runtime)
        process = await asyncio.create_subprocess_exec(
            sys.executable, *command, cwd=self.root, env=base_environment(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        try:
            process.stdin.write(request)
            await process.stdin.drain()
            self.assertEqual(await asyncio.wait_for(process.stdout.readline(), 5), response)
            self.assertEqual(captured.read_bytes(), request)
            process.stdin.close()
            self.assertEqual(await asyncio.wait_for(process.wait(), 5), 0)
            rows = records(out / "mcp-buyer.jsonl")
            self.assertEqual([row["message"]["id"] for row in rows], ["echo", "echo"])
        finally:
            signal_group(process.pid, signal.SIGKILL)
            await asyncio.wait_for(process.wait(), 2)

    async def test_preflight_rejects_fake_inventory_without_actual_call(self):
        out = prepare_output(self.root / "claimed-preflight")
        self.fake.write_text(
            f"#!{sys.executable}\nimport io,runpy,sys\n"
            "if '--version' not in sys.argv and '--help' not in sys.argv: sys.stdin=io.StringIO('{\"mode\":\"plain\"}')\n"
            f"runpy.run_path({str(ROOT / 'tests' / 'fake_claude.py')!r}, run_name='__main__')\n"
        )
        args = options(out, self.fake)
        self.assertEqual(await preflight.run(args, out), 1)
        record = json.loads((out / "preflight.json").read_text())
        self.assertFalse(record["passed"])
        self.assertEqual(record["status"], "missing_template_exchange")

    async def start_public_launcher(self, name):
        inputs = self.root / (name + "-inputs")
        inputs.mkdir()
        (inputs / "buyer.md").write_text("{{AGENT_GUIDE}}\nSource JSON: {{SOURCE_CSV_JSON}}")
        (inputs / "provider.md").write_text("{{AGENT_GUIDE}}")
        (inputs / "guide.md").write_text("Synthetic setup guide, not scored task instructions.")
        source = "Order,Units,Price\r\nCLI-7,1,$8.125\r\n"
        (inputs / "source.csv").write_bytes(source.encode("utf-8"))
        out = self.root / name
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "coldstart.launch", "--out", str(out),
            "--buyer-task", str(inputs / "buyer.md"), "--provider-task", str(inputs / "provider.md"),
            "--guide", str(inputs / "guide.md"), "--source-csv", str(inputs / "source.csv"),
            "--claude-bin", str(self.fake), "--model", "synthetic-model",
            "--wall-seconds", "12", "--startup-seconds", "4",
            cwd=ROOT, env=dict(os.environ), stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, start_new_session=True,
        )
        return process, out

    async def test_public_launcher_entrypoint_and_source_isolation(self):
        process, out = await self.start_public_launcher("public-command")
        try:
            _, stderr = await asyncio.wait_for(process.communicate(), 15)
            self.assertEqual(process.returncode, 0, stderr.decode())
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["execution_status"], "completed")
            self.assertEqual(len(manifest["input_sha256"]), 4)
            self.assertIn("CLI-7", (out / "prompt-buyer.md").read_text())
            self.assertNotIn("CLI-7", (out / "prompt-provider.md").read_text())
            self.assertEqual(manifest["agents"]["buyer"]["tool_attempts"], 1)
            self.assertEqual(manifest["agents"]["provider"]["tool_attempts"], 1)
        finally:
            signal_group(process.pid, signal.SIGKILL)
            await asyncio.wait_for(process.wait(), 2)

    async def test_public_launcher_sigterm_is_recorded_as_interruption(self):
        self.fake.write_text(
            f"#!{sys.executable}\nimport io,runpy,sys\n"
            "if '--version' not in sys.argv and '--help' not in sys.argv: sys.stdin=io.StringIO('{\"mode\":\"interrupt\"}')\n"
            f"runpy.run_path({str(ROOT / 'tests' / 'fake_claude.py')!r}, run_name='__main__')\n"
        )
        process, out = await self.start_public_launcher("public-interrupt")
        try:
            for _ in range(200):
                if (out / ".buyer-inventory-ok").exists():
                    break
                await asyncio.sleep(0.025)
            self.assertTrue((out / ".buyer-inventory-ok").exists())
            process.send_signal(signal.SIGTERM)
            await asyncio.wait_for(process.communicate(), 8)
            self.assertEqual(process.returncode, 130)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["execution_status"], "interrupted")
            if manifest["cleanup"]["status"] == "failed":
                # Some macOS sandbox runs deny probing a terminated group. The
                # result must preserve state, never claim confirmed cleanup.
                self.assertTrue(any("Operation not permitted" in error for error in manifest["cleanup"]["errors"]), manifest)
                self.assertTrue((out / ".work").exists())
                self.assertEqual(manifest["snapshot"]["status"], "unavailable")
            else:
                self.assertEqual(manifest["cleanup"]["status"], "completed", manifest)
            self.assertFalse((out / "termsmet.sqlite").exists())
        finally:
            signal_group(process.pid, signal.SIGKILL)
            await asyncio.wait_for(process.wait(), 2)

    async def test_real_sdk_preflight_and_synthetic_inventory_cannot_claim_live_call(self):
        out = prepare_output(self.root / "preflight")
        args = options(out, self.fake)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            code = await preflight.run(args, out)
        result = json.loads((out / "preflight.json").read_text())
        self.assertEqual(code, 2)
        self.assertTrue(result["sdk"]["passed"], result)
        self.assertFalse(result["passed"])
        self.assertFalse(result["list_templates_exchange_verified"])


if __name__ == "__main__":
    unittest.main()
