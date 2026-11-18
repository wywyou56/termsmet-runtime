# HW9 technical handoff — interim baseline and interface contract

**This is not the final Y5 handoff.** Y1 and the Y2 execution tools are implemented;
deterministic checks exercise actual MCP processes and synthetic CLI clients.
The real restricted Claude preflight passed at clean runtime revision
`4b91a623c5d6f0443d5df8a302da032aec5595ea` (local `preflight-y2-04`, one matched
actual `list_templates` call, exit 0). Y3 preserved the generic boundary response
at `hw9-docs-v0`, commit `c1f536295bd0184a7e1a0684fc388d59d9f245b9`.
Y4 implements the additive missing/received-column diagnostic; its formal rerun
is recorded separately from the clean Y4 revision. Y5 final reproduction,
publication, access checks and the final tag remain pending.
No main cold-start experiment has been run. The final handoff will include the
full Y1–Y5 results and Sheila's self-contained S1–S5 instructions.

TermsMet remains an MCP service. The new tools run Claude Code clients; they do
not implement agent reasoning or choose negotiation/submission/settlement calls.
All settlement is simulated. No private HW7 benchmark module is required or
imported. The historical HW7 harness and server defaults are unchanged.

## Install and verify setup

The runtime is `https://github.com/wywyou56/termsmet-runtime`. This work is on
local branch `hw9`; publication is reserved for Y5. Python 3.11.5, MCP 2.3.0 and
Claude Code 2.1.317 were observed during Y2. Python patch versions are recorded,
not used as an exact-patch rejection gate. POSIX process groups (macOS/Linux)
are required by this launcher.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m coldstart.preflight \
  --out runtime/hw9/preflight-01 --model claude-haiku-5-5 --effort medium
```

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

Those task/data files are intentionally absent at Y2. Do not create or run the
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

## Work still required

Y2 passed its actual restricted Claude preflight; that is setup verification,
not the main cold-start result. The original Y3 unsupported-input observation
remains preserved for the Y4 comparison. Y5 must provide the final results/handoff,
independent-checkout verification, reviewed publication, tags, and confirmed
Sheila access to this runtime repository. Y4 authorizes a local commit and one
fresh improved boundary attempt only. Publication, the final tag and the main
cold-start run remain outside Y4.
