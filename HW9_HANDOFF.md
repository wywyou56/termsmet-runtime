# HW9 technical handoff — interim Y2 interface contract

**This is not the final Y5 handoff.** Y1 and the Y2 execution tools are implemented;
deterministic checks exercise actual MCP processes and synthetic CLI clients.
The real restricted Claude preflight remains pending until
authorized model access is available. Y3 boundary evidence, Y4 diagnostic
improvement, final reproduction/publication/access checks and tags are pending.
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

Y2 remains partially complete until the actual restricted Claude preflight
passes with environment-provided access. Do not infer that result from fake CLI
tests or the SDK stage. Y3 must freeze and observe the original unsupported-input
diagnostic before Y4 changes it. Y5 must provide the final results/handoff,
independent-checkout verification, reviewed publication, tags, and confirmed
Sheila access to this runtime repository. No tags or publication are authorized
at this checkpoint.
