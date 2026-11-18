"""Launch two restricted fresh Claude sessions and preserve actual execution."""

import argparse
import asyncio
import importlib.metadata
import json
import os
import re
import shutil
import signal
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from ._support import (
    FLAGS, ROOT, client_environment, command_output,
    contains_credential, digest, inventory, positive, prepare_output, proxy_parameters,
    proxy_environment, read_text, records, redact, signal_group, snapshot, tool_limit, with_signals, write_json,
)


def render_tasks(buyer, provider, guide, source):
    result = {}
    for role, template in (("buyer", buyer), ("provider", provider)):
        if template.count("{{AGENT_GUIDE}}") != 1:
            raise ValueError(f"{role} task must contain exactly one AGENT_GUIDE placeholder")
        if template.count("{{SOURCE_CSV_JSON}}") != (1 if role == "buyer" else 0):
            raise ValueError(f"{role} task has an invalid SOURCE_CSV_JSON placeholder count")
        substitutions = {"{{AGENT_GUIDE}}": guide,
                         "{{SOURCE_CSV_JSON}}": json.dumps(source, ensure_ascii=False)}
        remaining = template.replace("{{AGENT_GUIDE}}", "").replace("{{SOURCE_CSV_JSON}}", "")
        if "{{" in remaining:
            raise ValueError(f"{role} task contains an unresolved placeholder")
        # Single-pass substitution never interprets braces in source/guide content.
        prompt = re.sub(r"\{\{.*?\}\}", lambda match: substitutions[match[0]], template, flags=re.DOTALL)
        if role == "buyer":
            prompt += "\nThe source JSON string above represents decoded CSV text; preserve its newlines and final newline.\n"
        result[role] = prompt
    return result


def initial_manifest(args, kind):
    return {
        "schema_version": 1, "kind": kind, "started_at": time.time(), "finished_at": None,
        "execution_status": "starting", "transaction_status": "not_evaluated",
        "runtime_commit": None, "working_tree_dirty": None,
        "python": sys.version, "mcp_version": importlib.metadata.version("mcp"),
        "model": args.model, "effort": args.effort,
        "review_seconds": args.review_seconds, "first_submit_minutes": args.first_submit_minutes,
        "wall_seconds": args.wall_seconds, "tool_limit": args.tool_limit,
        "startup_seconds": args.startup_seconds,
        "manual_help": args.manual_help, "agents": {}, "failures": [],
        "snapshot": {"status": "unavailable", "reason": "no server database observed"},
        "cleanup": {"status": "not_started"},
    }


async def stop_owned(processes, out, roles):
    groups = {process.pid for process in processes.values()}
    errors = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        # Re-read after TERM to catch a proxy registering during client shutdown.
        for role in roles:
            try:
                groups.update(row["pgid"] for row in records(out / f"{role}-control.jsonl")
                              if row["event"] == "proxy_started")
            except (OSError, ValueError, KeyError) as exc:
                errors.append(redact(str(exc)))
        for group in groups:
            try:
                signal_group(group, sig)
            except (OSError, ValueError) as exc:
                errors.append(redact(str(exc)))
        # Process.wait alone cannot confirm that grandchildren have stopped.
        deadline = time.monotonic() + 2
        while groups:
            try:
                running = set()
                for group in groups:
                    try:
                        os.killpg(group, 0)
                        running.add(group)
                    except ProcessLookupError:
                        pass
            except OSError as exc:
                errors.append("could not confirm descendant shutdown: " + redact(str(exc)))
                break
            if not running:
                break
            if time.monotonic() >= deadline:
                if sig == signal.SIGKILL:
                    errors.append("trial descendants remain after KILL")
                break
            await asyncio.sleep(0.05)
        if processes:
            try:
                await asyncio.wait_for(asyncio.gather(*(p.wait() for p in processes.values())), 2)
            except asyncio.TimeoutError:
                if sig == signal.SIGKILL:
                    errors.append("client failed to exit after KILL")
    return {"status": "failed" if errors else "completed", "process_groups": sorted(groups), "errors": errors}


