# Reviewed HW9 setup and boundary evidence

This package records self-run setup checks and the scripted MCP B1 boundary
comparison. It is not the main cold-start experiment or evidence of adoption.

Run from a clone of the handoff revision, without credentials or a database:

```sh
python3.11 evidence/hw9/verify.py
```

The verifier only checks hashes, matched requests/responses, diagnostics,
exported counts and the actual preflight exchange. It never starts an agent,
server, experiment, or database connection, and it does not implement C1–C7.

- `b1-v0/` preserves the generic `INVALID_TERMS` observation at
  `c1f536295bd0184a7e1a0684fc388d59d9f245b9` (`hw9-docs-v0`).
- `b1-v1/` records the structured missing/received-column response at
  `7d70e99801c512d5d7e4653f0cf451ed33eb4b45`.
- Each has the exact source CSV, MCP traffic with original IDs/timestamps,
  control events, a reviewed probe report and a state export.
- `comparison.json` records the original comparison. Its `report_sha256` fields
  identify original private reports, not their path-sanitized published copies.
- `attempts.json` discloses the earlier blocked setup attempts. Successful setup
  evidence includes actual MCP traffic, advertised inventory, and complete final
  Claude output; it is not inferred from an agent's claim.
- The independent Y5 reconstruction report and preflight are added after the
  fresh-clone verification. The reconstruction candidate revision is recorded
  explicitly; final documentation/evidence updates do not change runtime code.

`manifest.json` lists each published file hash and its source/provenance hash.
`origins` documents transformations. Source labels are portable evidence labels,
not requirements to have another person's local run directories. The attempt
index is derived from the listed source reports; each original report hash is
included. The manifest is anchored by the Git commit, not included in its own
hash list.

Business request/response payloads, source bytes, protocol IDs and timestamps
remain unchanged. Personal machine paths and session/account metadata are
replaced in affected reports and JSON-encoded CLI event lines. Such containers
are reserialized and explicitly labeled as derived copies; original raw lines
remain preserved locally. No credential value, local authentication file,
temporary MCP configuration, private benchmark module, or raw diagnostic log
belongs in this package.

**State counts plus snapshot hashes are recorded evidence.** The generated
SQLite binaries are not committed. Counts were exported by opening reviewed
copies of the existing final consistent snapshots read-only; originals and
their WAL/SHM files remain untouched. Offline verification checks the exported
evidence and its internal consistency, not an unpublished database. The B1
snapshots contained zero rows in all seven business tables and no funding,
release or refund events.

Both B1 executions completed and correctly rejected the input. The observed
improvement is richer machine-readable feedback. No improved agent-success
rate, independent adoption, or main-task downstream-use result is established.
