# B1 unsupported-source boundary — predefined criteria

This is a **scripted actual-MCP boundary test**, not a cold-start LLM test.
These criteria and the probe are committed before the formal baseline request.
Sheila's main-task criteria belong in `coldstart/criteria.md` during S1.

## Fixed request and isolation

Use the original UTF-8 bytes of `coldstart/data/B1.csv`, including its final LF,
as the decoded `source_csv` argument. Do not rename headers or repair the source.
The buyer makes exactly one business tool request:

```text
propose_agreement(template_id="order_extraction_v1", source_csv=<original B1 CSV>)
```

Initialize through the official MCP SDK, verify the full eleven-tool inventory,
and use a fresh database with two-second review/five-minute first submission
configuration. No model client, credentials, funding, submissions, extra service
observations, or settlement calls are needed. Verify state using a read-only
SQLite snapshot after processes stop.

## Four separate outcomes

1. **Execution completed:** initialization, inventory verification, one matched
   request/response, process cleanup, consistent backup, and read-only inspection
   completed with preserved evidence. A generic business error is a completed
   execution, not a transport or setup failure.
2. **Unsupported input correctly rejected:** the actual business response has
   `error.code == "INVALID_TERMS"`. The unsupported input must remain rejected
   after the later improvement.
3. **Zero state changes verified:** the fresh database has no job or related
   rows, and no simulated funding, release, or refund events. Missing/inaccessible
   state is unknown, never evidence for zero changes.
4. **Diagnostic richness observed:** assess the actual missing/received column
   details independently of execution and rejection. Required columns are
   `Order`, `Units`, `Price`; B1 receives `order_no`, `client`, `qty`, `unit_price`.
   The expected baseline has a generic message without those structured details.
   That limitation does not fail outcomes 1–3.

The probe labels diagnostics `generic` (no missing/received-column fields),
`partial_structured` (some fields present but not both correct), `structured`
(both lists exactly correct), or `no_business_error`. Its expected/observed
fields distinguish assessment criteria from information supplied by the server.
The original message is retained for human assessment too.

Exit 0 requires completed execution, correct rejection, and verified zero state;
it does not require rich diagnostics. Exit 1 records an execution or substantive
check failure; exit 2 records invalid input/output setup; exit 130 records
interruption. Report all four outcomes even when exit 0.

## Freeze and comparison

Commit the fair guide, baseline code, probe, data, tests and these criteria; create
the local `hw9-docs-v0` tag without moving an existing tag. Run once from that
exact clean revision:

```sh
.venv/bin/python -m coldstart.boundary_probe \
  --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v0
```

Preserve the full revision, hashes, input, response, inventory, protocol records,
state counts, cleanup and snapshot status. Refuse nonempty output directories;
never overwrite an unsuccessful attempt or move the baseline tag to hide it.
Raw evidence remains ignored and unpublished until reviewed publication in Y5.

If the actual baseline already provides the complete structured diagnostic,
stop and report that the planned improvement is already present. Do not invent
before/after evidence or weaken documentation to manufacture a failure.

Y4 uses the same invocation, source and client configuration with a fresh
`runtime/hw9/b1-v1` output directory. Success there means richer verified
machine-readable diagnostics with unchanged rejection/no-state-change behavior.
This boundary experiment alone does not establish improved agent success.
