"""Per-tool risk tagging.

Each tool declares its own risk with `@risk("LOW" | "MEDIUM" | "HIGH")` right
next to its definition. The decorator stamps "Risk: LEVEL." onto the front of
the function's docstring; MCP's introspection turns that docstring into the
tool's `description` field, and the backend's MCPManager reads the tag back
out of it (see backend/app/mcp/manager.py::_parse_risk).

Why this instead of a central risk table in the backend: adding a new tool to
any server automatically gets classified — nobody has to remember to also
update a switch statement somewhere else in the codebase.

Usage (note the order — `risk` goes closest to the function so it runs first):

    @mcp.tool()
    @risk("HIGH")
    def send_email(to: str, subject: str, body: str) -> dict:
        \"\"\"Send an email on the user's behalf.\"\"\"
        ...
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)

_LEVELS = {"LOW", "MEDIUM", "HIGH"}


def risk(level: str) -> Callable[[F], F]:
    level = level.upper()
    if level not in _LEVELS:
        raise ValueError(f"Unknown risk level {level!r}, expected one of {_LEVELS}")

    def decorator(func: F) -> F:
        doc = (func.__doc__ or "").strip()
        func.__doc__ = f"Risk: {level}. {doc}"
        return func

    return decorator
