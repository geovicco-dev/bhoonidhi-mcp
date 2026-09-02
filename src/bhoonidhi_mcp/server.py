"""The MCP server entry point.

Builds the server, registers the read-only Bhoonidhi tools over one shared
``BhoonidhiClient``, and runs the stdio transport. All tool logic lives in
``tools.py``; these wrappers only expose it to MCP with agent-facing schemas.
"""

from __future__ import annotations

import json

from bhoonidhi_downloader.sdk import BhoonidhiClient
from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from . import tools

server = MCPServer("bhoonidhi")
_client = BhoonidhiClient()


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def list_archive(refresh: bool = False) -> dict:
    """List every satellite and sensor the Bhoonidhi portal supports.

    Returns the vocabulary of valid satellites, sensors, and exact search
    tokens, with each product's resolution and date coverage. Call this to
    discover what can be searched. Set refresh=True to bypass the local cache.
    """
    return tools.list_archive(_client, refresh=refresh)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def resolve_location(name: str) -> dict:
    """Resolve a place name to a centroid and bounding box.

    Turns a place like "Shillong" or "Loktak Lake" into latitude/longitude and a
    bounding box (minx, miny, maxx, maxy) that search_scenes can use as its area
    of interest. Returns found=False when the place can't be resolved.
    """
    return tools.resolve_location(name)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
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
    are Archived, OnOrder, or Priced and what each needs. This search is
    stateless: to act on these scenes, call save_query with the same arguments to
    persist them and get a <slug>, then download_query (open data) or cart_add
    (on-order / priced) on that slug — both need a login (see auth_status).
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


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
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


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def save_query(
    satellite: str,
    start_date: str,
    end_date: str,
    name: str | None = None,
    description: str | None = None,
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
    """Persist a search as a saved query and return a reusable slug.

    Takes the same arguments as search_scenes, plus an optional name and
    description. Unlike search_scenes (which is stateless and leaves nothing
    behind), this saves the search on the portal so it can be acted on later:
    the returned slug is what downloading and cart staging key off. Call this
    once the user has confirmed a search returns the scenes they want, then hand
    the slug to the bhd CLI (download / cart) until those actions land in-server.

    Returns status="ok" with the slug and the shaped saved query. If the
    satellite is ambiguous or the request is invalid, returns the same
    status="ambiguous_satellite" / "invalid_request" shapes as search_scenes,
    and saves nothing.
    """
    return tools.save_query(
        _client,
        satellite,
        start_date,
        end_date,
        name=name,
        description=description,
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


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def list_queries() -> dict:
    """List every saved query as compact summaries.

    Returns each saved query's slug, name, date range, satellites, area of
    interest, scene count, and a plain-English availability summary — but not
    the full scene lists (call show_query for one query's scenes). Use this to
    find the slug for a query the user saved earlier.
    """
    return tools.list_queries(_client)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def show_query(slug: str) -> dict:
    """Return one saved query by slug, with its scenes.

    Give the slug from save_query or list_queries. Returns the full saved query:
    its selections, area of interest, date range, and shaped scenes with
    availability. Returns status="not_found" if no query has that slug.
    """
    return tools.show_query(_client, slug)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def remove_query(slug: str) -> dict:
    """Delete a saved query by slug.

    Give the slug from save_query or list_queries. Removes the saved query from
    disk; the scenes themselves are unaffected. Returns status="not_found" if no
    query has that slug.
    """
    return tools.remove_query(_client, slug)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def auth_status() -> dict:
    """Report whether a Bhoonidhi login is configured for downloads and cart.

    Never asks for or returns a password or token. If credentials are set in the
    server's environment (BHOONIDHI_USERNAME / BHOONIDHI_PASSWORD) it establishes
    the session so the answer matches what a download or cart action would find.
    Returns authenticated=True with the username when a usable session exists, or
    authenticated=False with guidance to log in ('bhd auth login' out of band, or
    set those environment variables). Call this before download or cart actions
    to tell the user if a login is needed.
    """
    return tools.auth_status(_client)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def download_query(
    slug: str,
    select: list | None = None,
    force: bool = False,
) -> dict:
    """Download a saved query's open-access scenes in the background.

    Give the slug from save_query or list_queries. Downloads run to a fixed,
    server-configured root (BHOONIDHI_MCP_DOWNLOAD_ROOT, default ~/Downloads),
    under a per-slug folder — you cannot choose an arbitrary path. select
    narrows to specific scenes (1-based indices or full scene IDs); omit it for
    the whole query. force re-downloads files already present.

    Needs a login (see auth_status). Priced and on-order scenes are skipped —
    stage those with cart_add instead. Returns immediately with a job_id: the
    download runs on its own and does NOT depend on this conversation, so never
    block by sleeping and re-polling. To follow it hands-free, delegate a
    background watcher that loops download_wait on the job_id and reports back,
    keeping you free to keep talking; the result's 'handoff' note says so. File
    sizes are unknown until each transfer starts (the portal reveals them only
    then); once a download proves large, download_status/download_wait flag it
    and 'large_download' offers a standalone command that outlives this session.
    Interrupted downloads restart from scratch (no resume support).
    """
    return tools.download_query(_client, slug, select=select, force=force)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def download_status(job_id: str) -> dict:
    """Check a background download started by download_query (one-off).

    Give the job_id from download_query. Returns the live state: running (with
    bytes_downloaded, mb_downloaded, rate_mb_s, percent when the total size is
    known, and per-scene detail), completed (with per-scene outcomes), or failed
    (with the error). Use this for a single progress check. To follow a job to
    completion without tying up the conversation, use download_wait from a
    delegated watcher instead. Jobs exist only while the server runs; an unknown
    id returns status="not_found".
    """
    return tools.download_status(job_id)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
)
def download_wait(job_id: str, timeout_s: float = 60.0) -> dict:
    """Wait for a background download to finish, then report — for a watcher.

    Give the job_id from download_query. Blocks inside the server and returns as
    soon as the download completes or fails, or after timeout_s (capped at 120s)
    with the latest progress if still running. This is the efficient way to
    follow a job: a delegated background watcher calls it in a loop and stops
    when status is "completed" or "failed", so the main conversation is never
    blocked on sleeps. Prefer this over repeated sleep+download_status. An
    unknown id returns status="not_found".
    """
    return tools.download_wait(job_id, timeout_s=timeout_s)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=False,
        idempotent_hint=False,
        open_world_hint=True,
    )
)
def cart_add(slug: str, select: list | None = None) -> dict:
    """Stage a saved query's scenes to the Bhoonidhi cart.

    Give the slug from save_query or list_queries. Each scene is routed to the
    cart its access type needs (ready / on-order / priced); select narrows to
    specific scenes (1-based indices or scene IDs). Needs a login (see
    auth_status). Use this for on-order and priced scenes; priced ones still
    need purchasing on the portal afterwards. Returns counts of what was staged
    and what failed.
    """
    return tools.cart_add(_client, slug, select=select)


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def cart_list(
    filter_by: str | None = None,
    since: str | None = None,
    until: str | None = None,
    last: str | None = None,
) -> dict:
    """List scenes currently staged in the Bhoonidhi cart.

    Cart items are filed by the date they were added; with no window this
    shows today only, so pass since/until (ISO dates, e.g. "2026-08-10") or
    last (e.g. "1 week") to widen it. filter_by limits to a state: ready,
    archived, onorder, or priced. Needs a login (see auth_status).
    """
    return tools.cart_list(
        _client, filter_by=filter_by, since=since, until=until, last=last
    )


@server.tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=True,
    )
)
def cart_remove(
    slug: str | None = None,
    select: list | None = None,
    since: str | None = None,
    until: str | None = None,
    last: str | None = None,
    filter_by: str | None = None,
) -> dict:
    """Remove scenes from the Bhoonidhi cart.

    Two ways to address rows: pass slug to index a saved query's scenes, or
    omit it and let select index the merged cart itself (the same row numbers
    cart_list shows under the same since/until/last/filter_by window). Needs
    a login (see auth_status).
    """
    return tools.cart_remove(
        _client,
        slug=slug,
        select=select,
        since=since,
        until=until,
        last=last,
        filter_by=filter_by,
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
