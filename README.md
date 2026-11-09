# TermsMet minimal runtime

TermsMet is a local MCP stdio service for a versioned order extraction agreement, deterministic delivery checks, repair and conditional delivery. Funding, release and refunds are simulated; this is not a payment service. Identities are local demo identities, not production authentication.

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

The default review window is 10 seconds. A client may explicitly set `TERMSMET_REVIEW_SECONDS=2` for HW8; the first submission default is five minutes (`TERMSMET_FIRST_SUBMIT_MIN`). The server supports one template and minimal mechanical challenges, not subjective arbitration. See SOURCE_PROVENANCE.json for the source revision and copied file hashes.
