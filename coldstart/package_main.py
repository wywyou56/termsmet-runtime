"""Package and verify a reviewed, sanitized subset of HW9 main cold-start runs (Sheila S5).

``--run <raw dir> --out <evidence dir>`` copies the evidence needed to rerun the
independent checker, replaces machine paths and client session IDs, and exports
the seven business tables from the final snapshot read-only into ``state.json``.
The SQLite file, raw diagnostic logs and temporary MCP configurations are not
published. ``--verify <package root>`` rechecks published hashes and reruns the
checker in memory against every packaged run, comparing check statuses with the
published ``check.json``. Neither mode calls the service.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from . import check_run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "coldstart" / "data"
COPIED = ("manifest.json", "buyer.jsonl", "provider.jsonl", "mcp-buyer.jsonl", "mcp-provider.jsonl",
          "buyer-control.jsonl", "provider-control.jsonl", "prompt-buyer.md", "prompt-provider.md", "check.json")
EXCLUDED = ("termsmet.sqlite", "client-*.stderr.log", "server-*.stderr.log", "mcp-buyer.json",
            "mcp-provider.json", ".work/")
SESSION = re.compile(r'(\\?"session_id\\?":\s*\\?")([0-9a-f-]{36})')
PRIVATE = re.compile(r"/Users/|/home/|/private/var/|/var/folders/|sk-ant", re.IGNORECASE)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sanitize(text):
    text = text.replace(str(ROOT), "<REPOSITORY>").replace(str(Path.home()), "<HOME>")
    return SESSION.sub(lambda m: m.group(1) + "<SESSION>", text)


def package(run, out):
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    out.mkdir(parents=True, exist_ok=True)
    files, origins = {}, {}
    for name in COPIED:
        original = (run / name).read_bytes()
        published = sanitize(original.decode("utf-8")).encode("utf-8")
        if PRIVATE.search(published.decode("utf-8")):
            raise SystemExit(f"{name} still contains a private path or credential-like value")
        (out / name).write_bytes(published)
        files[name] = sha256(published)
        origins[name] = {"original_sha256": sha256(original),
                         "transformation": "none" if published == original else
                         "machine paths -> <REPOSITORY>/<HOME>; client session IDs -> <SESSION>"}
    snapshot = run / "termsmet.sqlite"
    state = {"source": "termsmet.sqlite opened read-only after the run",
             "snapshot_sha256": sha256(snapshot.read_bytes()),
             "tables": check_run.export_tables(snapshot)}
    (out / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files["state.json"] = sha256((out / "state.json").read_bytes())
    origins["state.json"] = {"transformation": "export of the seven business tables; the database is not published"}
    record = {"schema_version": 1, "run": run.name, "files": files, "origins": origins,
              "not_published": list(EXCLUDED),
              "note": "State is a recorded export plus snapshot hash, not independent inspection of an "
                      "unpublished database. Business payloads, prompts, IDs and timestamps are unchanged."}
    (out / "package.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"packaged {run.name}: {len(files)} files")


def verify(root):
    expected_delivery = json.loads((DATA / "H9_expected_delivery.json").read_text(encoding="utf-8"))
    expected_report = json.loads((DATA / "H9_expected_report.json").read_text(encoding="utf-8"))
    runs = sorted(p.parent for p in root.glob("*/package.json"))
    if not runs:
        raise SystemExit("no packaged runs found")
    summary = {}
    for run in runs:
        record = json.loads((run / "package.json").read_text(encoding="utf-8"))
        for name, digest in record["files"].items():
            data = (run / name).read_bytes()
            if sha256(data) != digest:
                raise SystemExit(f"{run.name}/{name} hash mismatch")
            if PRIVATE.search(data.decode("utf-8")):
                raise SystemExit(f"{run.name}/{name} contains a private path or credential-like value")
        published = json.loads((run / "check.json").read_text(encoding="utf-8"))
        rerun = check_run.evaluate(run, expected_delivery, expected_report)
        statuses = {k: v["status"] for k, v in rerun["checks"].items()}
        if statuses != {k: v["status"] for k, v in published["checks"].items()}:
            raise SystemExit(f"{run.name}: rerun statuses {statuses} differ from published check.json")
        if rerun["useful_result"] != published["useful_result"]:
            raise SystemExit(f"{run.name}: useful_result differs")
        summary[run.name] = {"useful_result": rerun["useful_result"], "checks": statuses,
                             "state_source": rerun.get("state_source")}
    print(json.dumps({"verified_runs": summary, "service_calls_made": 0}, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify:
        return verify(args.verify)
    if not (args.run and args.out):
        parser.error("use --run and --out, or --verify")
    package(args.run, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
