"""Location MCP server — geocoding, distance, and nearby-place search.

Backed by OpenStreetMap's public Nominatim + Overpass APIs. No API key needed.
"""
from __future__ import annotations

import math

from mcp.server.fastmcp import FastMCP

from mcp_servers.shared.http import get_json
from mcp_servers.shared.risk import risk

mcp = FastMCP("location")

_NOMINATIM = "https://nominatim.openstreetmap.org"
_OVERPASS = "https://overpass-api.de/api/interpreter"


async def _geocode(place: str) -> dict | None:
    results = await get_json(f"{_NOMINATIM}/search", params={"q": place, "format": "json", "limit": 1})
    if not results:
        return None
    r = results[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "display_name": r["display_name"]}


@mcp.tool()
@risk("LOW")
async def geocode(place: str) -> dict:
    """Look up the latitude/longitude and full address for a place name."""
    result = await _geocode(place)
    if not result:
        return {"error": f"Could not geocode '{place}'."}
    return result


@mcp.tool()
@risk("LOW")
async def distance_between(place_a: str, place_b: str) -> dict:
    """Compute the great-circle distance in kilometers between two named places."""
    a, b = await _geocode(place_a), await _geocode(place_b)
    if not a or not b:
        missing = place_a if not a else place_b
        return {"error": f"Could not geocode '{missing}'."}

    r = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    km = 2 * r * math.asin(math.sqrt(h))
    return {
        "from": a["display_name"],
        "to": b["display_name"],
        "distance_km": round(km, 2),
        "distance_miles": round(km * 0.621371, 2),
    }


@mcp.tool()
@risk("LOW")
async def find_nearby(place: str, category: str, radius_km: float = 2.0, max_results: int = 8) -> dict:
    """Find nearby points of interest (e.g. category='restaurant', 'cafe', 'pharmacy', 'atm') around a place."""
    origin = await _geocode(place)
    if not origin:
        return {"error": f"Could not geocode '{place}'."}

    radius_m = int(max(0.1, min(radius_km, 20)) * 1000)
    query = f"""
    [out:json][timeout:15];
    (
      node["amenity"="{category}"](around:{radius_m},{origin['lat']},{origin['lon']});
      node["shop"="{category}"](around:{radius_m},{origin['lat']},{origin['lon']});
    );
    out center {max(1, min(max_results, 20))};
    """
    data = await get_json(_OVERPASS, params={"data": query})
    places = [
        {
            "name": el.get("tags", {}).get("name", "Unnamed"),
            "lat": el.get("lat"),
            "lon": el.get("lon"),
            "tags": {k: v for k, v in el.get("tags", {}).items() if k in ("amenity", "shop", "addr:street")},
        }
        for el in data.get("elements", [])
    ]
    return {"origin": origin["display_name"], "category": category, "results": places}


if __name__ == "__main__":
    mcp.run()
