"""Y1 baseline checks against two actual identity-scoped MCP processes."""

import json
import sys
import tempfile
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from server.mcp_server import load_config


ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    "list_templates", "propose_agreement", "list_jobs", "get_job",
    "counter_agreement", "accept_agreement", "fund_job", "submit_delivery",
    "get_result", "challenge_result", "retrieve_delivery",
}


class ConfigurationTests(unittest.TestCase):
    def test_review_default_and_explicit_hw9_override(self):
        with patch.dict("os.environ", {
            "TERMSMET_IDENTITY": "buyer",
            "TERMSMET_DB_PATH": "/unused/termsmet.sqlite",
        }, clear=True):
            self.assertEqual(load_config().review_seconds, 10)
            self.assertEqual(load_config().first_submit_minutes, 5)
            with patch.dict("os.environ", {"TERMSMET_REVIEW_SECONDS": "2"}):
                self.assertEqual(load_config().review_seconds, 2)


class SubmissionDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_job_tracks_actual_submission_versions_for_both_roles(self):
        with tempfile.TemporaryDirectory(prefix="termsmet-y1-") as directory:
            async with AsyncExitStack() as stack:
                sessions = {}
                for identity in ("buyer", "provider"):
                    streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                        command=sys.executable,
                        args=["-m", "server.mcp_server"],
                        cwd=ROOT,
                        env={
                            "TERMSMET_IDENTITY": identity,
                            "TERMSMET_DB_PATH": str(Path(directory) / "live.sqlite"),
                            "TERMSMET_REVIEW_SECONDS": "2",
                            "TERMSMET_FIRST_SUBMIT_MIN": "5",
                        },
                    )))
                    session = await stack.enter_async_context(ClientSession(
                        *streams, read_timeout_seconds=10,
                    ))
                    await session.initialize()
                    inventory = (await session.list_tools()).tools
                    self.assertEqual({tool.name for tool in inventory}, TOOLS)
                    for tool in inventory:
                        self.assertFalse({"identity", "role"} & tool.input_schema["properties"].keys())
                    sessions[identity] = session

                async def call(identity, tool, **arguments):
                    response = await sessions[identity].call_tool(tool, arguments)
                    self.assertFalse(response.is_error, response)
                    self.assertIsInstance(response.structured_content, dict)
                    # The structured and textual business results must agree.
                    self.assertEqual(json.loads(response.content[0].text), response.structured_content)
                    return response.structured_content

                source = "Order,Customer,Units,Price\nZ17,Synthetic,3,$3.125\n"
                proposal = await call("buyer", "propose_agreement",
                                      template_id="order_extraction_v1", source_csv=source)
                self.assertNotIn("error", proposal)
                job_id = proposal["job_id"]

                async def assert_version(version):
                    for identity in sessions:
                        job = await call(identity, "get_job", job_id=job_id)
                        self.assertEqual(set(job), {
                            "job_id", "status", "version", "current_submission_version",
                            "terms", "source_csv", "deadlines",
                        })
                        self.assertIs(type(job["current_submission_version"]), int)
                        self.assertEqual(job["current_submission_version"], version)
                        self.assertEqual(job["version"], 1)
                        self.assertEqual(job["source_csv"], source)

                await assert_version(0)
                denied = await call("buyer", "retrieve_delivery", job_id=job_id)
                self.assertEqual(denied["error"]["code"], "PERMISSION_DENIED")
                denied = await call("provider", "fund_job", job_id=job_id)
                self.assertEqual(denied["error"]["code"], "PERMISSION_DENIED")
                for identity in sessions:
                    accepted = await call(identity, "accept_agreement", job_id=job_id, version=1)
                    self.assertNotIn("error", accepted)
                funded = await call("buyer", "fund_job", job_id=job_id)
                self.assertEqual(funded, {"job_id": job_id, "status": "FUNDED", "simulated": True})

                failed = await call("provider", "submit_delivery", job_id=job_id, delivery=[])
                self.assertEqual(failed["verdict"], "FAIL")
                self.assertEqual(failed["submission_version"], 1)
                await assert_version(1)
                passed = await call("provider", "submit_delivery", job_id=job_id, delivery=[{
                    "order_id": "Z17", "quantity": 3, "unit_price_cents": 313, "total_cents": 939,
                }])
                self.assertEqual(passed["verdict"], "PASS")
                self.assertEqual(passed["submission_version"], 2)
                await assert_version(2)
                for identity in sessions:
                    report = await call(identity, "get_result", job_id=job_id, submission_version=2)
                    self.assertEqual(report["verdict"], "PASS")
                    self.assertEqual(report["errors"], [])


if __name__ == "__main__":
    unittest.main()
