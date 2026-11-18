"""Additive header diagnostics and unchanged source/transaction behavior."""

import asyncio
import json
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import AsyncExitStack, closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from coldstart._support import ROOT
from server.checker import MissingSourceColumnsError, parse_source
from server.service import TermsMetService
from server.storage import open_database


GENERIC_ERROR = {"error": {"code": "INVALID_TERMS", "message": "source_csv must contain valid, unambiguous order data"}}


class SourceDiagnosticTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="termsmet-y4-source-")
        self.addCleanup(directory.cleanup)
        self.connection = open_database(Path(directory.name) / "termsmet.sqlite")
        self.addCleanup(self.connection.close)
        self.service = TermsMetService(self.connection, "buyer")

    def propose(self, source):
        return self.service.call("propose_agreement", template_id="order_extraction_v1", source_csv=source)

    def assert_no_business_rows(self):
        for table in ("jobs", "agreement_versions", "acceptances", "submissions", "check_results", "challenges", "settlement_events"):
            self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)

    def test_missing_columns_are_ordered_and_received_headers_unchanged(self):
        for source, missing, received in (
            ("sku,count,cost\nOTHER-7,2,$3.125\n", ["Order", "Units", "Price"], ["sku", "count", "cost"]),
            ("Order,Customer,Units\nOTHER-7,Synthetic,2\n", ["Price"], ["Order", "Customer", "Units"]),
            ("Price,notes\n$3.125,Synthetic\n", ["Order", "Units"], ["Price", "notes"]),
            (" Price,units,Order\n$3.125,2,OTHER-7\n", ["Units", "Price"], [" Price", "units", "Order"]),
            ("order,Units,Price\nOTHER-7,2,$3.125\n", ["Order"], ["order", "Units", "Price"]),
        ):
            with self.subTest(source=source):
                expected = {"missing_columns": missing, "received_columns": received}
                with self.assertRaises(MissingSourceColumnsError) as raised:
                    parse_source(source)
                self.assertIsInstance(raised.exception, ValueError)
                self.assertEqual(raised.exception.details, expected)
                self.assertEqual(self.propose(source), {"error": {
                    "code": "INVALID_TERMS", "message": "Required source columns are missing", "details": expected,
                }})
        self.assert_no_business_rows()

    def test_malformed_headers_keep_generic_rejection_before_missing_columns(self):
        for source in (
            "", "\n\n", "Order,,Price\nA,2,$1\n", "Order,   ,Price\nA,2,$1\n",
            "Order,Order,Price\nA,A,$1\n", "Order,Units,Price,Order\nA,2,$1,A\n",
            '"Order,Units,Price\nA,2,$1\n',
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError) as raised:
                    parse_source(source)
                self.assertNotIsInstance(raised.exception, MissingSourceColumnsError)
                self.assertEqual(self.propose(source), GENERIC_ERROR)
        self.assert_no_business_rows()

    def test_other_malformed_data_keeps_generic_error_without_details(self):
        for rows in (
            "A,2\n", "A,2,$1,extra\n", "A,2,$1\nA,1,$2\n", "   ,2,$1\n",
            "A,2.0,$1\n", "A,2,NaN\n", "A,2,Infinity\n", "A,2,not-money\n", 'A,2,"$1\n',
        ):
            with self.subTest(rows=rows):
                self.assertEqual(self.propose("Order,Units,Price\n" + rows), GENERIC_ERROR)
        self.assert_no_business_rows()

    def test_existing_accepted_controls_and_rounding_remain_valid(self):
        for source, expected in (
            ("Price,Customer,Units,Order\n$3.125,Synthetic-Control,3,V401\n",
             {"V401": {"order_id": "V401", "quantity": 3, "unit_price_cents": 313, "total_cents": 939}}),
            ("Order,Units,Price\n", {}),
            ("Order,Units,Price\nSIGNED,+2,-3.125\n",
             {"SIGNED": {"order_id": "SIGNED", "quantity": 2, "unit_price_cents": -313, "total_cents": -626}}),
            ("Order,Units,Price\nNEGATIVE,-2,3.125\n",
             {"NEGATIVE": {"order_id": "NEGATIVE", "quantity": -2, "unit_price_cents": 313, "total_cents": -626}}),
            ("Order,Units,Price\nZERO,0,1e2\n",
             {"ZERO": {"order_id": "ZERO", "quantity": 0, "unit_price_cents": 10000, "total_cents": 0}}),
            ("Order,Units,Price\n EDGE ,1,$1.00\n",
             {" EDGE ": {"order_id": " EDGE ", "quantity": 1, "unit_price_cents": 100, "total_cents": 100}}),
        ):
            with self.subTest(source=source):
                self.assertEqual(parse_source(source), expected)
                self.assertEqual(self.propose(source)["status"], "PROPOSED")
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM settlement_events").fetchone()[0], 0)

    def test_service_parses_each_proposal_once(self):
        for source in ("sku,count,cost\nOTHER-8,1,$1\n", "Order,Units,Price\nOTHER-8,1,$1\n"):
            with self.subTest(source=source), patch("server.service.parse_source", wraps=parse_source) as parser:
                self.propose(source)
                parser.assert_called_once_with(source)

    def test_existing_business_errors_omit_details(self):
        self.assertEqual(self.service.call("get_job", job_id="missing"), {
            "error": {"code": "NOT_FOUND", "message": "job not found"},
        })
        self.assertEqual(self.service.call("propose_agreement", template_id="unsupported", source_csv=""), {
            "error": {"code": "INVALID_TERMS", "message": "unsupported template_id"},
        })
        provider = TermsMetService(self.connection, "provider")
        self.assertEqual(provider.call("fund_job", job_id="missing"), {
            "error": {"code": "PERMISSION_DENIED", "message": "fund_job is not permitted for this caller"},
        })
        self.assert_no_business_rows()


class ValidMCPTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_extra_column_transaction_releases_with_bounded_real_time_polling(self):
        with tempfile.TemporaryDirectory(prefix="termsmet-y4-transaction-") as directory:
            database = Path(directory) / "termsmet.sqlite"
            async with AsyncExitStack() as stack:
                clients = {}
                for identity in ("buyer", "provider"):
                    streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                        command=sys.executable, args=["-m", "server.mcp_server"], cwd=ROOT,
                        env={"TERMSMET_IDENTITY": identity, "TERMSMET_DB_PATH": str(database),
                             "TERMSMET_REVIEW_SECONDS": "2", "TERMSMET_FIRST_SUBMIT_MIN": "5"},
                    )))
                    client = await stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=10))
                    await asyncio.wait_for(client.initialize(), 10)
                    clients[identity] = client

                async def call(identity, tool, **arguments):
                    response = await asyncio.wait_for(clients[identity].call_tool(tool, arguments), 10)
                    self.assertFalse(response.is_error, response)
                    self.assertIsInstance(response.structured_content, dict)
                    self.assertEqual(json.loads(response.content[0].text), response.structured_content)
                    return response.structured_content

                source = "Price,Customer,Units,Order\n$3.125,Synthetic-Control,3,V401\n"
                expected = [{"order_id": "V401", "quantity": 3, "unit_price_cents": 313, "total_cents": 939}]
                proposal = await call("buyer", "propose_agreement", template_id="order_extraction_v1", source_csv=source)
                job_id = proposal["job_id"]
                denied = await call("buyer", "retrieve_delivery", job_id=job_id)
                self.assertEqual(denied["error"]["code"], "PERMISSION_DENIED")
                view = await call("provider", "get_job", job_id=job_id)
                self.assertEqual(view["source_csv"], source)
                self.assertEqual(view["current_submission_version"], 0)
                for identity in clients:
                    acceptance = await call(identity, "accept_agreement", job_id=job_id, version=1)
                    self.assertNotIn("error", acceptance)
                funded = await call("buyer", "fund_job", job_id=job_id)
                self.assertEqual(funded, {"job_id": job_id, "status": "FUNDED", "simulated": True})
                submitted = await call("provider", "submit_delivery", job_id=job_id, delivery=expected)
                self.assertEqual(submitted["verdict"], "PASS")

                deadline = time.monotonic() + 10
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.fail("transaction did not reach RELEASED within ten real-time seconds")
                    job = await asyncio.wait_for(call("buyer", "get_job", job_id=job_id), remaining)
                    if job["status"] == "RELEASED":
                        break
                    self.assertEqual(job["status"], "IN_REVIEW", job)
                    await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))

                result = await call("buyer", "get_result", job_id=job_id, submission_version=submitted["submission_version"])
                self.assertEqual(result["verdict"], "PASS")
                self.assertEqual(result["errors"], [])
                self.assertTrue(result["release_allowed"])
                self.assertEqual(result["settlement"], {"status": "RELEASED", "simulated": True})
                for _ in range(2):
                    retrieved = await call("buyer", "retrieve_delivery", job_id=job_id)
                    self.assertEqual(retrieved, {"job_id": job_id, "delivery": expected})
                with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)) as db:
                    events = dict(db.execute("SELECT event_type, COUNT(*) FROM settlement_events GROUP BY event_type"))
                    self.assertEqual(events, {"SIMULATED_FUNDING": 1, "SIMULATED_RELEASE": 1})
                    review, released = db.execute("SELECT review_deadline, released_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
                    self.assertGreaterEqual(datetime.fromisoformat(released), datetime.fromisoformat(review))


if __name__ == "__main__":
    unittest.main()
