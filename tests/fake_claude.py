"""Synthetic CLI process fixture. This is never live-Claude usability evidence."""

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from coldstart._support import FLAGS, TOOLS


def emit(value):
    print(json.dumps(value), flush=True)


def init(model, extra=False):
    emit({"type": "system", "subtype": "init", "model": model,
          "tools": ["mcp__termsmet__" + name for name in sorted(TOOLS)] + (["Read"] if extra else [])})


def finish(value="synthetic complete"):
    emit({"type": "result", "is_error": False, "result": value})


async def run():
    prompt = sys.stdin.read()
    try:
        options = json.loads(prompt)
    except ValueError:
        options = {"mode": "templates", "role": "buyer"}
    mode = options["mode"]
    model = sys.argv[sys.argv.index("--model") + 1]
    config = json.loads(Path(sys.argv[sys.argv.index("--mcp-config") + 1]).read_text())["mcpServers"]["termsmet"]
    assert config["env"]["ANTHROPIC_API_KEY"] == ""
    assert list(Path.cwd().iterdir()) == []
    if mode == "missing_inventory":
        time.sleep(30)
        return
    if mode == "missing_final":
        init(model)
        return
    if mode == "extra_tool":
        init(model, extra=True)
        time.sleep(30)
        return
    if mode == "wrong_model":
        init("synthetic-other-model")
        return
    if mode in ("plain", "early"):
        init(model)
        if options.get("role") == "provider":
            await asyncio.sleep(0.3)
        finish("synthetic early exit")
        return
    if mode == "descendant":
        init(model)
        child = subprocess.Popen([sys.executable, "-c", "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"])
        emit({"type": "fixture_child", "pid": child.pid})
        time.sleep(30)
        return
    if mode == "interrupt":
        init(model)
        time.sleep(30)
        return
    if mode == "secret_output":
        init(model)
        print(os.environ["ANTHROPIC_API_KEY"], file=sys.stderr, flush=True)
        print(json.dumps({"credential": os.environ["ANTHROPIC_API_KEY"]}).replace("-", "\\u002d"), file=sys.stderr, flush=True)
        finish(os.environ["ANTHROPIC_API_KEY"])
        return

    async with stdio_client(StdioServerParameters(
        command=config["command"], args=config["args"], env=config["env"], cwd=Path.cwd(),
    )) as streams:
        async with ClientSession(*streams, read_timeout_seconds=5) as client:
            await client.initialize()
            await client.list_tools()
            if mode != "closed_gate":
                init(model)

            async def call(name, **arguments):
                response = await client.call_tool(name, arguments)
                assert not response.is_error
                return response.structured_content

            if mode == "cap":
                index = config["args"].index("--tool-limit")
                for _ in range(int(config["args"][index + 1]) + 1):
                    await call("get_job", job_id="synthetic-missing")
            elif mode == "business_errors":
                for _ in range(2):
                    result = await call("get_job", job_id="synthetic-missing")
                    assert result["error"]["code"] == "NOT_FOUND"
            elif mode == "transaction":
                role = options["role"]
                if role == "buyer":
                    job = await call("propose_agreement", template_id="order_extraction_v1",
                                     source_csv="Order,Units,Price\nSETUP-T,2,$1.125\n")
                    job_id = job["job_id"]
                    await call("accept_agreement", job_id=job_id, version=1)
                    while (await call("get_job", job_id=job_id))["status"] != "ACCEPTED":
                        await asyncio.sleep(0.02)
                    await call("fund_job", job_id=job_id)
                else:
                    while not (jobs := (await call("list_jobs"))["jobs"]):
                        await asyncio.sleep(0.02)
                    job_id = jobs[0]["job_id"]
                    await call("accept_agreement", job_id=job_id, version=1)
                    while (await call("get_job", job_id=job_id))["status"] != "FUNDED":
                        await asyncio.sleep(0.02)
                    result = await call("submit_delivery", job_id=job_id, delivery=[{
                        "order_id": "SETUP-T", "quantity": 2, "unit_price_cents": 113, "total_cents": 226,
                    }])
                    assert result["verdict"] == "PASS"
                    # Review expires without a further service call. The launcher
                    # must leave this transaction unfinished in its snapshot.
                    await asyncio.sleep(0.2)
            else:
                result = await call("list_templates")
                assert result["templates"][0]["template_id"] == "order_extraction_v1"
    finish()


if __name__ == "__main__":
    if "--version" in sys.argv:
        print("synthetic-test-cli")
    elif "--help" in sys.argv:
        print(" ".join(FLAGS))
    else:
        asyncio.run(run())
