"""Second, independent arithmetic check of the H9 oracles.

Deliberately does not import ``server`` or ``coldstart``: the oracle must not be
derived from the production parser/checker.
"""

import csv
import io
import json
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "coldstart" / "data"


def recompute():
    text = (DATA / "H9.csv").read_text(encoding="utf-8")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    delivery = []
    for row in rows:
        quantity = int(row["Units"])
        unit = int((Decimal(row["Price"].replace("$", "")) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        delivery.append({"order_id": row["Order"], "quantity": quantity,
                         "unit_price_cents": unit, "total_cents": quantity * unit})
    return text, delivery


def usd(cents):
    return f"{cents // 100}.{cents % 100:02d}"


class H9OracleTests(unittest.TestCase):
    def test_source_shape(self):
        text, delivery = recompute()
        self.assertTrue(text.startswith("Order,Customer,Units,Price\n"))
        self.assertTrue(text.endswith("\n"))
        self.assertNotIn("\r", text)
        self.assertEqual(len(delivery), 8)
        self.assertEqual(len({record["order_id"] for record in delivery}), 8)
        self.assertTrue(all(record["quantity"] > 0 for record in delivery))
        totals = [record["total_cents"] for record in delivery]
        self.assertIn(10000, totals)
        self.assertTrue(any(total > 10000 for total in totals))
        self.assertTrue(any(total < 10000 for total in totals))
        prices = text.splitlines()[1:]
        self.assertTrue(any(line.endswith("5") and len(line.rsplit(".", 1)[1]) == 3 for line in prices))

    def test_expected_delivery_matches_recomputation(self):
        _, delivery = recompute()
        expected = json.loads((DATA / "H9_expected_delivery.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(expected, key=lambda r: r["order_id"]), sorted(delivery, key=lambda r: r["order_id"]))
        for record in expected:
            self.assertEqual(set(record), {"order_id", "quantity", "unit_price_cents", "total_cents"})
            for field in ("quantity", "unit_price_cents", "total_cents"):
                self.assertIs(type(record[field]), int)

    def test_expected_report_matches_recomputation(self):
        _, delivery = recompute()
        expected = json.loads((DATA / "H9_expected_report.json").read_text(encoding="utf-8"))
        self.assertEqual(set(expected), {"job_id", "order_count", "total_quantity", "total_amount_usd", "approval_orders"})
        self.assertEqual(expected["job_id"], "<observed job ID>")
        self.assertEqual(expected["order_count"], len(delivery))
        self.assertEqual(expected["total_quantity"], sum(r["quantity"] for r in delivery))
        self.assertEqual(expected["total_amount_usd"], usd(sum(r["total_cents"] for r in delivery)))
        approvals = sorted(({"order_id": r["order_id"], "total_amount_usd": usd(r["total_cents"])}
                            for r in delivery if r["total_cents"] > 10000), key=lambda r: r["order_id"])
        self.assertEqual(sorted(expected["approval_orders"], key=lambda r: r["order_id"]), approvals)

    def test_binary_float_would_disagree(self):
        """Documents why the half-cent prices are meaningful traps."""
        self.assertEqual(round(2.675, 2), 2.67)  # half-up requires 2.68 (268 cents)
        self.assertEqual(round(0.995, 2), 0.99)  # half-up requires 1.00 (100 cents)


if __name__ == "__main__":
    unittest.main()
