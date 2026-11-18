# HW9 technical handoff — You Wu to Sheila Hsu

**Publication and collaborator access must be confirmed before transfer.**
Y1–Y4 are implemented and verified; the results and reviewed evidence are in
`HW9_YOU_RESULTS.md` and `evidence/hw9/`. Deterministic checks exercise actual MCP
processes and synthetic CLI clients.
The real restricted Claude preflight passed at clean runtime revision
`4b91a623c5d6f0443d5df8a302da032aec5595ea` (local `preflight-y2-04`, one matched
actual `list_templates` call, exit 0). Y3 preserved the generic boundary response
at `hw9-docs-v0`, commit `c1f536295bd0184a7e1a0684fc388d59d9f245b9`.
Y4 recorded its successful structured rerun at
`7d70e99801c512d5d7e4653f0cf451ed33eb4b45`, preserving the baseline. The Y5
reconstruction record identifies the tested candidate and runtime hashes;
publication, its anonymous-clone check and accepted write access are separate
acceptance conditions. No main cold-start experiment has been run. The S1–S5
contract below is self-contained; no earlier chat or private planning file is needed.

TermsMet remains an MCP service. The new tools run Claude Code clients; they do
not implement agent reasoning or choose negotiation/submission/settlement calls.
All settlement is simulated. No private HW7 benchmark module is required or
imported. The historical HW7 harness and server defaults are unchanged.

## Install and verify setup

The runtime is `https://github.com/wywyou56/termsmet-runtime`. This work is on
branch `hw9`; links become usable after owner-approved publication. Python 3.11.5, MCP 2.3.0 and
Claude Code 2.1.317 were observed during Y2. Python patch versions are recorded,
not used as an exact-patch rejection gate. POSIX process groups (macOS/Linux)
are required by this launcher.

```sh
git clone --branch hw9 https://github.com/wywyou56/termsmet-runtime.git
cd termsmet-runtime
git rev-parse HEAD
git rev-parse 'hw9-v1^{commit}'
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evidence/hw9/verify.py
.venv/bin/python -m coldstart.preflight \
  --out runtime/hw9/preflight-01 --model claude-haiku-5-5 --effort medium
```

Before editing, require the two printed commits to equal the full handoff hash
in the owner's message. A mismatch means you are not at the agreed handoff;
do not reset unrelated work. `hw9-docs-v0` remains the historical baseline and
`hw9-v1` the immutable technical handoff. Do not move either tag. You owns `hw9`
until the handoff message; Sheila owns it afterward.

