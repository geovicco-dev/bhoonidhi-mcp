"""The MCP server entry point.

Builds the server, registers the read-only Bhoonidhi tools over one shared
``BhoonidhiClient``, and runs the stdio transport. All tool logic lives in
``tools.py``; these wrappers only expose it to MCP with agent-facing schemas.
"""

from __future__ import annotations

import json

from bhoonidhi_downloader.sdk import BhoonidhiClient
from mcp.server.mcpserver import MCPServer

from . import tools

server = MCPServer("bhoonidhi")
_client = BhoonidhiClient()


@server.tool()
def list_archive(refresh: bool = False) -> dict:
    """List every satellite and sensor the Bhoonidhi portal supports.

    Returns the vocabulary of valid satellites, sensors, and exact search
    tokens, with each product's resolution and date coverage. Call this to
    discover what can be searched. Set refresh=True to bypass the local cache.
    """
    return tools.list_archive(_client, refresh=refresh)


@server.tool()
def resolve_location(name: str) -> dict:
    """Resolve a place name to a centroid and bounding box.

    Turns a place like "Shillong" or "Loktak Lake" into latitude/longitude and a
    bounding box (minx, miny, maxx, maxy) that search_scenes can use as its area
    of interest. Returns found=False when the place can't be resolved.
    """
    return tools.resolve_location(name)


@server.tool()
def search_scenes(
    satellite: str,
    start_date: str,
    end_date: str,
    minx: float | None = None,
    maxx: float | None = None,
    miny: float | None = None,
    maxy: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    sensor: str | None = None,
    product: str | None = None,
) -> dict:
    """Search Bhoonidhi scenes for a satellite over an area and date range.

    The satellite may be a casual name ("Sentinel-2", "cartosat"); it is matched
    to the portal's exact tokens, and a constellation expands to all its
    platforms. Dates are ISO (YYYY-MM-DD). Give the area either as a bounding box
    (minx/maxx/miny/maxy) or a point with radius (lat/lon/radius_km) — typically
    from resolve_location. sensor narrows to one sensor on the matched
    satellite(s) (e.g. "SSAR", "LISS3"); product further narrows to one product
    under that sensor (e.g. "GCOV", "L2C-Chlorophyll") — see list_archive for the
    exact sensor/product names each satellite carries. The search is stateless
    and needs no login.

    If the satellite name is ambiguous, returns status="ambiguous_satellite"
    with candidate names instead of guessing.

    Each scene carries an "availability": Ready (downloadable now), Archived
    (open data but may need a portal request first), OnOrder (must be requested),
    or Priced (must be purchased). The result includes a plain-English "summary"
    of these counts and a "how_to_act" block. Tell the user clearly when scenes
    are Archived, OnOrder, or Priced and what each needs. This server is
    read-only for now: it cannot download scenes or add them to a cart —
    those are planned for a future update. Until then, "how_to_act" gives the
    exact bhd CLI commands the user runs themselves (after 'bhd auth login').
    Downloads cannot be resumed if interrupted (the portal has no range support).
    """
    return tools.search_scenes(
        _client,
        satellite,
        start_date,
        end_date,
        minx=minx,
        maxx=maxx,
        miny=miny,
        maxy=maxy,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        sensor=sensor,
        product=product,
    )


@server.tool()
def preview_download(
    satellite: str,
    start_date: str,
    end_date: str,
    out_dir: str = "./downloads",
    minx: float | None = None,
    maxx: float | None = None,
    miny: float | None = None,
    maxy: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    sensor: str | None = None,
    product: str | None = None,
    force: bool = False,
) -> dict:
    """Dry-run a download for a search: show what would be fetched, no login.

    Takes the same arguments as search_scenes, plus out_dir (where files would
    go) and force (preview re-downloading files already present). It runs the
    search and predicts, per scene, what a real download would do: would_download
    (staged, ready), may_404 (open data but archived — attempted but may fail
    until requested on the portal), already_here / already_elsewhere (a matching
    file exists), or skipped_on_order / skipped_priced (needs the portal).

    Use this before telling a user to download, so they know how many scenes are
    actually fetchable. Nothing is downloaded and no login is used. File sizes
    are not known until a download starts (the portal exposes them only in the
    download response headers), and interrupted downloads cannot be resumed —
    both are stated in the result's disclaimers.
    """
    return tools.preview_download(
        _client,
        satellite,
        start_date,
        end_date,
        out_dir=out_dir,
        minx=minx,
        maxx=maxx,
        miny=miny,
        maxy=maxy,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        sensor=sensor,
        product=product,
        force=force,
    )


@server.resource("bhoonidhi://archive")
def archive_resource() -> str:
    """The portal's satellite/sensor vocabulary, as read-only context."""
    return json.dumps(tools.list_archive(_client))


def main() -> None:
    """Run the server over stdio (how desktop MCP clients launch it)."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