async def execute(args, out, prompts, manifest):
    """Shared bounded client supervision; preflight supplies one setup-only prompt."""
    started = time.monotonic()
    processes, collectors, inventory_deadlines = {}, [], {}
    roles = list(prompts)
    work = out / ".work"
    work.mkdir()

    def save():
        write_json(out / "manifest.json", redact(manifest))

    def fail(reason, **details):
        manifest["failures"].append({"reason": reason, **redact(details)})

    async def stdout(role, process):
        state = manifest["agents"][role]
        try:
            with (out / f"{role}.jsonl").open("a", encoding="utf-8") as output:
                while raw := await process.stdout.readline():
                    line = raw.decode("utf-8")
                    if line.endswith("\n"):
                        line = line[:-1]
                    received = time.time()
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if contains_credential(line) or contains_credential(event):
                        fail("credential_output_blocked", role=role)
                        return
                    output.write(json.dumps({"received_at": received, "line": line}, ensure_ascii=False) + "\n")
                    output.flush()
                    if not isinstance(event, dict):
                        continue
                    if event.get("type") == "system" and event.get("subtype") == "init":
                        if state["inventory_verified"]:
                            fail("duplicate_inventory", role=role)
                        elif not inventory(event.get("tools"), "mcp__termsmet__"):
                            fail("tool_isolation_failure", role=role)
                        elif event.get("model") != args.model:
                            fail("model_mismatch", role=role, observed=event.get("model"))
                        else:
                            state.update(inventory_verified=True, inventory_received_at=received,
                                         advertised_tools=event["tools"], observed_model=event["model"])
                            (out / f".{role}-inventory-ok").touch()
                    if event.get("type") == "result":
                        if state.get("result_received_at") is not None:
                            fail("duplicate_final_output", role=role)
                        state.update(result_received_at=received, result_is_error=event.get("is_error", True))
                        for key in ("usage", "modelUsage", "total_cost_usd", "subtype"):
                            if key in event:
                                state[key] = event[key]
                        if event.get("is_error", True):
                            fail("client_result_error", role=role)
                state["stdout_complete"] = True
        except (OSError, ValueError) as exc:
            fail("logging_failure", role=role, detail=str(exc))

    async def stderr(role, process):
        try:
            with (out / f"client-{role}.stderr.log").open("w", encoding="utf-8") as output:
                while raw := await process.stderr.readline():
                    line = raw.decode("utf-8", errors="replace")
                    try:
                        decoded = json.loads(line)
                        if contains_credential(decoded):
                            line = json.dumps(redact(decoded), ensure_ascii=False) + "\n"
                    except ValueError:
                        pass
                    output.write(redact(line))
                    output.flush()
        except (OSError, ValueError) as exc:
            fail("logging_failure", role=role, detail=str(exc))

    def control_status():
        for role in roles:
            state = manifest["agents"][role]
            rows = records(out / f"{role}-control.jsonl")
            state["tool_attempts"] = sum(row["event"] == "tool_attempt" for row in rows)
            state["forwarded_calls"] = sum(row["event"] == "tool_forwarded" for row in rows)
            state["blocked_calls"] = sum(row["event"] == "tool_budget_exhausted" for row in rows)
            for name in ("tool_budget_exhausted", "proxy_failure", "cleanup_failure"):
                if any(row["event"] == name for row in rows) and not any(
                    item["reason"] == name and item.get("role") == role for item in manifest["failures"]
                ):
                    fail(name, role=role)

    try:
        for role, prompt in prompts.items():
            manifest["agents"][role] = {
                "inventory_verified": False, "tool_attempts": 0, "forwarded_calls": 0,
                "blocked_calls": 0, "usage": "N/A", "total_cost_usd": "N/A",
                "stdout_complete": False, "prompt_sha256": digest(prompt.encode("utf-8")),
            }
            for filename in (f"{role}.jsonl", f"mcp-{role}.jsonl", f"{role}-control.jsonl"):
                (out / filename).touch()
            (out / f"prompt-{role}.md").write_bytes(prompt.encode("utf-8"))
        save()

        def metadata(command, cwd):
            remaining = args.wall_seconds - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("wall cap reached during startup")
            return command_output(command, cwd, timeout=min(5, remaining))

        manifest["runtime_commit"] = metadata(["git", "rev-parse", "HEAD"], ROOT)
        manifest["working_tree_dirty"] = bool(metadata(["git", "status", "--porcelain"], ROOT))
        executable = shutil.which(args.claude_bin)
        if not executable:
            raise ValueError("Claude executable not found")
        manifest["claude_version"] = metadata([executable, "--version"], work)
        help_text = metadata([executable, "--help"], work)
        if not all(flag in help_text for flag in FLAGS):
            raise ValueError("installed Claude CLI lacks required isolation flags")
        manifest["claude_executable"] = executable
        endpoint = client_environment()["ANTHROPIC_BASE_URL"]
        parsed = urlsplit(endpoint)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("model endpoint must be an HTTP(S) URL without credentials, query or fragment")
        manifest["provider_base_url"] = endpoint
        if not os.environ.get("ANTHROPIC_API_KEY"):
            manifest["execution_status"] = "blocked_missing_credential"
            return 2

        for role, prompt in prompts.items():
            cwd = work / role
            cwd.mkdir()
            config = out / f"mcp-{role}.json"
            write_json(config, {"mcpServers": {"termsmet": {
                "command": str(Path(args.python).absolute()),
                "args": proxy_parameters(args, out, role), "env": proxy_environment(),
            }}})
            command = [executable, "-p", "--model", args.model, "--effort", args.effort,
                       "--mcp-config", str(config), "--strict-mcp-config", "--bare",
                       "--setting-sources", "", "--no-chrome", "--disable-slash-commands",
                       "--no-session-persistence", "--tools", "", "--allowedTools", "mcp__termsmet",
                       "--permission-mode", "dontAsk", "--output-format", "stream-json", "--verbose"]
            state = manifest["agents"][role]
            state.update(command=command, started_at=time.time())
            process = await asyncio.wait_for(asyncio.create_subprocess_exec(
                *command, cwd=cwd, env=client_environment(), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, limit=8 * 1024 * 1024,
            ), min(args.startup_seconds, max(0.01, args.wall_seconds - (time.monotonic() - started))))
            processes[role] = process
            inventory_deadlines[role] = time.monotonic() + args.startup_seconds
            state["pid"] = process.pid
            collectors.extend([asyncio.create_task(stdout(role, process)), asyncio.create_task(stderr(role, process))])
            process.stdin.write(prompt.encode("utf-8"))
            await asyncio.wait_for(process.stdin.drain(), min(args.startup_seconds, max(0.01, args.wall_seconds - (time.monotonic() - started))))
            process.stdin.close()
        manifest["execution_status"] = "running"
        save()
        while True:
            control_status()
            for role, process in processes.items():
                state = manifest["agents"][role]
                if process.returncode is not None:
                    state.setdefault("exit_observed_at", time.time())
                    if process.returncode:
                        fail("process_failure", role=role, exit_code=process.returncode)
                    if not state["inventory_verified"]:
                        fail("missing_inventory", role=role)
                    if state["stdout_complete"] and "result_received_at" not in state:
                        fail("missing_final_output", role=role)
                elif not state["inventory_verified"] and time.monotonic() >= inventory_deadlines[role]:
                    fail("inventory_timeout", role=role)
            if manifest["failures"]:
                manifest["execution_status"] = manifest["failures"][0]["reason"]
                break
            if all(p.returncode is not None for p in processes.values()) and all(
                manifest["agents"][role]["stdout_complete"] for role in roles
            ):
                manifest["execution_status"] = "completed"
                break
            if time.monotonic() - started >= args.wall_seconds:
                manifest["execution_status"] = "wall_timeout"
                break
            await asyncio.sleep(0.02)
    except asyncio.CancelledError:
        manifest["execution_status"] = "interrupted"
    except Exception as exc:
        manifest.update(execution_status="startup_failure", reason=redact(str(exc)), exception_type=type(exc).__name__)
    finally:
        (out / ".stop-requested").touch()
        manifest["cleanup"] = await stop_owned(processes, out, roles)
        if collectors:
            try:
                await asyncio.wait_for(asyncio.gather(*collectors), 2)
            except Exception as exc:
                fail("logging_failure", detail=str(exc))
        try:
            control_status()
            for role in roles:
                for name in (f"{role}.jsonl", f"mcp-{role}.jsonl", f"{role}-control.jsonl"):
                    data = (out / name).read_bytes()
                    if data and not data.endswith(b"\n"):
                        fail("truncated_evidence", file=name)
        except (OSError, ValueError, KeyError) as exc:
            fail("control_log_failure", detail=str(exc))
        for role, process in processes.items():
            manifest["agents"][role]["exit_code"] = process.returncode
            manifest["agents"][role].setdefault("exit_observed_at", time.time())
        if manifest["cleanup"]["status"] == "completed":
            manifest["snapshot"] = snapshot(work / "live.sqlite", out / "termsmet.sqlite")
            if manifest["snapshot"]["status"] != "failed":
                try:
                    shutil.rmtree(work)
                except OSError as exc:
                    manifest["cleanup"] = {"status": "failed", "errors": [redact(str(exc))]}
        else:
            manifest["snapshot"] = {"status": "unavailable", "reason": "process cleanup was not confirmed; live state retained"}
        if manifest["execution_status"] == "completed":
            if manifest["failures"]:
                manifest["execution_status"] = manifest["failures"][0]["reason"]
            elif manifest["cleanup"]["status"] != "completed":
                manifest["execution_status"] = "cleanup_failure"
            elif manifest["snapshot"]["status"] == "failed":
                manifest["execution_status"] = "backup_failure"
        manifest["finished_at"] = time.time()
        manifest["elapsed_seconds"] = time.monotonic() - started
        save()
    return 0 if manifest["execution_status"] == "completed" else (130 if manifest["execution_status"] == "interrupted" else 1)


