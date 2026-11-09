"""Utility MCP server — weather, currency conversion, a safe calculator, and time.

None of these need API keys: weather is Open-Meteo (geocoding + forecast),
currency is Frankfurter (backed by the ECB), time is the standard library.
Every tool hits a live API at call time — nothing here is a canned answer.
"""
from __future__ import annotations

import ast
import datetime
import operator
import zoneinfo

from mcp.server.fastmcp import FastMCP

from mcp_servers.shared.http import get_json
from mcp_servers.shared.risk import risk

mcp = FastMCP("utility")

# ── Weather ───────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
async def get_weather(location: str) -> dict:
    """Get the current weather for a city or place name."""
    geo = await get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1},
    )
    results = geo.get("results") or []
    if not results:
        return {"error": f"Could not find a location matching '{location}'."}
    place = results[0]
    lat, lon = place["latitude"], place["longitude"]

    weather = await get_json(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "timezone": "auto",
        },
    )
    current = weather.get("current", {})
    return {
        "location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "latitude": lat,
        "longitude": lon,
        "temperature_c": current.get("temperature_2m"),
        "humidity_pct": current.get("relative_humidity_2m"),
        "wind_speed_kmh": current.get("wind_speed_10m"),
        "observed_at": current.get("time"),
    }


@mcp.tool()
@risk("LOW")
async def get_forecast(location: str, days: int = 3) -> dict:
    """Get a multi-day daily weather forecast (max/min temp, precipitation chance) for a place."""
    days = max(1, min(days, 14))
    geo = await get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": location, "count": 1},
    )
    results = geo.get("results") or []
    if not results:
        return {"error": f"Could not find a location matching '{location}'."}
    place = results[0]

    forecast = await get_json(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": days,
        },
    )
    daily = forecast.get("daily", {})
    dates = daily.get("time", [])
    return {
        "location": f"{place.get('name')}, {place.get('country', '')}".strip(", "),
        "days": [
            {
                "date": dates[i],
                "max_c": daily["temperature_2m_max"][i],
                "min_c": daily["temperature_2m_min"][i],
                "precipitation_chance_pct": daily.get("precipitation_probability_max", [None] * len(dates))[i],
            }
            for i in range(len(dates))
        ],
    }


# ── Currency ──────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
async def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert an amount from one currency to another using live exchange rates."""
    data = await get_json(
        "https://api.frankfurter.app/latest",
        params={"amount": amount, "from": from_currency.upper(), "to": to_currency.upper()},
    )
    rates = data.get("rates", {})
    converted = rates.get(to_currency.upper())
    if converted is None:
        return {"error": f"No rate available for {from_currency} -> {to_currency}."}
    return {
        "amount": amount,
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "converted_amount": converted,
        "rate_date": data.get("date"),
    }


# ── Calculator (safe, no eval/exec) ──────────────────────────────────────

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_safe_eval(node.operand))
    raise ValueError("Expression contains unsupported syntax.")


@mcp.tool()
@risk("LOW")
def calculate(expression: str) -> dict:
    """Evaluate a basic arithmetic expression (+, -, *, /, %, **, parentheses). No variables or functions."""
    try:
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree.body)
        return {"expression": expression, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"Could not evaluate '{expression}': {exc}"}


# ── Time ──────────────────────────────────────────────────────────────────


@mcp.tool()
@risk("LOW")
def get_current_time(timezone: str = "UTC") -> dict:
    """Get the current date and time in a given IANA timezone (e.g. 'Asia/Kolkata', 'America/New_York')."""
    try:
        tz = zoneinfo.ZoneInfo(timezone)
    except Exception:
        return {"error": f"Unknown timezone '{timezone}'."}
    now = datetime.datetime.now(tz)
    return {"timezone": timezone, "iso": now.isoformat(), "readable": now.strftime("%A, %d %B %Y %H:%M:%S")}


if __name__ == "__main__":
    mcp.run()
