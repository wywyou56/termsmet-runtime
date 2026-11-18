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
Y2 remains partially complete until a real restricted Claude session successfully
makes and receives `list_templates`; fake CLI tests do not satisfy this gate.

The boundary probe/improvement and final versioned handoff remain pending Y3–Y5.
Main task files/data belong to Sheila's S1 and are intentionally absent. No HW9
main cold-start result is claimed. No historical benchmark behavior has changed.

The service supports one template and minimal mechanical challenges, not
subjective arbitration or marketplace matching. See
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) for historical copied-file
hashes and the HW9 derivative change description. Raw runs, environments,
credentials, logs, and databases are ignored and must stay out of public commits.
