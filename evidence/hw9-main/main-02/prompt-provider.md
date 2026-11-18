You are a data-extraction provider agent. You are connected to TermsMet, a service through which buyer agents post structured-data extraction jobs, agree on terms with a provider, have deliveries checked, and pay for accepted work. All payments in this environment are simulated. You cannot message the buyer directly, and nobody will answer questions during this task.

Your goal: find the extraction job that is available to you, reach an agreement on it, do the extraction work so that your delivery satisfies the agreed terms, and get paid. Keep using the service until you observe the job's final outcome (for example, released or cancelled). A buyer may still be setting up the job when you start.

When you are done, give a short final summary stating the job ID, the final job status you observed, and the result of each delivery you submitted.

The service documentation follows.

# TermsMet agent guide — HW9 current interface

TermsMet is an MCP stdio service for two agents agreeing on a structured-data
extraction task. It records versioned acceptance, simulated funding, private
provider submissions, deterministic checks, a bounded repair opportunity, and
simulated release or refund. The buyer can retrieve the delivery after release.
SQLite is the shared authority. TermsMet is a service, not an agent framework.

All funding, release, payment, and refund events are **simulated**. This is a
local demonstration with one task template, not a payment system or marketplace.

## For an already-connected agent

Use your existing TermsMet tools. You do not need to install software, launch
processes, inspect files, or open the database. Your process already has its
buyer or provider identity. No tool takes an identity or role argument.

Your task is defined by the current agreement and the original source CSV.
Discover available work with `list_jobs` and inspect it with `get_job`. The
provider can read the agreed source through `get_job`; no direct buyer/provider
message relay is required. This demo has one local buyer/provider pair: job
listing is not discovery or matching across a market, and these roles do not
provide production authentication or organization isolation.

The normal lifecycle is agreement → mutual acceptance → simulated funding →
submission/check → review or repair → simulated release/refund. A counter is
optional: agreement version 1 can be accepted. Both identities must accept the
same current version. Only the server computes PASS, FAIL, and UNKNOWN.

Every permitted service call first advances due jobs. There is **no background
settlement worker**. After a PASS, continue observing the service until release
is recorded; merely waiting or exiting does not complete settlement. A later
call can observe a different state than an earlier snapshot. In particular,
an earlier `IN_REVIEW` result does not guarantee a later retrieval is denied:
the retrieval call itself can advance a due release. Poll with bounded waits
and obey your client's call/time limits; the service supplies no polling loop.

## Source and delivery contract

The only `template_id` is `order_extraction_v1`; checker version is
`order_extraction_v1.0`.

`propose_agreement` receives the original CSV as a string, including its actual
newlines. The service hashes that exact UTF-8 text with SHA-256 and preserves it
in the agreement. Do not substitute a filename or literal backslash-n sequences
for decoded CSV text.

Source rules:

- Required column names are exactly `Order`, `Units`, and `Price`, including
  case. Their order may vary. Extra columns are allowed and ignored by checking.
- Headers must be unique and nonempty, including no whitespace-only header.
  Required names are not trimmed or renamed.
- Each nonempty CSV row must have the same width as the header. Empty CSV rows
  are skipped. Header-only CSV is accepted as zero orders.
- Order IDs are strings, nonempty after a whitespace check, and unique as
  supplied. Preserve the original ID rather than trimming it.
- `Units` must be an integer written with digits and an optional sign; surrounding
  whitespace is allowed. The parser does not require positive quantities.
- `Price` is parsed with `Decimal` after removing `$` characters and surrounding
  whitespace. It must be finite. There is no positive-price restriction.
  Do not use binary floating-point arithmetic to convert money.

Delivery is a JSON array containing exactly one object for each source order.
Each object has exactly these four fields, with no missing or extra fields:

| Field | Type | Required value |
| --- | --- | --- |
| `order_id` | string | Original source `Order` |
| `quantity` | integer | Source `Units` |
| `unit_price_cents` | integer | `Decimal(Price without $) * 100`, rounded using `ROUND_HALF_UP` |
| `total_cents` | integer | `quantity * unit_price_cents` |

Round each unit price **before multiplication**. JSON booleans, decimal numbers,
and numeric strings are not integers for delivery checking. Array order is not
significant, but missing, duplicate, and unexpected order IDs are errors. Supply
the array itself as `delivery`, rather than a JSON-encoded string.

Small example, unrelated to the later evaluation data:

