# H9 hand calculation (independent oracle)

Synthetic data created for HW9 S1. The expected files were typed from this
worksheet, not produced by the TermsMet parser or checker. Rule from the guide:
unit cents = Price × 100 rounded ROUND_HALF_UP **first**, then
total = quantity × unit cents.

| Order | Units | Price | Price × 100 | Unit cents (half-up) | Total cents | Total USD | > $100.00? |
|---|---:|---|---:|---:|---:|---:|---|
| K301 | 4 | $25.00 | 2500.0 | 2500 | 4 × 2500 = 10000 | 100.00 | no (exactly 100.00) |
| K302 | 3 | $2.675 | 267.5 | 268 | 3 × 268 = 804 | 8.04 | no |
| K303 | 1 | $149.99 | 14999.0 | 14999 | 1 × 14999 = 14999 | 149.99 | **yes** |
| K304 | 12 | $8.40 | 840.0 | 840 | 12 × 840 = 10080 | 100.80 | **yes** |
| K305 | 7 | $0.995 | 99.5 | 100 | 7 × 100 = 700 | 7.00 | no |
| K306 | 5 | $19.99 | 1999.0 | 1999 | 5 × 1999 = 9995 | 99.95 | no |
| K307 | 10 | $12.50 | 1250.0 | 1250 | 10 × 1250 = 12500 | 125.00 | **yes** |
| K308 | 6 | $3.333 | 333.3 | 333 | 6 × 333 = 1998 | 19.98 | no |

Totals:

- order_count = 8
- total_quantity = 4 + 3 + 1 + 12 + 7 + 5 + 10 + 6 = **48**
- total_cents = 10000 + 804 + 14999 + 10080 + 700 + 9995 + 12500 + 1998
  = 10804 → 25803 → 35883 → 36583 → 46578 → 59078 → **61076** = **$610.76**
- approval_orders (total_cents strictly > 10000): K303 $149.99, K304 $100.80,
  K307 $125.00. K301 is exactly $100.00 and is excluded.

Design coverage required by the handoff: half-cent unit prices (K302, K305),
an order totaling exactly $100 (K301), orders above $100 (K303, K304, K307)
and below $100 (K302, K305, K306, K308). K302 and K305 are also binary-float
traps: Python's `round(2.675, 2)` gives 2.67 and `round(0.995, 2)` gives 0.99,
whereas the contract's Decimal ROUND_HALF_UP gives 268 and 100 cents.

Second check: `tests/test_h9_oracle.py` recomputes every value from `H9.csv`
with Python `Decimal` without importing `server/`, and compares the result to
both expected files.