Versioned documentation after publication:
[guide](https://github.com/wywyou56/termsmet-runtime/blob/hw9-v1/AGENT_GUIDE.md),
[results](https://github.com/wywyou56/termsmet-runtime/blob/hw9-v1/HW9_YOU_RESULTS.md),
[handoff](https://github.com/wywyou56/termsmet-runtime/blob/hw9-v1/HW9_HANDOFF.md),
[reviewed evidence](https://github.com/wywyou56/termsmet-runtime/tree/hw9-v1/evidence/hw9).
Use your own authorized model access. You do not need You's terminal, environment,
private benchmark, local evidence directories, credential file or earlier chat.

Supply `ANTHROPIC_API_KEY` privately through the invoking environment. Do not put
it in a command, task, guide, repository file, manifest, or MCP config. The
default endpoint is `https://parley.api.mit.edu`; `ANTHROPIC_BASE_URL` in the
invoking environment may select another HTTP(S) endpoint without embedded
credentials/query/fragment. No OAuth/keychain authentication is attempted in bare
mode. Model/effort must work in preflight before the later formal experiment;
there is no automatic model substitution.

Preflight first initializes actual buyer/provider SDK connections, verifies
exactly eleven tools, and confirms that a provider can read a new synthetic
buyer proposal from the shared database. It does not fund that job. It then
starts one restricted fresh Claude session, which must actually call and receive
`list_templates`. The advertised inventory and a final claim alone cannot pass.

`preflight.json` records both stages and overall `passed`. SDK evidence is under
`sdk/` (`sdk.json`, MCP/control logs, snapshot); the Claude stage is under
`claude/` using the run schema below. Exit 0 means both stages passed. Missing
credentials yield exit 2 and `blocked_missing_credential`, not a passing preflight.
SDK or other execution failures yield exit 1; interruption yields exit 130.
Use a new numbered output path after any failed/blocked attempt.

The unit tests use clearly labeled synthetic CLI processes. Their outputs are
test fixtures, never live Claude or cold-start evidence.

## Scripted B1 boundary baseline

Read `coldstart/boundary_criteria.md`, which is separate from Sheila's S1 main
criteria. The checked-in B1 source has unsupported headers. The tagged v0 guide
documents its generic error; the current guide documents the additive diagnostic
and the same accepted source contract. Structured assessment fixtures were tested
before the freeze without temporarily changing the server.

The following historical command was run once from the exact clean v0 tag. Its
input, response, logs and snapshot are preserved. Do not rerun or overwrite that
attempt. Historical reproduction requires the tag in a separate fresh checkout:

```sh
.venv/bin/python -m coldstart.boundary_probe \
  --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v0
```

This is a fixed actual-MCP script, not a fresh LLM agent. It needs no model key.
It initializes a buyer identity with all eleven tools, then makes exactly one
`propose_agreement` request containing the original decoded CSV. No subsequent
business calls are made. A supervised worker bounds SDK initialization and
teardown. Defaults are 15 seconds per startup/request and 45 seconds for the
worker, plus bounded cleanup/backup. Both baseline and rerun use two-second
review and five-minute first submission settings.

The output directory must be absent or empty. `probe.json` records four separate
outcomes: `execution_status`, `unsupported_input_correctly_rejected`,
`zero_state_changes_verified`, and `diagnostic_richness_observed`. Exit 0 requires
completed execution, rejection with `INVALID_TERMS`, and verified zero business
rows/events. It does not require rich diagnostics. Unknown state is JSON null,
not true. Missing snapshots, failed cleanup, unmatched requests/responses, and
SDK failures prevent completed execution. The original error remains unmodified.

`source.csv` preserves input bytes. `worker.json` records the SDK request,
response and inventory. `mcp-buyer.jsonl` and `buyer-control.jsonl` use the existing
protocol/control formats; worker/server diagnostic logs are retained. There is
no LLM stdout file. Runtime/tag commits, clean/dirty state, source/guide/criteria/
probe hashes, historical provenance, configuration and timestamps are recorded.
The final consistent `termsmet.sqlite` is inspected read-only to count all seven
business tables and settlement event types. No observer calls advance the service.

The recorded baseline execution completed and correctly rejected the input with
`INVALID_TERMS`; all seven business tables were empty. Its generic message did
not identify missing or received columns. Never move the baseline tag or edit
its evidence.

## Y4 additive diagnostic and comparison

The parser now raises a small `ValueError` subclass only for otherwise valid
headers missing required column names. Empty, duplicate and blank-header
validation still precedes that case. The service propagates optional details:

```json
{"error":{"code":"INVALID_TERMS","message":"Required source columns are missing","details":{"missing_columns":["Order","Units","Price"],"received_columns":["order_no","client","qty","unit_price"]}}}
```

Other errors without details keep their original shape. The service does not
parse the source a second time. Headers are not normalized; accepted inputs,
monetary conversion, delivery checking, tool schemas, checker version, deadlines,
repair rules and settlement gates remain unchanged. The valid regression
transaction uses an extra source column, two-second review, bounded real-time
polling that accepts an already `RELEASED` job, and a hand-computed delivery.

After testing and committing Y4, run the same probe once from that clean revision:

```sh
.venv/bin/python -m coldstart.boundary_probe \
  --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v1
```

Keep the probe, B1 input and predefined criteria byte-identical to v0. Compare
the input/request, inventory, SDK/interpreter and client settings; record new
runtime, guide and provenance hashes. Report execution, rejection, verified
zero state changes, and diagnostic richness separately. The first three should
remain successful and richness should become structured. Preserve both attempts
and the local comparison independently of Git until reviewed Y5 publication.
Richer boundary diagnostics alone do not establish better agent success.

## Launcher invocation and task contract

The intended later invocation, **after Sheila creates S1 inputs**, is:

```sh
.venv/bin/python -m coldstart.launch \
  --buyer-task coldstart/tasks/buyer.md \
  --provider-task coldstart/tasks/provider.md \
  --source-csv coldstart/data/H9.csv --guide AGENT_GUIDE.md \
  --out runtime/hw9/main-01 \
  --review-seconds 2 --first-submit-minutes 5 \
  --wall-seconds 900 --tool-limit 60 \
  --model claude-haiku-5-5 --effort medium
```

Those task/data files are intentionally absent from You's half. Do not create or run the
main experiment as part of You's half. Each task template must contain exactly
one `{{AGENT_GUIDE}}`; the buyer also needs exactly one `{{SOURCE_CSV_JSON}}`,
while the provider must have none. Unknown/unclosed placeholders are rejected.
Guide injection is verbatim. Source injection is a JSON string encoding the
original decoded UTF-8 CSV, preserving CRLF and the final newline. Only the buyer
prompt contains the source. A neutral note explains decoded CSV text. No
expected artifacts, draft, mandatory version, FAIL, or call sequence is added.

The launcher reads prompts into stdin rather than command-line arguments. Each
role uses a fresh process and empty temporary working directory with explicit
MCP configuration. Built-in tools, project memory, skills, hooks, prior sessions,
other MCP servers, shell/file/database access, and message relaying are excluded
by CLI settings and verified advertised inventory. Exact CLI arguments are
recorded. Model credentials are cleared from the MCP child environment, and the
server receives only minimal OS and explicit TermsMet settings.

The review/submission/wall/call defaults are 2 seconds, 5 minutes, 900 seconds,
and 60 attempted calls per role. Durations must be positive finite numbers and
the tool cap a positive integer. Lower caps are useful for setup tests; formal
HW9 runs must use the agreed 900/60 caps. `--claude-bin` selects an executable;
`--startup-seconds` defaults to 15; `--manual-help` defaults to `none reported`
and must truthfully disclose any assistance. These settings do not change server
defaults or historical benchmark settings.

Metadata commands, including CLI version/help, are bounded by five seconds and
the remaining wall budget. Client startup, prompt input, and inventory admission
are bounded by `--startup-seconds`. SDK initialization/tool requests use the
same per-request bound, plus an overall SDK-stage bound of six times that value.
The SDK stage runs in a separately supervised process, so shielded SDK teardown
cannot extend that deadline indefinitely; its registered transport groups are
also cleaned up by the supervisor. SDK configuration, worker output and partial
worker results are retained with the stage evidence.
Missing inventory fails rather than waiting indefinitely. SIGINT/SIGTERM,
timeout, startup/proxy errors, model/inventory mismatch and call exhaustion are
recorded. A normally finished role does not stop the other role.

## Frozen evidence interface, schema version 1

All raw run artifacts live under the chosen ignored output directory. Existing
nonempty directories are refused. Keep unsuccessful attempts. The root contains:

| File | Contract |
| --- | --- |
| `buyer.jsonl`, `provider.jsonl` | Every retained CLI stdout line, including complete final output: `{"received_at": <Unix seconds>, "line": "<original stdout line without its newline>"}` |
| `mcp-buyer.jsonl`, `mcp-provider.jsonl` | `{"timestamp": <Unix seconds>, "direction": "request" or "response", "message": <parsed JSON-RPC object>}`; original IDs retained |
| `buyer-control.jsonl`, `provider-control.jsonl` | Timestamped process registration, verified server inventory, attempts, forwarding, budget-block and proxy/cleanup events |
| `manifest.json` | Settings, versions, revision/dirty status, input/prompt hashes, exact CLI commands, role inventories, start/end/exit observations, usage/cost, failure reasons, cleanup and snapshot status |
| `prompt-<role>.md`, `mcp-<role>.json` | Exact rendered prompt and explicit local MCP configuration; no credentials |
| `client-<role>.stderr.log`, `server-<role>.stderr.log` | Diagnostic output; server stdout remains MCP-only |
| `termsmet.sqlite` | Consistent SQLite backup, only when a live database exists and cleanup/backup succeed |

MCP `direction` denotes client-to-server versus server-to-client traffic,
including protocol notifications. Each request is logged before admission. A
blocked call therefore appears in MCP records without a matching response;
consult control events before treating that as an unexplained missing response.
The proxy never synthesizes a response or alters a forwarded line.

Control `tool_attempt` events contain `count` and `request_id`; `tool_forwarded`
records admitted calls. `tool_budget_exhausted` records the first blocked attempt
(61 for a cap of 60). Business errors count. Manifest role fields summarize
`tool_attempts`, `forwarded_calls`, and `blocked_calls`. Protocol setup methods
such as initialize/list-tools are not business tool attempts.

`agents.<role>` records `inventory_verified`, `advertised_tools`, `observed_model`,
`started_at`, `result_received_at`, `exit_observed_at`, `exit_code`,
`stdout_complete`, prompt hash, and available `usage`, `modelUsage`, and
`total_cost_usd`. Missing usage/cost is `N/A`, never zero. The manifest records
`started_at`, `finished_at` and `elapsed_seconds`; final elapsed time includes
bounded cleanup/backup after a timeout. `execution_status: completed` describes
client execution only. `transaction_status` remains `not_evaluated`; no success
scorer or settlement calls run at shutdown.

Unexpected credential-bearing stdout is withheld with an explicit failure and
incomplete-output flag, rather than written into evidence. Diagnostics/manifest
values redact the invoking key. Normal retained stdout lines are unchanged.
This is not publication sanitization: raw logs can still contain machine paths
and private task information and must not be committed or published unreviewed.

## Shutdown and snapshot semantics

Only trial-owned client/proxy process groups are signaled. Proxies register their
groups; servers stay in the proxy group. TERM and KILL phases each have bounded
waits. The launcher checks group disappearance and re-reads registrations during
shutdown. Cleanup failure prevents snapshotting and preserves live state.
An OS sandbox can deny a post-termination process-group probe; that is recorded
as unconfirmed cleanup with preserved live state, rather than assumed success.

The live database is `.work/live.sqlite`, distinct from `termsmet.sqlite`.
After shutdown, the launcher opens the live file read-only and uses SQLite
backup with a five-second deadline. WAL commits are included. A temporary
`termsmet.sqlite.partial` is renamed only after successful backup. No extra MCP
calls are made to advance a job or complete settlement.

`snapshot.status` is:

- `available`: final backup path and SHA-256 are recorded.
- `unavailable`: no nonempty live database was created, or shutdown could not be
  confirmed. No empty database is manufactured.
- `failed`: backup failed; the reason and partial path are recorded.

Temporary live state is deleted only after successful cleanup and backup, or
when there was no database to preserve. Backup/cleanup failures retain available
evidence and live state. Preserve the whole failed output directory for diagnosis.

## Verification, publication and access status

Run the offline package verifier without a model key. It checks file hashes,
matched calls, diagnostics, recorded state exports and actual preflight evidence.
It is not an experiment runner or the main-task scorer. Exported counts and
snapshot hashes are recorded evidence, not independent inspection of an
unpublished database. Read the package manifest for original/published hashes
and explicit path/account-metadata sanitization. Raw originals are preserved.

Y5 uses exactly two reconstruction checks: one independent local clone with a
fresh environment, all tests, offline verification and one actual restricted
preflight; then an anonymous public clone of the final commit for offline
verification after publication. The candidate revision and actual results are
recorded in `evidence/hw9/reconstruction.json`; runtime hashes must remain
unchanged between candidate and final commit. Documentation/evidence may change.

The owner must authorize the concrete final branch/tag hashes before normal
publication. No force-push, tag movement or merge into historical `main` is needed.
The final owner-forwarded message supplies the full handoff hash and status.
Access must be accepted write access for `sheilahf860316` on
`wywyou56/termsmet-runtime`, not merely on the Town fork. Public cloning is not
proof of write access. If it cannot be verified, report **Technical handoff ready;
collaborator access pending.** Do not treat Y5 as fully complete.

## Sheila S1 — Restore and freeze the new meaningful task

1. Follow the clone/install commands, verify the exact handoff hash, read the
   guide, run tests/offline verification, and run preflight using your own model
   access. Preserve failed attempts with new numbered output directories. Confirm
   the selected model/effort really works; never silently substitute during a run.
2. Create `coldstart/data/H9.csv`: eight new synthetic orders with
   `Order,Customer,Units,Price`, unique nonempty string IDs, positive integer
   quantities and positive prices. Include a half-cent unit price, an order
   totaling exactly $100, one above $100 and one below $100.
3. Independently hand-calculate `H9_expected_delivery.json` and
   `H9_expected_report.json`. Do not import the production parser/checker.
   Convert with Decimal/ROUND_HALF_UP, round unit cents first, then multiply.
   Cross-check the arithmetic a second time before any formal main run.
4. The buyer's final output is one JSON report:

   ```json
   {"job_id":"<observed job ID>","order_count":8,"total_quantity":0,"total_amount_usd":"0.00","approval_orders":[{"order_id":"<string>","total_amount_usd":"0.00"}]}
   ```

   The numeric values above illustrate types only, not an expected answer.
   Use actual integer counts/quantity, two-decimal dollar strings, and approval
   orders whose `total_cents` is **strictly greater than 10000**. Compare lists by
   order ID; an empty approval list is valid in general. Only substitute the
   observed job ID into the independent expected report.
5. Write goal-level buyer/provider English tasks with the required placeholders.
   Buyer receives source/guide and should obtain a verified released delivery
   and use it for the report. Provider receives the guide and authorized tools
   and should complete an available extraction job and observe its terminal
   outcome. No call sequence, mandatory version, expected answer, prepared draft
   or forced FAIL/repair. Never expose the independent expected artifacts to clients.
6. Write `coldstart/criteria.md` before execution, separate from the preserved
   boundary criteria. Commit data, oracles, tasks and criteria; record the full
   pre-run revision and hashes. Source already available to the buyer means
   report accuracy/timing is evidence of checkable downstream behavior, not
   proof of its internal causal reasoning.

## Sheila S2 — Implement the independent main-run checker

Provide this interface, without calling the service or editing original evidence:

```sh
.venv/bin/python -m coldstart.check_run \
  --run runtime/hw9/main-01 \
  --expected-delivery coldstart/data/H9_expected_delivery.json \
  --expected-report coldstart/data/H9_expected_report.json
```

Write `check.json`. Open the snapshot read-only; do not use immutable mode on a
potentially WAL-backed live file. These predefined checks govern the result:

| ID | Requirement | Evidence |
| --- | --- | --- |
| C1 | Both accepted the same current agreement version; no required v2 | Receipt/database and actual calls |
| C2 | Simulated funding exists before submission | Settlement/submission records |
| C3 | Actual provider submission has current server PASS | Provider requests and persisted result |
| C4 | Exactly one simulated release, no refund/conflict, not before review deadline | Snapshot |
| C5 | Buyer actually received the released delivery, independently equal to the oracle | Successful retrieval response; strict fields/types and no missing/duplicate IDs |
| C6 | Final buyer report matches all oracle fields and was emitted after retrieval response | Timestamped output and independent report oracle |
| C7 | Manual help disclosed; each role attempted at most 60 calls with no exhaustion; within 900 seconds | Manifest, proxy events and exits |

All C1–C6 passing establishes the useful main result. Report C7 and execution
status separately. Missing, malformed or contradictory evidence is incomplete,
not passed; never infer success from process exit or an agent's claim. Parse the
final answer as one JSON object, optionally one enclosing Markdown JSON fence.
Reject competing objects or unsupported prose rather than guessing. Enforce
strict integer types (booleans are not integers), required fields, unique IDs,
and order-independent comparison of order lists.

Record friction separately: business errors, calls by role, repairs, UNKNOWNs,
exits, elapsed time and short exact excerpts of misunderstanding. Separate
interface/project issues from authentication, configuration, model availability,
launcher and budget issues; evidence can support more than one cause.
Test valid synthetic evidence, wrong totals/types, absent retrieval, reports
before retrieval, missing/malformed final JSON, duplicate releases and incomplete
runs. Preflight traces must never score as a completed transaction.

## Sheila S3 — Run and interpret the cold start

Run the documented `coldstart.launch` command only after S1/S2 are committed and
the model, guide, tasks, source, oracles and preflight revision/hashes are frozen.
Use two new sessions, the same working model/effort, two-second review,
five-minute first submission, 900-second wall cap and 60 calls per role.

Give no mid-run coaching, repairs, answers, service calls or message relay. A
passive observer may display actual events without advancing jobs. Keep every
attempt, run the independent checker, and extract the request → response →
retrieval → report chain or exact blocking interaction. A correct report without
retrieval evidence is insufficient. A setup defect can be fixed and rerun under
a new numbered directory; retain the original attempt and disclose the change.
A substantive interface failure is acceptable evidence; do not keep rerunning
until success or depend on another routine feature cycle from You.

Label the attempt self-run with fresh agent sessions. Another teammate pressing
start does not make it independent adoption. One substantive main attempt is
required; repetitions/external testers are optional and cut first if time is short.

## Sheila S4 — Four final slides and embedded product demo

Expand/replace the existing HW8 TermsMet slide so the team has exactly four
contiguous final slides in the shared Fall 2026 Demo Day deck. Preserve the blank
template and other teams' content:

| Slide | Content | Time |
| --- | --- | --- |
| 1 | Problem, buyer/provider users, shared acceptance infrastructure | 25 seconds |
| 2 | Actual MCP/SQLite architecture; Agree → Fund → Check/repair → Review/release → Retrieve; embedded demo | 60 seconds including video |
| 3 | Accurate prior HW7/HW8 results and actual HW9 main/boundary outcomes | 40 seconds |
| 4 | Failures, limitations and evidence-supported next steps | 25 seconds |

Reuse the accurate HW6 Unlisted product-demo video if available, labeling it as
product demonstration rather than HW9 cold-start footage. If unavailable or
inaccurate, make a short truthful replacement from actual execution. Embed the
YouTube video in live Slides, set Play automatically, and verify in presentation
mode; confirm Unlisted visibility. A link or PDF cannot prove playback settings.
Locate the shared deck/demo through your own team/course access; those course
assets are not a runtime dependency and no further routine deliverable from You
is required to begin S1.

Historical evidence source:
[HW7 panels](https://github.com/sheilahf860316/termsmet-hw7-evidence/blob/main/fresh-package/summary/panels.md).
Keep these qualifications when using prior results: withholding A/B differences
execute the designed policy rather than discovering a behavioral law; detailed
feedback versus verdict-only completion was 10/12 versus 4/12 across development
and fresh repair cases, with small-sample/H06 limits. Across 88 scored trials,
zero incorrect releases were observed among 69 releases (65 excludes four A2
retests). A2 reduced calls but fresh completion was 6/12 versus A's 10/12, not an
overall improvement. HW8 Town participants were scripted; lost-PASS recovery had
one rejected retry, two accepted submissions total and one release. Do not call
that recovery “without resubmitting.” HW9 claims must follow actual traces/checks.

## Sheila S5 — Final evidence, PDF, reproduction and submission

Produce a short team PDF: ideally 2–3 usability-evidence pages followed by an
export of the four slides. Include project/team/contributions, versioned guide
and runtime links/revisions, live-deck slide link, reproduction commands, setup
and what each client received, predefined checks, exact interaction excerpts,
final report or evidenced failure, self-run/manual-help disclosure, and B1
before/limitation/change/rerun evidence. State what improved and what is unproven.

Publish a reviewed subset with runtime/guide/task/source hashes, manifest,
necessary requests/responses, actual final report, independent expected artifacts,
`check.json`, and boundary comparison. Never commit credentials, personal paths,
caches, private logs or generated databases. If public reconstruction of the
main checker requires a SQLite snapshot, use a separately owner-authorized,
reviewed synthetic artifact download with its hash and commands, not a Git
commit of the database. Exports remain recorded evidence, not independent
inspection of an omitted raw database.

In a separate checkout, follow documented installation/checker commands against
the published evidence. A second live main run is optional, not a prerequisite.
Run relevant tests and `git diff --check`, review the public diff and publish
normally without force-pushing or moving tags; record the full submission
revision. Confirm exactly four contiguous TermsMet slides, embedded playable
Unlisted video, automatic playback and preserved blank template. Both members
upload the same final PDF to their own Canvas submissions. Confirm the actual
deadline in Canvas; do not infer it from an earlier schedule. No new Town PR is
required; prior integration links are historical evidence only.

You's contributions: server baseline/API preparation, execution tooling,
documentation, setup/boundary evidence and diagnostic improvement. Sheila's
contributions: new H9 task/oracles, independent checker, main experiment,
interpretation and final course artifacts. After transfer, routine setup fixes,
navigation, analysis and packaging are Sheila's work. Escalate a true blocker
only with a concrete version, command, reproduction and error.