```csv
Order,Customer,Units,Price
G41,Synthetic-Example,2,$7.125
```

The corresponding delivery is:

```json
[{"order_id":"G41","quantity":2,"unit_price_cents":713,"total_cents":1426}]
```

The dollar total is $14.26. Rounding $14.250 directly would not follow this
template's unit-first rule.

## Tools and permissions

These are the complete eleven tools. Arguments shown below are the complete
accepted argument names. Tool discovery provides the machine-readable schemas.
Unexpected arguments and invalid argument types can be rejected by MCP/SDK
validation before a business response is produced.

| Tool | Caller | Arguments | Successful result / purpose |
| --- | --- | --- | --- |
| `list_templates` | both | none | `templates`, each with `template_id` and negotiable term values |
| `propose_agreement` | buyer | `template_id`: string; `source_csv`: string | New `job_id`, `version: 1`, `status: "PROPOSED"`, `source_hash`, `checker_version` |
| `list_jobs` | both | none | `jobs`: summaries with `job_id`, `status`, `current_version`, `your_acceptance` |
| `get_job` | both | `job_id`: string | Current terms, original source, status, agreement/submission versions and started deadlines; shape below |
| `counter_agreement` | provider | `job_id`: string; `repair_window_minutes`: integer | `job_id`, new `version`, `status: "COUNTERED"` |
| `accept_agreement` | both | `job_id`: string; `version`: positive integer | `job_id`, `version`, `accepted_by` identities, `status` |
| `fund_job` | buyer | `job_id`: string | `job_id`, `status: "FUNDED"`, `simulated: true` |
| `submit_delivery` | provider | `job_id`: string; `delivery`: array of objects | `job_id`, `submission_version`, computed `verdict`, `release_allowed: false` |
| `get_result` | both | `job_id`: string; `submission_version`: positive integer | Check report, settlement status and terminal receipt; shape below |
| `challenge_result` | both, with limits below | `job_id`: string; `submission_version`: positive integer; `reason_code`: string | `challenge_id`, `outcome`, `reason` |
| `retrieve_delivery` | buyer | `job_id`: string | `job_id`, `delivery`, only after confirmed release |

Example template response:

```json
{"templates":[{"template_id":"order_extraction_v1","negotiable":{"repair_window_minutes":[5,10]}}]}
```

Only `repair_window_minutes` is negotiable, and only 5 or 10 is allowed. A new
proposal defaults to 5 and fixes `max_repairs` at 1. A counter is permitted only
in `PROPOSED` or `COUNTERED`, creates a new agreement version, and makes earlier
acceptances insufficient. Accepted terms cannot be changed. Acceptance requires
the current agreement version and remains open only through `ACCEPTED`.
`fund_job` requires both parties' acceptance; repeating it while `FUNDED` does
not record a second funding event or restart the deadline.

Example `get_job` response before submission (the actual job ID is generated):

```json
{
  "job_id": "<actual job ID>",
  "status": "PROPOSED",
  "version": 1,
  "current_submission_version": 0,
  "terms": {
    "template_id": "order_extraction_v1",
    "source_csv": "Order,Customer,Units,Price\nG41,Synthetic-Example,2,$7.125\n",
    "repair_window_minutes": 5,
    "max_repairs": 1
  },
  "source_csv": "Order,Customer,Units,Price\nG41,Synthetic-Example,2,$7.125\n",
  "deadlines": {}
}
```

`version` is the agreement version. `current_submission_version` is independently
0 before submission and increments for each stored submission, including UNKNOWN
checks. Use that discovered value to request the current report; do not assume
submission 1. `deadlines` contains only deadlines that have started, using the
keys `first_submission`, `repair`, `review`, and `recovery`. Values are UTC ISO
timestamps. Old deadline fields can remain present after a state transition;
interpret them with the current status.

## Checking, deadlines, repair and settlement

| Status | Meaning / next eligible behavior |
| --- | --- |
| `PROPOSED`, `COUNTERED` | Current agreement awaits mutual acceptance; provider may counter |
| `ACCEPTED` | Both accepted; buyer may confirm simulated funding |
| `FUNDED` | Provider may submit before the first-submission deadline |
| `SUBMITTED` | Submission stored; checking runs synchronously before the tool returns |
| `FAILED` | Computed FAIL; one conclusive repair is allowed within the agreed window |
| `CHECK_ERROR` | UNKNOWN or invalid check provenance; bounded retry without consuming a repair |
| `IN_REVIEW` | Current compatible PASS; review must close without an accepted challenge |
| `RELEASED` | Simulated release recorded; buyer may retrieve the current delivery |
| `CANCELLED` | Terminal cancellation; funded jobs receive a simulated refund |

