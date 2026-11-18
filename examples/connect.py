"""Connect two official-SDK clients; no agent decisions or settlement workflow."""

import argparse
import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def connect(database: Path) -> None:
    runtime = Path(__file__).resolve().parents[1]
    async with AsyncExitStack() as stack:
        sessions = {}
        for identity in ("buyer", "provider"):
            streams = await stack.enter_async_context(stdio_client(StdioServerParameters(
                command=sys.executable,
                args=["-m", "server.mcp_server"],
                cwd=runtime,
                env={
                    "TERMSMET_IDENTITY": identity,
                    "TERMSMET_DB_PATH": str(database),
                    "TERMSMET_REVIEW_SECONDS": "2",
                    "TERMSMET_FIRST_SUBMIT_MIN": "5",
                },
            )))
            session = await stack.enter_async_context(ClientSession(*streams, read_timeout_seconds=10))
            await session.initialize()
            sessions[identity] = session
        for identity, session in sessions.items():
            inventory = await session.list_tools()
            templates = await session.call_tool("list_templates", {})
            if templates.is_error:
                raise RuntimeError(f"{identity}: list_templates failed: {templates.content}")
            print(json.dumps({
                "identity": identity,
                "tools": [tool.name for tool in inventory.tools],
                "list_templates": templates.structured_content,
            }))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="absolute shared SQLite file path")
    args = parser.parse_args()
    if not args.db.is_absolute():
        parser.error("--db must be an absolute file path")
    asyncio.run(connect(args.db))


if __name__ == "__main__":
    main()
