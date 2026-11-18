# TermsMet

**Shared acceptance for agent transactions.** TermsMet is an MCP service that
lets buyer and provider agents agree on versioned terms, submit structured data,
receive deterministic checks and repair feedback, and retrieve the delivery
after conditional release.

The current template converts order CSV into checked JSON records. Both agents
use the same agreement and persistent transaction state:

**Agree → Simulate funding → Submit → Check and repair → Review → Release → Retrieve**

Funding, release, and refunds are **simulated**. This runtime does not move money.

## Quick start

Use Python 3.11; the dependency file pins `mcp==2.3.0`.

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python examples/connect.py --db "$PWD/runtime/connection-check/live.sqlite"
```

The [connection example](examples/connect.py) starts buyer and provider MCP
processes, initializes both sessions, lists their tools, and calls
`list_templates`. It checks connectivity; it does not run an agent transaction.

## Connect an agent

Read [AGENT_GUIDE.md](AGENT_GUIDE.md) for tool arguments, responses, permissions,
source and delivery formats, rounding, versions, deadlines, and examples.

Configure your MCP client to launch the server from this repository's root:

```sh
TERMSMET_IDENTITY=buyer \
TERMSMET_DB_PATH=/absolute/path/to/termsmet.sqlite \
.venv/bin/python -m server.mcp_server
```

Launch a separate process with `TERMSMET_IDENTITY=provider` for the other agent.
Both processes must use the same absolute database path. Identity comes from
server configuration; no tool accepts a role argument. Stdout is reserved for MCP.

| Setting | Value |
| --- | --- |
| `TERMSMET_IDENTITY` | Required: `buyer` or `provider` |
| `TERMSMET_DB_PATH` | Required: absolute path to the shared SQLite file |
| `TERMSMET_REVIEW_SECONDS` | Default: `10`; the connection example and HW9 launcher explicitly use `2` |
| `TERMSMET_FIRST_SUBMIT_MIN` | Default: `5` minutes after funding |

The service exposes eleven tools: `list_templates`, `propose_agreement`,
`counter_agreement`, `accept_agreement`, `list_jobs`, `get_job`, `fund_job`,
`submit_delivery`, `get_result`, `challenge_result`, and `retrieve_delivery`.

**PASS is not release.** Review must close and all release conditions must hold.
Permitted tool calls advance due jobs; there is no background settlement worker.

## Verification and agent testing

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evidence/hw9/verify.py
.venv/bin/python -m coldstart.package_main --verify evidence/hw9-main
```

The offline evidence verifier checks file hashes, recorded MCP exchanges,
diagnostics, and exported state counts. It does not inspect unpublished databases
or run a new experiment.

For restricted Claude sessions, setup preflight, task inputs, execution commands,
and evidence formats, use [HW9_HANDOFF.md](HW9_HANDOFF.md). Model access is needed
for those sessions; the service, SDK connection example, and offline verifier do
not require model credentials. Keep credentials and raw runs out of Git.

## Documentation and evidence

| Document | Purpose |
| --- | --- |
| [Agent guide](AGENT_GUIDE.md) | Interface contract for connected agents |
| [HW9 handoff](HW9_HANDOFF.md) | Reproducible setup and remaining usability-test steps |
| [HW9 results](HW9_YOU_RESULTS.md) | Recorded setup checks, boundary comparison, and limitations |
| [Reviewed evidence](evidence/hw9/README.md) | Preserved setup and boundary evidence with offline verification |
| [Main cold-start evidence](evidence/hw9-main/README.md) | Fresh-agent buyer/provider runs, predefined checks, results and reproduction |
| [Source provenance](SOURCE_PROVENANCE.json) | Original service revision and subsequent runtime changes |

The boundary improvement adds machine-readable missing/received-column
diagnostics; it does not establish improved agent success. In the main HW9
cold-start test, two fresh Claude sessions given only this guide, their tools and
a goal-level task completed the transaction; the required attempt (`main-01`)
passed all predefined checks including the buyer's downstream report, and an
optional repetition passed C1–C5 but failed the report-format check
([details](evidence/hw9-main/README.md)). `hw9-docs-v0` and `hw9-v1` preserve the
baseline and technical handoff revisions.

## Current limits

- One task template: `order_extraction_v1`.
- Simulated settlement and local demo identities; no production authentication
  between independent organizations.
- Mechanical challenges only; no subjective arbitration or marketplace discovery.
- Local stdio processes and SQLite; no hosted service or background settlement.
- The restricted agent launcher requires macOS or Linux.

This repository distributes the standalone service and its current integration
tools. Historical demos and benchmarks remain in their original repositories.