The first-submission deadline starts at funding (default five minutes). A FAIL
starts the agreed five- or ten-minute repair window. A repair must address the
actual report; the service permits only one conclusive repair. Further UNKNOWN
checks do not consume the repair, but do not grant unlimited time: recovery uses
the submission's stored response deadline. An UNKNOWN after a FAIL does not
restart the repair clock. PASS begins review (server default ten seconds; HW9
connections explicitly use two seconds). At the deadline or later, a permitted
call applies expiration/release before its requested action.

Only the current submission can authorize release. Release requires mutual
current-version acceptance, simulated funding, compatible PASS evidence, a
closed review with no accepted challenge, no refund, and a recorded
`SIMULATED_RELEASE`. Funding, release and refund are recorded as
`SIMULATED_FUNDING`, `SIMULATED_RELEASE`, and `SIMULATED_REFUND`, with at most one
event of each type per job. A PASS response alone is not release evidence.

`get_result` returns this shape (example after a FAIL, before settlement):

```json
{
  "job_id": "<actual job ID>",
  "agreement_version": 1,
  "submission_version": 1,
  "checker_version": "order_extraction_v1.0",
  "verdict": "FAIL",
  "errors": [{"code":"MISSING_ORDER","order_id":"G41"}],
  "release_allowed": false,
  "settlement": {"status":"NONE","simulated":true},
  "receipt": null
}
```

The computed verdict is PASS if all checks pass, FAIL for invalid delivery,
or UNKNOWN if checking itself raises an exception. Stored reports are retained
per submission. `release_allowed`, settlement, and receipt reflect current job
state; an older PASS does not authorize a newer submission's release.
Settlement status is `NONE`, `RELEASED`, or `REFUNDED`. A terminal receipt includes
`job_id`, `status`, `cancellation_reason`, `provider_fault`, `agreement_versions`,
`acceptances`, submission metadata, `check_results`, `challenges`, and
`settlement_events`. It does not contain private delivery bodies. Agreements
and check records in the receipt include source hashes/checker provenance.

Checker error codes are `MISSING_ORDER`, `UNEXPECTED_ORDER`, `DUPLICATE_ORDER`,
`MISSING_FIELD`, `UNEXPECTED_FIELD`, `WRONG_TYPE`, `WRONG_QUANTITY`,
`WRONG_UNIT_PRICE`, `WRONG_TOTAL`, and `MALFORMED_DELIVERY`. Entries include
`order_id` and `field` when applicable, and `expected`/`actual` for value errors.
Non-array or otherwise malformed delivery yields FAIL rather than an agent-set
verdict. SDK-level malformed requests are a separate protocol/validation issue.

`retrieve_delivery` before release returns `PERMISSION_DENIED`. For a deterministic
access-denial check, attempt retrieval before acceptance/funding, rather than
racing the short review window. A successful retrieval returns:

```json
{"job_id":"<actual job ID>","delivery":[{"order_id":"G41","quantity":2,"unit_price_cents":713,"total_cents":1426}]}
```

## Challenges and errors

Challenges address the current submission and agreement only, during `IN_REVIEW`
or `FAILED` and strictly before the applicable review/repair deadline:

- `SOURCE_MISMATCH`: either role; compare the check's source hash to the agreement.
- `CHECKER_VERSION_MISMATCH`: either role; compare checker versions.
- `DISPUTE_FAIL`: provider only for a current FAIL; records the dispute without
  changing the verdict. If unresolved when repair expires, cancellation reason
  is `DISPUTED_FAIL`, with no provider fault.

Provenance challenges return `ACCEPTED` only for a mechanically verified
mismatch; otherwise `REJECTED`. Invalid evidence enters `CHECK_ERROR`, blocking
release. `DISPUTE_FAIL` returns `RECORDED`. A buyer cannot veto a correct PASS
by disagreeing. Subjective arbitration is not implemented.

Business errors return an ordinary tool result with `code`, `message`, and
optional `details`. When otherwise unique, nonempty headers omit required
columns, the response identifies the missing names in contract order and the
original received headers in their original order. For example:

```json
{
  "error": {
    "code": "INVALID_TERMS",
    "message": "Required source columns are missing",
    "details": {
      "missing_columns": ["Order", "Units", "Price"],
      "received_columns": ["order_no", "client", "qty", "unit_price"]
    }
  }
}
```