def add_options(parser):
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--review-seconds", type=positive, default=2)
    parser.add_argument("--first-submit-minutes", type=positive, default=5)
    parser.add_argument("--wall-seconds", type=positive, default=900)
    parser.add_argument("--tool-limit", type=tool_limit, default=60)
    parser.add_argument("--startup-seconds", type=positive, default=15)
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    parser.add_argument("--claude-bin", default="claude")
    parser.add_argument("--manual-help", default="none reported")
    parser.set_defaults(python=sys.executable)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_options(parser)
    for name in ("buyer-task", "provider-task", "source-csv", "guide"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        out = prepare_output(args.out)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc) + "\n")
    manifest = initial_manifest(args, "launch")
    try:
        contents = {name: read_text(getattr(args, name)) for name in ("buyer_task", "provider_task", "source_csv", "guide")}
        manifest["input_sha256"] = {name: digest(text.encode("utf-8")) for name, text in contents.items()}
        prompts = render_tasks(contents["buyer_task"], contents["provider_task"], contents["guide"], contents["source_csv"])
        if contains_credential(prompts):
            raise ValueError("rendered prompt contains the invoking model credential")
    except (OSError, ValueError) as exc:
        manifest.update(execution_status="startup_failure", reason=redact(str(exc)), finished_at=time.time())
        write_json(out / "manifest.json", redact(manifest))
        return 2
    return asyncio.run(with_signals(execute(args, out, prompts, manifest)))


if __name__ == "__main__":
    raise SystemExit(main())
