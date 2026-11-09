"""Source parsing and deterministic checks for order_extraction_v1."""

import csv
import hashlib
import io
import re
from collections import Counter
from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext

TEMPLATE_ID = "order_extraction_v1"
CHECKER_VERSION = "order_extraction_v1.0"
DELIVERY_FIELDS = ("order_id", "quantity", "unit_price_cents", "total_cents")


def parse_source(source_csv: str) -> dict[str, dict[str, object]]:
    """Derive order records from source text, without changing the agreed text."""
    if not isinstance(source_csv, str):
        raise ValueError("source_csv must be CSV text")
    try:
        rows = (row for row in csv.reader(io.StringIO(source_csv, newline=""), strict=True) if row)
        headers = next(rows, None)
        if (not headers or len(set(headers)) != len(headers)
                or any(not header.strip() for header in headers)
                or not {"Order", "Units", "Price"}.issubset(headers)):
            raise ValueError("source CSV requires unique, nonempty headers including Order, Units and Price")
        order_column, units_column, price_column = (headers.index(name) for name in ("Order", "Units", "Price"))
        orders = {}
        for row in rows:
            if len(row) != len(headers):
                raise ValueError("source CSV rows must match the header width")
            order_id = row[order_column]
            if not order_id.strip() or order_id in orders:
                raise ValueError("source CSV order IDs must be nonempty and unique")
            units = row[units_column].strip()
            if not re.fullmatch(r"[+-]?\d+", units):
                raise ValueError("source CSV Units must be integers")
            quantity = int(units)
            price = Decimal(row[price_column].replace("$", "").strip())
            if not price.is_finite():
                raise ValueError("source CSV Price must be finite")
            with localcontext() as context:
                # Avoid silently rounding prices longer than Decimal's default precision.
                context.prec = max(28, len(price.as_tuple().digits) + 2, price.adjusted() + 3)
                cents = int((price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            orders[order_id] = {
                "order_id": order_id, "quantity": quantity,
                "unit_price_cents": cents, "total_cents": quantity * cents,
            }
        return orders
    except (csv.Error, DecimalException, OverflowError) as exc:
        raise ValueError("source CSV contains malformed rows or invalid prices") from exc


def check_delivery(source_csv: str, delivery: object) -> dict[str, object]:
    """Check the submitted values without coercing, mutating or executing them."""
    source_hash = hashlib.sha256(source_csv.encode("utf-8")).hexdigest()
    expected = parse_source(source_csv)
    errors = []
    if (not isinstance(delivery, list)
            or any(not isinstance(record, dict) or any(not isinstance(key, str) for key in record)
                   for record in delivery)):
        errors.append({"code": "MALFORMED_DELIVERY"})
    else:
        for record in delivery:
            identity = {"order_id": record["order_id"]} if isinstance(record.get("order_id"), str) else {}
            for field in DELIVERY_FIELDS:
                if field not in record:
                    errors.append({"code": "MISSING_FIELD", **identity, "field": field})
            for field in sorted(record.keys() - DELIVERY_FIELDS):
                errors.append({"code": "UNEXPECTED_FIELD", **identity, "field": field})
            for field in DELIVERY_FIELDS:
                if field not in record:
                    continue
                expected_type = str if field == "order_id" else int
                if type(record[field]) is not expected_type:
                    errors.append({"code": "WRONG_TYPE", **identity, "field": field,
                                   "expected": "string" if expected_type is str else "integer",
                                   "actual": type(record[field]).__name__})

        counts = Counter(record["order_id"] for record in delivery if isinstance(record.get("order_id"), str))
        for order_id in expected:
            if order_id not in counts:
                errors.append({"code": "MISSING_ORDER", "order_id": order_id})
        for order_id, count in counts.items():
            if order_id not in expected:
                errors.append({"code": "UNEXPECTED_ORDER", "order_id": order_id})
            if count > 1:
                errors.append({"code": "DUPLICATE_ORDER", "order_id": order_id})

        for record in delivery:
            order_id = record.get("order_id")
            if not isinstance(order_id, str) or order_id not in expected:
                continue
            for field, code in (("quantity", "WRONG_QUANTITY"), ("unit_price_cents", "WRONG_UNIT_PRICE"),
                                ("total_cents", "WRONG_TOTAL")):
                if type(record.get(field)) is not int:
                    continue
                value = expected[order_id][field]
                if (field == "total_cents" and record[field] == value
                        and all(type(record.get(name)) is int for name in ("quantity", "unit_price_cents"))):
                    value = record["quantity"] * record["unit_price_cents"]
                if record[field] != value:
                    errors.append({"code": code, "order_id": order_id, "field": field,
                                   "expected": value, "actual": record[field]})
    return {"source_hash": source_hash, "checker_version": CHECKER_VERSION,
            "verdict": "FAIL" if errors else "PASS", "errors": errors}


def list_templates() -> dict[str, object]:
    """List supported acceptance templates and their negotiable terms."""
    return {
        "templates": [
            {
                "template_id": TEMPLATE_ID,
                "negotiable": {"repair_window_minutes": [5, 10]},
            }
        ]
    }
