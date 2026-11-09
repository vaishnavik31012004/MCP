"""Nylas MCP server — email, calendar, and contacts behind a single API key.

Nylas unifies Gmail, Outlook, iCloud, and Exchange behind one v3 REST API, so
this one server (one NYLAS_API_KEY + one NYLAS_GRANT_ID) replaces what would
otherwise be a separate Google OAuth flow, a separate Microsoft Graph flow,
and hand-rolled SMTP/IMAP code. Every call below hits the live Nylas API —
nothing here is mocked or dry-run.

Setup: connect an inbox at https://dashboard-v3.nylas.com to get a grant,
then put NYLAS_API_KEY / NYLAS_GRANT_ID / NYLAS_API_URI in backend/.env.
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.shared.http import request_json
from mcp_servers.shared.risk import risk

mcp = FastMCP("nylas")


def _config() -> tuple[str, str, str] | None:
    api_key = os.environ.get("NYLAS_API_KEY")
    grant_id = os.environ.get("NYLAS_GRANT_ID")
    api_uri = os.environ.get("NYLAS_API_URI", "https://api.us.nylas.com")
    if not api_key or not grant_id:
        return None
    return api_key, grant_id, api_uri


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _not_configured() -> dict:
    return {
        "error": (
            "Nylas isn't configured. Set NYLAS_API_KEY and NYLAS_GRANT_ID in backend/.env "
            "(create a grant at https://dashboard-v3.nylas.com)."
        )
    }


# ── Email ─────────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
async def list_emails(query: str = "", max_results: int = 10) -> dict:
    """List recent emails in the connected inbox, optionally filtered by a search term (subject/sender)."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    params: dict = {"limit": max(1, min(max_results, 25))}
    if query:
        params["search_query_native"] = query
    data = await request_json(
        "GET", f"{api_uri}/v3/grants/{grant_id}/messages", params=params, headers=_headers(api_key)
    )
    messages = [
        {
            "id": m.get("id"),
            "subject": m.get("subject"),
            "from": m.get("from"),
            "date": m.get("date"),
            "snippet": m.get("snippet"),
            "unread": m.get("unread"),
        }
        for m in data.get("data", [])
    ]
    return {"messages": messages}


@mcp.tool()
@risk("HIGH")
async def send_email(to: str, subject: str, body: str, cc: str = "") -> dict:
    """Send an email from the connected account. `to` and `cc` are comma-separated email addresses."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    payload = {
        "to": [{"email": addr.strip()} for addr in to.split(",") if addr.strip()],
        "subject": subject,
        "body": body,
    }
    if cc:
        payload["cc"] = [{"email": addr.strip()} for addr in cc.split(",") if addr.strip()]
    data = await request_json(
        "POST", f"{api_uri}/v3/grants/{grant_id}/messages/send", json_body=payload, headers=_headers(api_key)
    )
    sent = data.get("data", {})
    return {"status": "sent", "id": sent.get("id"), "subject": sent.get("subject")}


# ── Calendar ──────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
async def list_calendar_events(start_iso: str, end_iso: str, calendar_id: str = "primary") -> dict:
    """List calendar events between two ISO-8601 datetimes, e.g. start_iso='2026-09-20T00:00:00Z'."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    import datetime

    try:
        start_ts = int(datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
        end_ts = int(datetime.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return {"error": "start_iso/end_iso must be ISO-8601 datetimes."}

    data = await request_json(
        "GET",
        f"{api_uri}/v3/grants/{grant_id}/events",
        params={"calendar_id": calendar_id, "start": start_ts, "end": end_ts},
        headers=_headers(api_key),
    )
    events = [
        {
            "id": e.get("id"),
            "title": e.get("title"),
            "when": e.get("when"),
            "participants": [p.get("email") for p in e.get("participants", [])],
            "location": e.get("location"),
        }
        for e in data.get("data", [])
    ]
    return {"events": events}


@mcp.tool()
@risk("MEDIUM")
async def create_calendar_event(
    title: str, start_iso: str, end_iso: str, participants: str = "", calendar_id: str = "primary"
) -> dict:
    """Create a calendar event. `participants` is a comma-separated list of email addresses to invite."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    import datetime

    try:
        start_ts = int(datetime.datetime.fromisoformat(start_iso.replace("Z", "+00:00")).timestamp())
        end_ts = int(datetime.datetime.fromisoformat(end_iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return {"error": "start_iso/end_iso must be ISO-8601 datetimes."}

    payload: dict = {
        "title": title,
        "when": {"start_time": start_ts, "end_time": end_ts},
    }
    if participants:
        payload["participants"] = [{"email": addr.strip()} for addr in participants.split(",") if addr.strip()]

    data = await request_json(
        "POST",
        f"{api_uri}/v3/grants/{grant_id}/events",
        params={"calendar_id": calendar_id},
        json_body=payload,
        headers=_headers(api_key),
    )
    created = data.get("data", {})
    return {"status": "created", "id": created.get("id"), "title": created.get("title")}


@mcp.tool()
@risk("HIGH")
async def delete_calendar_event(event_id: str, calendar_id: str = "primary") -> dict:
    """Permanently delete a calendar event by its ID."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    await request_json(
        "DELETE",
        f"{api_uri}/v3/grants/{grant_id}/events/{event_id}",
        params={"calendar_id": calendar_id},
        headers=_headers(api_key),
    )
    return {"status": "deleted", "id": event_id}


# ── Contacts ──────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
async def list_contacts(query: str = "", max_results: int = 15) -> dict:
    """List contacts in the connected account, optionally filtered by name/email."""
    cfg = _config()
    if not cfg:
        return _not_configured()
    api_key, grant_id, api_uri = cfg
    params: dict = {"limit": max(1, min(max_results, 25))}
    if query:
        params["email"] = query
    data = await request_json(
        "GET", f"{api_uri}/v3/grants/{grant_id}/contacts", params=params, headers=_headers(api_key)
    )
    contacts = [
        {
            "id": c.get("id"),
            "name": c.get("given_name", "") + " " + c.get("surname", ""),
            "emails": [e.get("email") for e in c.get("emails", [])],
        }
        for c in data.get("data", [])
    ]
    return {"contacts": contacts}


if __name__ == "__main__":
    mcp.run()
