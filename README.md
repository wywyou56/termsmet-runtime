# TermsMet minimal runtime

TermsMet is a local MCP stdio service for a versioned order extraction agreement, deterministic delivery checks, repair and conditional delivery. Funding, release and refunds are simulated; this is not a payment service. Identities are local demo identities, not production authentication.

Read [AGENT_GUIDE.md](AGENT_GUIDE.md) for the complete connected-agent interface,
tool arguments/results, permissions, validation, deadlines, and limitations.

## Setup

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Launch a process per identity with a shared absolute SQLite path. The server reserves stdout for MCP.

```sh
TERMSMET_IDENTITY=buyer TERMSMET_DB_PATH=/absolute/path/to/termsmet.sqlite .venv/bin/python -m server.mcp_server
```

Use `provider` as the other identity. A client should use the official MCP SDK over stdio. The service offers 11 tools: list_templates, propose_agreement, counter_agreement, accept_agreement, list_jobs, get_job, fund_job, submit_delivery, get_result, challenge_result and retrieve_delivery. No tool accepts an identity argument.

An executable [connection example](examples/connect.py) initializes both roles
with an explicit runtime directory/interpreter and a shared absolute database:

```sh
.venv/bin/python examples/connect.py --db "$PWD/runtime/hw9/connection-example/live.sqlite"
.venv/bin/python -m unittest discover -s tests -v
```

The example explicitly supplies two-second review and five-minute first submission
settings for HW9. The server default review remains **10 seconds**, and its first
submission default remains five minutes (`TERMSMET_FIRST_SUBMIT_MIN`). Every
permitted call advances due jobs; there is no background settlement worker.

## HW9 checkpoint status

Y1 provides the guide, connection example, and `current_submission_version` in
`get_job` (0 before submission). Y2 adds the configurable restricted Claude
launcher, pass-through MCP observer, bounded cleanup/backup and SDK/Claude
preflight. See [the interim handoff](HW9_HANDOFF.md) for commands, task placeholders,
the frozen evidence schema and failure behavior.

```sh
.venv/bin/python -m coldstart.preflight \
  --out runtime/hw9/preflight-01 --model claude-haiku-5-5 --effort medium
```

Supply authorized model access through `ANTHROPIC_API_KEY` in the invoking
environment. Never put its value in a command or committed file. The default
endpoint is Parley; an environment-provided `ANTHROPIC_BASE_URL` can override it.
Missing credentials record a blocked preflight, while the SDK checks still run.
Y2 is complete: local `preflight-y2-04` passed at clean runtime commit
`4b91a623c5d6f0443d5df8a302da032aec5595ea`, using Claude Code 2.1.317,
`claude-haiku-5-5`, medium effort, and one actual matched `list_templates`
request/response. Raw evidence is preserved locally under `runtime/hw9/`;
reviewed publication is reserved for Y5. Fake CLI tests do not satisfy this gate.

Y3 froze the [scripted boundary criteria](coldstart/boundary_criteria.md), B1 input,
and official-SDK probe at local `hw9-docs-v0`, commit
`c1f536295bd0184a7e1a0684fc388d59d9f245b9`. The single formal baseline run is
preserved in `runtime/hw9/b1-v0`: execution completed, `INVALID_TERMS` rejected the
input, all seven business tables were empty, and the response was generic.
Do not rerun or overwrite that attempt or move the baseline tag.

Y4 adds optional `error.details.missing_columns` and `received_columns` for valid
headers that omit required names. Accepted inputs, other validation errors,
checker version, and settlement behavior are unchanged. The unchanged probe is
run from the tested clean Y4 commit into a fresh directory:

```sh
.venv/bin/python -m coldstart.boundary_probe \
  --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v1
```

The probe records **execution**, **correct rejection**, **verified zero business
state changes**, and **diagnostic richness** separately. The preserved generic
`INVALID_TERMS` is a baseline observation, not an execution failure. The probe makes
one actual buyer proposal, then checks a read-only snapshot; no Claude session
or credentials are used. Compare v0/v1 source, client settings, rejection and
state checks independently from diagnostic richness. Richer feedback alone does
not establish improved agent success.

The reviewed boundary/setup subset is in [evidence/hw9](evidence/hw9/README.md):

```sh
python3.11 evidence/hw9/verify.py
```

This offline verifier checks hashes, matched exchanges, diagnostics and recorded
state exports; it does not open an unpublished database, run an experiment or
score the main task. See [You's results](HW9_YOU_RESULTS.md) and the
[self-contained S1–S5 handoff](HW9_HANDOFF.md). Raw originals remain local.
Y5 independent local reconstruction passed: fresh installation, **50 tests**,
offline verification and one actual restricted preflight. Runtime code remains
unchanged from the tested candidate. Current status: **Technical handoff ready;
collaborator access pending.** Owner-approved publication, anonymous public-clone
offline verification and accepted runtime-repository write access for Sheila
remain required; technical preparation alone is not full Y5 completion.
Main task files/data belong to Sheila's S1 and are intentionally absent. No HW9
main cold-start result is claimed. No historical benchmark behavior has changed.

The service supports one template and minimal mechanical challenges, not
subjective arbitration or marketplace matching. See
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) for historical copied-file
hashes and the HW9 derivative change description. Raw runs, environments,
credentials, logs, and databases are ignored and must stay out of public commits.
