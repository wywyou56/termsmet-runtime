"""Environment-assigned TermsMet MCP process: python -m server.mcp_server."""

import logging
import math
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.tools import Tool
from pydantic import ConfigDict, WithJsonSchema, create_model

from .service import TermsMetService
from .storage import open_database


@dataclass(frozen=True)
class Config:
    identity: str
    db_path: Path
    first_submit_minutes: float
    review_seconds: float


def load_config() -> Config:
    identity = os.environ.get("TERMSMET_IDENTITY")
    if identity not in ("buyer", "provider"):
        raise ValueError("TERMSMET_IDENTITY must be buyer or provider")

    db_path = Path(os.environ.get("TERMSMET_DB_PATH", ""))
    if not db_path.is_absolute():
        raise ValueError("TERMSMET_DB_PATH must be an absolute database file path")

    durations = []
    for name, default in (
        ("TERMSMET_FIRST_SUBMIT_MIN", "5"),
        ("TERMSMET_REVIEW_SECONDS", "10"),
    ):
        try:
            duration = float(os.environ.get(name, default))
        except ValueError:
            raise ValueError(f"{name} must be a positive finite number") from None
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"{name} must be a positive finite number")
        durations.append(duration)

    return Config(identity, db_path, *durations)


def create_server(service: TermsMetService) -> MCPServer:
    async def list_templates() -> dict[str, object]:
        """List supported acceptance templates and their negotiable terms."""
        return service.call("list_templates")

    async def propose_agreement(template_id: str, source_csv: str) -> dict[str, object]:
        """Buyer: propose an order extraction agreement from the original CSV text."""
        return service.call("propose_agreement", template_id=template_id, source_csv=source_csv)

    async def list_jobs() -> dict[str, object]:
        """List the caller's jobs and current-version acceptance status."""
        return service.call("list_jobs")

    async def get_job(job_id: str) -> dict[str, object]:
        """Read current agreement terms, original source, status and started deadlines."""
        return service.call("get_job", job_id=job_id)

    async def counter_agreement(job_id: str, repair_window_minutes: int) -> dict[str, object]:
        """Provider: counter an unlocked agreement's repair window to 5 or 10 minutes."""
        return service.call("counter_agreement", job_id=job_id, repair_window_minutes=repair_window_minutes)

    async def accept_agreement(job_id: str, version: int) -> dict[str, object]:
        """Accept the current agreement version for this process's identity only."""
        return service.call("accept_agreement", job_id=job_id, version=version)

    async def fund_job(job_id: str) -> dict[str, object]:
        """Buyer: confirm simulated funding and start the first-submission deadline."""
        return service.call("fund_job", job_id=job_id)

    async def submit_delivery(
        job_id: str,
        delivery: Annotated[Any, WithJsonSchema({"type": "array", "items": {"type": "object"}})],
        ctx: Context,
    ) -> dict[str, object]:
        """Provider: submit delivery records for deterministic checking and private storage."""
        # The SDK may pre-parse JSON-looking strings; preserve what was actually submitted.
        delivery = ctx.request_context.params["arguments"]["delivery"]
        return service.call("submit_delivery", job_id=job_id, delivery=delivery)

    async def get_result(job_id: str, submission_version: int) -> dict[str, object]:
        """Read an immutable check report, settlement status and terminal receipt."""
        return service.call("get_result", job_id=job_id, submission_version=submission_version)

    async def challenge_result(job_id: str, submission_version: int, reason_code: str) -> dict[str, object]:
        """Challenge current check provenance, or record a provider's failure dispute."""
        return service.call("challenge_result", job_id=job_id,
                            submission_version=submission_version, reason_code=reason_code)

    async def retrieve_delivery(job_id: str) -> dict[str, object]:
        """Buyer: retrieve the current delivery only after confirmed simulated release."""
        return service.call("retrieve_delivery", job_id=job_id)

    tools = []
    for function in (list_templates, propose_agreement, list_jobs, get_job,
                     counter_agreement, accept_agreement, fund_job, submit_delivery, get_result,
                     challenge_result, retrieve_delivery):
        tool = Tool.from_function(function)
        # Configure the SDK's own validator; keep protocol errors in the SDK.
        arguments = tool.fn_metadata.arg_model
        tool.fn_metadata.arg_model = create_model(
            arguments.__name__, __base__=arguments, __config__=ConfigDict(strict=True, extra="forbid")
        )
        tool.parameters = tool.fn_metadata.arg_model.model_json_schema()
        tools.append(tool)
    return MCPServer("TermsMet", tools=tools)


def main() -> int:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s: %(message)s")
    try:
        config = load_config()
        with closing(open_database(config.db_path)) as connection:
            service = TermsMetService(connection, config.identity, config.first_submit_minutes,
                                      review_seconds=config.review_seconds)
            server = create_server(service)
            logging.getLogger(__name__).info("TermsMet MCP ready (identity=%s)", config.identity)
            server.run(transport="stdio")
    except (ValueError, OSError, sqlite3.Error) as exc:
        logging.getLogger(__name__).error("TermsMet could not start: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
