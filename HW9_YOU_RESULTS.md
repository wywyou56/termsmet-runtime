# HW9 — You Wu technical results

TermsMet is an MCP service, not an agent framework. All funding, release and
refund events are simulated. This half provides the interface, execution tools,
setup evidence and one boundary-driven diagnostic improvement. Sheila owns the
fresh main task, independent oracles/checker, main attempt and final course work.

## Revisions and existing verification

| Checkpoint | Full revision | Result |
| --- | --- | --- |
| Historical HW8 runtime/main | `7ee09295226d2a41555293f391e13a8c46020031` | Preserved |
| Y1 guide/submission discovery | `853acf6bfe734fdcff16bf2ee3c9172254393f75` | `get_job.current_submission_version`, complete guide and connection example |
| Y2 execution tools | `4b91a623c5d6f0443d5df8a302da032aec5595ea` | Real restricted preflight `preflight-y2-04` passed: eleven tools, one actual `list_templates` exchange, exit 0 |
| Y3 baseline, `hw9-docs-v0` | `c1f536295bd0184a7e1a0684fc388d59d9f245b9` | 37 tests passed; one formal generic B1 observation |
| Y4 improved service | `7d70e99801c512d5d7e4653f0cf451ed33eb4b45` | 44 tests passed; one formal structured B1 observation |

The baseline annotated tag object is
`9fe1452001a9290e7a177a1f8077f5f8d93e96a3`. No historical tag is moved. The final
handoff revision is resolved by `git rev-parse hw9-v1^{commit}` after publication;
the owner receives that full hash in the publication review and handoff message.

Observed runtime: Python 3.11.5, MCP SDK 2.3.0, Claude Code 2.1.317,
`claude-haiku-5-5`, medium effort, Parley endpoint. Python patch versions are
recorded rather than enforced as a new launcher rejection gate. Main HW9 defaults
are two-second review, five-minute first submission, 900-second wall cap and
60 attempted calls per role. Server default review remains ten seconds.

## Boundary evidence: exact request and before/after

This was a **scripted actual-MCP negative request**, not a fresh LLM attempt.
The fair guide already stated required source columns before execution. The
predefined criteria, input and probe are unchanged across the two attempts.

The buyer called `propose_agreement` once per fresh database with these values:

```json
{"template_id":"order_extraction_v1","source_csv":"order_no,client,qty,unit_price\nB901,Synthetic-A,2,$3.125\nB902,Synthetic-B,1,$120.00\n"}
```

The exact UTF-8 source, including final newline, has SHA-256
`f26d4f490e74852bd8e4e603204f0f5a99230746f6f4aae80eb14143a48b123f`.

The v0 response was:

```json
{"error":{"code":"INVALID_TERMS","message":"source_csv must contain valid, unambiguous order data"}}
```

The observed limitation was missing machine-readable information about the
required/missing and received headers. Y4 added a small `ValueError` subclass in
the existing parser and optional `BusinessError.details` propagation. Empty,
duplicate and blank-header checks still precede missing-column assessment. The
service does not parse CSV again to generate the diagnostic. Other errors keep
their existing shape. Accepted inputs, rounding, delivery checking, schema,
permissions, deadlines, repair and settlement rules are unchanged.

The v1 response was:

```json
{"error":{"code":"INVALID_TERMS","message":"Required source columns are missing","details":{"missing_columns":["Order","Units","Price"],"received_columns":["order_no","client","qty","unit_price"]}}}
```

| Separate outcome | v0 | v1 |
| --- | --- | --- |
| Execution completed | Yes, exit 0 | Yes, exit 0 |
| Unsupported input correctly rejected | `INVALID_TERMS` | `INVALID_TERMS` |
| Zero business state changes verified | All seven tables empty; no settlement events | Same |
| Diagnostic richness observed | Generic | Structured missing/received lists |

Input bytes/hash, request arguments, full inventory, probe/criteria hashes,
Python/SDK and client settings match. Each run has one matched request/response.
Review was two seconds, first submission five minutes, call cap one and startup
15 seconds, with a 45-second worker cap. All 14 original v0 files and the baseline
tag were verified unchanged after Y4. Y5 reviews copies and retains the originals.

The commands actually used for the formal attempts were:

```sh
.venv/bin/python -m coldstart.boundary_probe --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v0
.venv/bin/python -m coldstart.boundary_probe --source-csv coldstart/data/B1.csv --out runtime/hw9/b1-v1
```

Do not repeat those directories. Historical reproduction uses the appropriate
revision in a separate checkout and a new output path; Y5 does not rerun either
formal attempt.

## Regressions and reconstruction

Actual Y4 commands: `.venv/bin/python -m unittest discover -s tests -v` passed
44 tests in 62.745 seconds; `git diff --check HEAD^ HEAD` passed. The real MCP
transaction used an extra-column source and hand-computed unit-first rounding,
bounded real-time polling accepting an already `RELEASED` state, actual PASS,
release and retrieval, and exactly one simulated release. Retrieval denial was
checked before acceptance, not during a timing-sensitive review race.

Y5 adds only the offline evidence verifier and its focused integrity tests, plus
documentation and reviewed exports. The candidate independent local clone will
install fresh dependencies, run the full tests, verify this package, and make one
real restricted preflight. Actual candidate/final revisions and commands are
recorded in `evidence/hw9/reconstruction.json` once this check is complete. The
second reconstruction is the anonymous public clone after publication approval;
it performs offline verification of the final commit. No third checkout is
required. No main task or old benchmark is run.

## Evidence, interpretation and remaining acceptance

Run `python3.11 evidence/hw9/verify.py` without model credentials. The package
manifest records original and published hashes and sanitization transformations.
See [package documentation](evidence/hw9/README.md) and
[the full handoff](HW9_HANDOFF.md).

Raw SQLite files and logs remain out of Git. State exports and snapshot hashes
are recorded evidence, not independent inspection of an unpublished database.
These self-run setup checks establish interface access, and the B1 comparison
establishes richer machine-readable feedback. Neither establishes independent
adoption, improved agent success, a meaningful main cold-start result, or the
buyer's downstream report. Those require Sheila's actual S1–S3 work.

Publication requires owner approval of the final commit/refs and reviewed files.
Sheila's accepted write access to this runtime repository remains unverified:
the integration returns 403, so permission on another fork or a public clone
cannot substitute. If unresolved, the status is **Technical handoff ready;
collaborator access pending.** Y5 is not fully complete until publication,
post-publication offline reconstruction and accepted write access are confirmed.
