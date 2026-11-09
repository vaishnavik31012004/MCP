"""The MCP client side: launches every configured MCP server as a stdio
subprocess, discovers its tools, and exposes a single flat, namespaced tool
registry to the agent.

Tool discovery is fully dynamic. Add a new `@mcp.tool()` function to any
server in mcp_servers/, restart the backend, and it shows up here — and in
the LLM's tool list — automatically. Nothing in this file names a specific
tool. Risk classification is dynamic too: it's read off a `Risk: LEVEL.`
marker in each tool's own docstring (see mcp_servers/shared/risk.py), not
looked up in a table here.

Each server's connection lives on its own long-running asyncio.Task for the
whole app lifetime. This isn't just style: anyio's cancel scopes (which the
`mcp` SDK's stdio/session context managers use under the hood) must be
entered and exited from the *same* task, so opening a connection in one task
and closing it from another — e.g. a plain gather() followed by a later
close() — raises "Attempted to exit cancel scope in a different task". One
task per server, parked on an internal stop-event, keeps every server's
open/close pair on the same task.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from mcp import ClientSession, StdioServerParameters

from app.config import get_settings
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# backend/app/mcp/manager.py -> project root is three levels up. Computed
# from this file's location (not the process's cwd) so that MCP server
# subprocesses can `import mcp_servers` regardless of whether the backend
# was launched from the project root, from backend/, or anywhere else.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]

_RISK_PATTERN = re.compile(r"^\s*Risk:\s*(LOW|MEDIUM|HIGH)\b\.?\s*", re.IGNORECASE)

# name -> module run as `python -m <module>`. This is the only place a server
# has to be registered; everything downstream (tools, risk, schemas) is
# discovered from it at connect time.
SERVERS: dict[str, str] = {
    "utility": "mcp_servers.utility.server",
    "information": "mcp_servers.information.server",
    "location": "mcp_servers.location.server",
    "nylas": "mcp_servers.nylas.server",
}


def _parse_risk(description: str | None) -> str:
    if not description:
        return "LOW"
    match = _RISK_PATTERN.match(description)
    return match.group(1).upper() if match else "LOW"


def _clean_description(description: str | None) -> str:
    if not description:
        return ""
    return _RISK_PATTERN.sub("", description).strip()


@dataclass
class ToolInfo:
    name: str  # namespaced, e.g. "nylas__send_email"
    server: str
    raw_name: str
    description: str
    risk: str
    input_schema: dict[str, Any]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


class MCPManager:
    def __init__(self, python_executable: str = "python"):
        self._python = python_executable
        self._sessions: dict[str, ClientSession] = {}
        self._call_locks: dict[str, asyncio.Lock] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self.tools: dict[str, ToolInfo] = {}
        self.errors: dict[str, str] = {}

    async def connect_all(self) -> None:
        ready_events: dict[str, asyncio.Event] = {}
        for name, module in SERVERS.items():
            ready = asyncio.Event()
            stop = asyncio.Event()
            ready_events[name] = ready
            self._stop_events[name] = stop
            self._tasks[name] = asyncio.create_task(self._server_task(name, module, ready, stop))
        await asyncio.gather(*(ev.wait() for ev in ready_events.values()))
        logger.info(
            "MCP: connected %d/%d servers, %d tools discovered",
            len(self._sessions),
            len(SERVERS),
            len(self.tools),
        )

    async def _server_task(self, name: str, module: str, ready: asyncio.Event, stop: asyncio.Event) -> None:
        try:
            settings = get_settings()

            params = StdioServerParameters(
                command=self._python,
                args=["-m", module],
                cwd=str(_PROJECT_ROOT),
                env={
                    **os.environ,
                    "PYTHONPATH": str(_PROJECT_ROOT),
                    "NYLAS_API_KEY": settings.nylas_api_key,
                    "NYLAS_GRANT_ID": settings.nylas_grant_id,
                    "NYLAS_API_URI": settings.nylas_api_uri,
                },
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    for tool in listed.tools:
                        info = ToolInfo(
                            name=f"{name}__{tool.name}",
                            server=name,
                            raw_name=tool.name,
                            description=_clean_description(tool.description),
                            risk=_parse_risk(tool.description),
                            input_schema=tool.inputSchema or {},
                        )
                        self.tools[info.name] = info
                    self._sessions[name] = session
                    self._call_locks[name] = asyncio.Lock()
                    ready.set()
                    await stop.wait()
        except Exception as exc:  # noqa: BLE001 -- one bad server shouldn't take the rest down
            logger.exception("MCP: server %r failed", name)
            self.errors[name] = str(exc)
            ready.set()
        finally:
            self._sessions.pop(name, None)

    async def call_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> Any:
        info = self.tools.get(namespaced_name)
        if info is None:
            raise ValueError(f"Unknown tool: {namespaced_name}")
        session = self._sessions.get(info.server)
        if session is None:
            raise RuntimeError(f"Server '{info.server}' is not connected.")
        # Calls to the same server's session are serialized: stdio is a single
        # duplex pipe, so concurrent calls on one session would interleave.
        async with self._call_locks[info.server]:
            result = await session.call_tool(info.raw_name, arguments)
        if result.isError:
            text = "; ".join(getattr(c, "text", "") for c in result.content)
            raise RuntimeError(text or "Tool call failed.")
        for block in result.content:
            text = getattr(block, "text", None)
            if text is not None:
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return text
        return None

    def get_risk(self, namespaced_name: str) -> str:
        info = self.tools.get(namespaced_name)
        return info.risk if info else "HIGH"  # unknown tool -> treat as dangerous by default

    def openai_tools(self) -> list[dict[str, Any]]:
        return [t.as_openai_tool() for t in self.tools.values()]

    def status(self) -> dict[str, Any]:
        return {
            "servers_connected": sorted(self._sessions.keys()),
            "servers_total": len(SERVERS),
            "errors": self.errors,
            "tools": [
                {"name": t.name, "server": t.server, "risk": t.risk, "description": t.description}
                for t in self.tools.values()
            ],
        }

    async def close(self) -> None:
        for stop in self._stop_events.values():
            stop.set()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._sessions.clear()
        self._tasks.clear()
        self._stop_events.clear()
