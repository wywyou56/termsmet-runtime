# HW9 main cold-start criteria (Sheila S1, frozen before execution)

These criteria govern the fresh-agent main attempt only. They are separate from
the scripted unsupported-input criteria in `boundary_criteria.md`. They were
committed before any main run; the commit timestamp is the evidence that they
precede execution. They must not be edited after the first formal attempt
starts; any later change would be a new, disclosed revision.

## What is being tested

Can two **fresh** LLM client sessions, given only the TermsMet guide, their
authorized TermsMet MCP tools and a goal-level task, complete a real buyer ↔
provider transaction on the actual service, and can the buyer **use the
retrieved result** for a downstream purchasing summary?

This is a **self-run** test with fresh sessions: the team built the service and
launched the clients. It is not independent adoption by another builder.

## What each client receives

| | Buyer | Provider |
|---|---|---|
| Task | `coldstart/tasks/buyer.md` (goal + report fields) | `coldstart/tasks/provider.md` (goal only) |
| Documentation | `AGENT_GUIDE.md`, verbatim | `AGENT_GUIDE.md`, verbatim |
| Source data | `coldstart/data/H9.csv`, as a JSON string | none (must discover it through the service) |
| Tools | the eleven TermsMet MCP tools for the `buyer` identity | the same eleven tools for the `provider` identity |

Neither client receives a call sequence, agreement version, repair window,
prepared draft, forced FAIL/repair, expected delivery, expected report, file,
shell or database access, or any message from the other client or a person.
No mid-run coaching, message relay or manual service call is permitted.

## Frozen run configuration

```sh
.venv/bin/python -m coldstart.launch \
  --buyer-task coldstart/tasks/buyer.md \
  --provider-task coldstart/tasks/provider.md \
  --source-csv coldstart/data/H9.csv --guide AGENT_GUIDE.md \
  --out runtime/hw9/main-01 \
  --review-seconds 2 --first-submit-minutes 5 \
  --wall-seconds 900 --tool-limit 60 \
  --model claude-haiku-5-5 --effort medium \
  --claude-bin <path to Claude Code 2.1.317>
```

- Model `claude-haiku-5-5`, effort `medium`, Claude Code `2.1.317` (the version
  You's preflights used; the local default `claude` on Sheila's machine is
  older, so `--claude-bin` selects the 2.1.317 executable). The model must pass
  `coldstart.preflight` first. No model substitution during or between formal
  attempts without a recorded, disclosed reason.
- Manual help: `none reported` unless something actually happens, in which
  case it is disclosed verbatim with `--manual-help`.
- Attempts are numbered `main-01`, `main-02`, … and never overwritten. If a
  setup defect prevents meaningful access, the attempt is kept, the fix is
  recorded, and a new numbered attempt is run. A project/interface failure is a
  valid result and is not rerun merely to obtain a pass.

## Independent oracles

`coldstart/data/H9_expected_delivery.json` and `H9_expected_report.json` were
hand-calculated (`H9_calculation.md`) and cross-checked by
`tests/test_h9_oracle.py` without importing the service. Only the observed job
ID is substituted into the expected report. The buyer already has the source,
so report accuracy and timing are evidence of checkable downstream behaviour,
not proof of the model's internal reasoning.

## Predefined checks

The checker (`coldstart/check_run.py`) reads only saved evidence: the run
manifest, client stdout JSONL, MCP JSONL, proxy control JSONL and the
`termsmet.sqlite` snapshot opened read-only. It never calls the service.

**Evaluated job.** The job named by the buyer's final report if that job exists
in the snapshot; otherwise the only job in the snapshot. If neither identifies
exactly one job, C1–C6 are `incomplete`.

Each check is `passed`, `failed` or `incomplete` (missing, malformed or
contradictory evidence). Nothing is inferred from a process exit code or a
client's own claim.

| ID | Passes only if | Evidence |
|---|---|---|
| C1 | The job's current agreement version V has acceptance rows for both `buyer` and `provider`, and each role's MCP log contains a non-error `accept_agreement` response for that job and V. V = 1 is acceptable. | snapshot `jobs`, `acceptances`; MCP logs |
| C2 | Exactly one `SIMULATED_FUNDING` event exists for the job and it is not later than any submission of the job. | snapshot `settlement_events`, `submissions` |
| C3 | The job's `current_submission_version` S > 0; submission S is by `provider` on agreement V with a persisted `PASS`; and the provider's MCP log contains a `submit_delivery` request for the job whose response reports submission S with verdict `PASS`. | snapshot; provider MCP log |
| C4 | Job status `RELEASED`; exactly one `SIMULATED_RELEASE`, zero `SIMULATED_REFUND`; release time ≥ the stored review deadline. | snapshot |
| C5 | The buyer's MCP log contains a successful (non-error) `retrieve_delivery` response for the job whose `delivery` strictly equals the expected delivery: a list of objects with exactly `order_id` (string), `quantity`, `unit_price_cents`, `total_cents` (integers; booleans are not integers), no missing, duplicate or unexpected order IDs, compared independent of row order. | buyer MCP log; expected delivery |
| C6 | The buyer's final result text is exactly one JSON object (optionally wrapped in one Markdown JSON code fence) with exactly the five report fields, correct types, `job_id` equal to the evaluated job, and every value equal to the expected report (approval orders compared by order ID, independent of order); and the final result line was received after the first successful retrieval response. | buyer stdout JSONL; expected report; MCP timestamps |
| C7 | Manual help is disclosed in the manifest; each role made at most 60 tool attempts with zero blocked calls and no budget-exhaustion event; the client execution span (launch start to last client exit) is at most 900 seconds with no wall-cap failure. | manifest; control JSONL |

**Useful main result = C1–C6 all `passed`.** C7 and the launcher's
`execution_status` are reported separately.

## Friction recorded (does not change pass/fail)

- Business errors per role, by tool and error code, with the service message.
- Tool attempts and forwarded/blocked calls per role.
- Number of jobs created, agreement versions, submissions, repairs (submissions
  after the first conclusive FAIL), UNKNOWN verdicts, challenges.
- Each client's exit code, final result text and elapsed time; usage/cost when
  available (missing is `N/A`, not zero).
- Short exact excerpts of client text that show a misunderstanding, chosen by
  hand during interpretation.

## Failure classification (used in interpretation)

| Class | Examples |
|---|---|
| Project / interface | Guide omits or misstates needed information; an error is not actionable; unsupported input; service defect; lazy settlement misunderstood |
| Test setup | Authentication or endpoint failure, model unavailable, MCP configuration or launcher defect, call/time cap too low, local environment problem |

An attempt can have causes in both classes; each is supported with evidence.
