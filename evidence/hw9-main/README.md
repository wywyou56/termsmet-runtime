# HW9 main cold-start evidence (Sheila S3/S5)

Self-run test with **fresh** Claude Code sessions. Each client received only
`AGENT_GUIDE.md` (verbatim), its eleven TermsMet MCP tools and a goal-level task
(`coldstart/tasks/`); the buyer also received `coldstart/data/H9.csv`. No call
sequence, agreement version, draft, expected answer, file/shell/database access,
message relay or mid-run coaching. Manual help: **none**. Criteria were frozen
and published in `coldstart/criteria.md` (commit `8842ebc`) before any run.

| Setting | Value |
|---|---|
| Runtime revision (clean) | `2250e3a875111261a184f98adf886a0afa4a006a` |
| Client | Claude Code 2.1.317, `--bare`, strict MCP config, built-in tools disabled |
| Model / effort | `claude-haiku-5-5` / medium (MIT Parley endpoint) |
| Limits | 2 s review, 5 min first submission, 900 s wall cap, 60 tool calls per role |
| Preflight | `preflight-01` passed at the same revision (one real `list_templates` exchange) |
| Checker | `coldstart/check_run.py` at `2250e3a` (statuses reproduced by later version via `--verify`) |

## Results

| Check | main-01 (required attempt) | main-02 (optional repetition) |
|---|---|---|
| C1 same agreement version accepted by both | passed (v1) | passed (v1) |
| C2 simulated funding before submission | passed | passed |
| C3 provider submission with server PASS | passed (submission 1) | passed (submission 1) |
| C4 one release after review deadline, no refund | passed | passed |
| C5 retrieved delivery = independent expectation | passed | passed |
| C6 final report = expected, after retrieval | **passed** | **failed** — prose before a fenced JSON object |
| C7 no help, ≤60 calls, ≤900 s | passed | passed |
| **Useful result (C1–C6)** | **yes** | **no** |
| Tool calls buyer / provider | 15 / 11 | 10 / 10 |
| Business errors | 0 | 0 |
| Run time / client cost | 91.8 s / $0.0101 | 61.8 s / $0.0083 |

### main-01 interaction chain (seconds from launch)

| t | Role | Request → response |
|---:|---|---|
| 5.1 | provider | `list_jobs` → `[]` (buyer not ready; provider keeps polling) |
| 14.1 | buyer | `propose_agreement(order_extraction_v1, <H9 CSV>)` → job, v1, `PROPOSED` |
| 17.2 | provider | `get_job` → reads the agreed source CSV itself |
| 19.3 / 24.1 | buyer / provider | `accept_agreement(v1)` → `ACCEPTED` (no counter needed) |
| 30.9 | buyer | `fund_job` → `FUNDED`, `simulated: true` |
| 39.7 | provider | `submit_delivery(8 records)` → submission 1, **PASS** |
| 48.4 | provider | `get_result(1)` → first call after the review deadline records the release |
| 55.2 | buyer | `get_result(1)` → PASS, settlement `RELEASED`; buyer checks before relying |
| 60.8 | buyer | `retrieve_delivery` → the 8 released records (equal to the oracle) |
| 91.1 | buyer | final JSON report: 8 orders, 48 units, $610.76, approvals K303/K304/K307 |

The provider derived every value itself, including the half-cent rounding
(K302 $2.675 → 268, K305 $0.995 → 100). The buyer's visible reasoning after
retrieval says it was "checking each delivery line's rounding against the source
values" before writing the report.

### Interpretation

- **No project/interface or test-setup failure** occurred in either attempt.
  Lazy settlement worked as documented: neither client waited forever; a later
  ordinary call recorded the release.
- **main-02's C6 failure is a client output-format failure**: the buyer wrote one
  sentence of prose and then a fenced JSON object, whereas the task required
  exactly one JSON object. Under the frozen rule this fails. *Sensitivity note,
  not preregistered:* the fenced object alone matches every expected field.
- **Limits of the evidence.** The buyer also had the source CSV and (in
  main-01) computed totals itself before retrieval, so a correct report shows
  checkable downstream behaviour and timing (report after retrieval), not that
  the numbers could only have come from the retrieved records. The provider's
  first submission passed, so this test did not exercise FAIL → repair (that
  path is covered by HW7). Two runs, one model family, self-run.
- Friction observed: provider sent three identical `list_jobs` calls within
  0.1 s; buyer made redundant `get_result` calls after release. Neither caused
  an error or approached the call cap.

## Reproduce

Offline (no key, no database):

```sh
git clone --branch hw9 https://github.com/wywyou56/termsmet-runtime.git
cd termsmet-runtime
uv venv --python 3.11.5 --seed .venv   # or: python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m coldstart.package_main --verify evidence/hw9-main
.venv/bin/python -m coldstart.check_run --run evidence/hw9-main/main-01 \
  --expected-delivery coldstart/data/H9_expected_delivery.json \
  --expected-report coldstart/data/H9_expected_report.json --output /tmp/main-01-recheck.json
```

Live (needs your own model key in `ANTHROPIC_API_KEY`; a new run gets new job
IDs, timestamps and possibly different agent behaviour):

```sh
.venv/bin/python -m coldstart.preflight --out runtime/hw9/preflight-XX --model claude-haiku-5-5 --effort medium
.venv/bin/python -m coldstart.launch --buyer-task coldstart/tasks/buyer.md \
  --provider-task coldstart/tasks/provider.md --source-csv coldstart/data/H9.csv \
  --guide AGENT_GUIDE.md --out runtime/hw9/main-XX --review-seconds 2 \
  --first-submit-minutes 5 --wall-seconds 900 --tool-limit 60 \
  --model claude-haiku-5-5 --effort medium
.venv/bin/python -m coldstart.check_run --run runtime/hw9/main-XX \
  --expected-delivery coldstart/data/H9_expected_delivery.json \
  --expected-report coldstart/data/H9_expected_report.json
```

## Package contents

Each run directory holds the manifest, both clients' complete stdout (stream-JSON
lines), both MCP request/response logs with original IDs and timestamps, proxy
control events, the exact rendered prompts, the checker's `check.json`, a
read-only export of the seven business tables (`state.json`, with the snapshot
SHA-256) and `package.json` (published/original hashes and transformations).
Machine paths are replaced by `<REPOSITORY>`/`<HOME>` and client session IDs by
`<SESSION>`; payloads, prompts, IDs and timestamps are otherwise unchanged. The
SQLite file, raw stderr logs and temporary MCP configs are not published, so the
state export is recorded evidence rather than independent inspection.