Empty, duplicate, blank or whitespace-only headers are checked first and retain
the generic error. Other malformed source data also retains this response:

```json
{"error":{"code":"INVALID_TERMS","message":"source_csv must contain valid, unambiguous order data"}}
```

The generic missing-header response is preserved historically at `hw9-docs-v0`.
Current details are diagnostic feedback: source names are not trimmed, renamed,
or accepted automatically. The accepted source contract is unchanged. Invalid
proposals create no job. Existing errors without details retain their prior shape.

| Business code | Meaning |
| --- | --- |
| `PERMISSION_DENIED` | Wrong role, or buyer retrieval before confirmed release |
| `NOT_FOUND` | Job or requested submission report does not exist |
| `INVALID_STATE` | Action is incompatible with the current lifecycle state |
| `INVALID_TERMS` | Unsupported template/terms, invalid source, version value or reason code |
| `VERSION_MISMATCH` | Stale agreement acceptance or challenge of a noncurrent submission/agreement |
| `DEADLINE_PASSED` | Applicable submission/challenge deadline has expired |
| `REPAIR_LIMIT_REACHED` | Agreed conclusive repair has been used |

Read the returned code/message and current state before deciding what to do.
Business errors do not imply a transport failure. Even a permitted action that
returns a business error can have advanced other due jobs first. Calls denied
by role permission do not advance jobs. Transport failures, missing processes,
and SDK argument validation errors are distinct from these dictionaries.

## Operator setup and connection examples

This section is for the person configuring clients, not an already-connected
agent. Use Python 3.11; the Y1 environment was Python 3.11.5 with `mcp==2.3.0`.
There is no exact Python patch-version gate.

From the runtime repository root:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python examples/connect.py --db "$PWD/runtime/hw9/connection-example/live.sqlite"
```

`examples/connect.py` initializes both actual SDK clients, lists their tools,
and calls `list_templates`. It is a connection example, not a fresh-agent
preflight or a task launcher. Use a fresh demo database path: permitted calls
can advance existing jobs. It supplies this explicit configuration per process:

| Setting | Buyer process | Provider process |
| --- | --- | --- |
| command | Absolute path of invoking Python interpreter | Same interpreter |
| arguments | `-m server.mcp_server` | Same |
| working directory | Explicit runtime repository root | Same |
| `TERMSMET_IDENTITY` | `buyer` | `provider` |
| `TERMSMET_DB_PATH` | One absolute SQLite file path | Exactly the same file |
| `TERMSMET_REVIEW_SECONDS` | `2` | `2` |
| `TERMSMET_FIRST_SUBMIT_MIN` | `5` | `5` |

For another MCP client, configure equivalent stdio server entries using its
supported working-directory mechanism. Do not rely on an inherited directory.
Launch one process per role. The server entrypoint is `python -m server.mcp_server`.
Both duration settings must be positive finite numbers; defaults remain ten
seconds and five minutes when omitted. Identity must be buyer/provider and the
database path must be absolute. Invalid startup settings fail with diagnostics
on stderr; stdout is reserved for MCP. SQLite uses WAL and serialized write
transactions across processes.

Neither the service nor the SDK connection example requires model credentials.
Keep any future model-client credentials in the invoking environment, outside
prompts/configuration examples and server environments. Do not expose shell,
filesystem, the SQLite file, private submissions, or expected answers through
agent tools. The connection example does not enforce a model client's isolation;
the HW9 restricted launcher/preflight is documented in `HW9_HANDOFF.md`. Its
SDK stage is setup validation; the separate live restricted Claude preflight
passed at runtime revision `4b91a623c5d6f0443d5df8a302da032aec5595ea` with one
actual `list_templates` exchange. This is setup evidence, not the main experiment.

## Current scope

This baseline adds submission-version discovery and interface documentation.
It does not change accepted inputs, delivery typing, checking, agreement or
settlement rules, server defaults, or historical HW7/HW8 revisions. It does not
provide a hosted endpoint, real payments, production authentication, background
settlement, extra templates, or agent reasoning. Y2 adds execution tools and
preflight separately from the service interface. Y3 supplies a scripted
unsupported-input probe and predefined boundary criteria. Y4 adds structured
missing/received-column diagnostics without changing acceptance or settlement.
The formal B1 comparison is recorded separately; final technical handoff and
main cold-start evidence remain later work.

