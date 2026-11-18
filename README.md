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
`get_job` (0 before submission). A focused actual-MCP check covers version
discovery before and after a failed submission and passing repair. The reusable
restricted launcher/preflight, boundary probe and diagnostic improvement, and
versioned technical handoff are still pending Y2–Y5. No HW9 main cold-start result
is claimed. No historical benchmark behavior has been changed.

The service supports one template and minimal mechanical challenges, not
subjective arbitration or marketplace matching. See
[SOURCE_PROVENANCE.json](SOURCE_PROVENANCE.json) for historical copied-file
hashes and the HW9 derivative change description. Raw runs, environments,
credentials, logs, and databases are ignored and must stay out of public commits.
