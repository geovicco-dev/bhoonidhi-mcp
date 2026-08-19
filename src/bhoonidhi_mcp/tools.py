"""The Bhoonidhi MCP tools — thin adapters over the downloader SDK.

Each function takes the ``BhoonidhiClient`` explicitly so it stays pure and
testable; ``server.py`` builds one client and registers the MCP-facing wrappers.
All SDK calls are wrapped in :func:`sdk_console_to_stderr` so the SDK's progress
output never reaches the JSON-RPC channel.

Output is shaped for an agent: trimmed dicts and plain values, never the SDK's
Rich objects. Scene availability is classified through the SDK's public
``scene_availability`` (the same logic the CLI uses), so an agent can tell a
staged scene from an archived one instead of guessing from the raw token.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from bhoonidhi_downloader.exceptions import (
    BhoonidhiAPIError,
    BhoonidhiAuthError,
    BhoonidhiError,
    BhoonidhiNotFoundError,
    BhoonidhiValidationError,
)
from bhoonidhi_downloader.sdk import preview_download as _sdk_preview
from bhoonidhi_downloader.sdk import scene_availability

from . import jobs
from .geocode import resolve_location as _resolve_place
from .matching import Vocabulary, resolve_satellite
from .protocol_safety import sdk_console_to_stderr

FUZZY_THRESHOLD = int(os.environ.get("BHOONIDHI_MCP_FUZZY_THRESHOLD", "88"))
MAX_RESULTS = int(os.environ.get("BHOONIDHI_MCP_MAX_RESULTS", "50"))
DOWNLOAD_PARALLEL = int(os.environ.get("BHOONIDHI_MCP_DOWNLOAD_PARALLEL", "4"))
# Downloads are confined to this root; a slug never escapes it. Read lazily so
# tests and a reconfigured environment see the current value.
_DEFAULT_DOWNLOAD_ROOT = "~/Downloads"


def _download_root() -> Path:
    """The allow-listed root every download is written under, as an absolute path."""
    raw = os.environ.get("BHOONIDHI_MCP_DOWNLOAD_ROOT", _DEFAULT_DOWNLOAD_ROOT)
    return Path(raw).expanduser().resolve()

_vocab_cache: Vocabulary | None = None


def _get_vocab(client: Any) -> Vocabulary:
    """Build the satellite vocabulary once and reuse it across searches."""
    global _vocab_cache
    if _vocab_cache is None:
        with sdk_console_to_stderr():
            _vocab_cache = Vocabulary.from_archive(client.archive.list())
    return _vocab_cache


# --- shaping ---------------------------------------------------------------


def _shape_archive_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "satellite": record.get("satName"),
        "sensors": [
            {
                "sensor": s.get("senName"),
                "token": s.get("dispName"),  # the exact SAT_SEN_PROD search token
                "resolution_m": s.get("res"),
                "start": s.get("stDate") or None,
                "end": s.get("endDate") or None,
            }
            for s in record.get("sensors", [])
        ],
    }


def _shape_scene(scene: dict[str, Any]) -> dict[str, Any]:
    state = scene_availability(scene)
    return {
        "id": scene.get("ID"),
        "satellite": scene.get("SATELLITE"),
        "sensor": scene.get("SENSOR"),
        "selection": scene.get("SELECTION"),
        "date_of_pass": scene.get("DOP"),
        # Classified state: "Ready" (staged, downloads now), "Archived" (open
        # data but may 404 until requested), "OnOrder", or "Priced".
        "availability": state.label,
        # True only when a download would actually be attempted.
        "downloadable": state.is_downloadable,
        "center": {
            "lat": scene.get("SCENE_CENTER_LAT"),
            "lon": scene.get("SCENE_CENTER_LONG"),
        },
    }


# --- tools ------------------------------------------------------------------


def list_archive(client: Any, *, refresh: bool = False) -> dict[str, Any]:
    """Return the portal's satellite/sensor vocabulary as shaped JSON."""
    with sdk_console_to_stderr():
        archive = client.archive.list(refresh=refresh)
    return {"satellites": [_shape_archive_record(r) for r in archive]}


def resolve_location(name: str) -> dict[str, Any]:
    """Resolve a place name to a centroid and bounding box."""
    place = _resolve_place(name)
    if place is None:
        return {
            "found": False,
            "query": name,
            "reason": (
                "Not a recognisable place name. Give a place (city, district, "
                "lake, park); bare numbers or coordinates are not resolved — "
                "if you already have coordinates, pass them to search_scenes as "
                "a bounding box or point."
            ),
        }
    minx, miny, maxx, maxy = place.bbox
    return {
        "found": True,
        "name": place.name,
        "lat": place.lat,
        "lon": place.lon,
        "bbox": {"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy},
    }


def search_scenes(
    client: Any,
    satellite: str,
    start_date: str,
    end_date: str,
    *,
    minx: float | None = None,
    maxx: float | None = None,
    miny: float | None = None,
    maxy: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    sensor: str | None = None,
    product: str | None = None,
    max_results: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Search scenes for a satellite over an area and date range (stateless).

    The satellite name is fuzzy-resolved to exact portal tokens first; if the
    name is ambiguous, candidates are returned instead of a guessed search. Give
    an area either as a bounding box (minx/maxx/miny/maxy) or a point plus radius
    (lat/lon/radius_km).
    """
    error, query, selections = _run_search(
        client, satellite, start_date, end_date,
        minx=minx, maxx=maxx, miny=miny, maxy=maxy,
        lat=lat, lon=lon, radius_km=radius_km, sensor=sensor, product=product,
    )
    if error is not None:
        return error

    scenes = query.scenes if query else []
    shaped = [_shape_scene(s) for s in scenes[:max_results]]
    counts = _availability_summary(scenes)
    result: dict[str, Any] = {
        "status": "ok",
        "matched_satellites": [s.satellite for s in selections],
        "total": len(scenes),
        "returned": len(shaped),
        "availability_summary": counts,
        "summary": _plain_summary(counts),
        "scenes": shaped,
    }
    if scenes:
        result["how_to_act"] = _how_to_act(counts)
    return result


def _validate_args(
    satellite: str,
    minx: float | None,
    maxx: float | None,
    miny: float | None,
    maxy: float | None,
    lat: float | None,
    lon: float | None,
    radius_km: float | None,
) -> dict[str, Any] | None:
    """Validate satellite and area-of-interest arguments before any search.

    Returns an ``invalid_request`` error dict describing the first problem, or
    None when the arguments are usable. Catches the malformed inputs that would
    otherwise reach the portal and come back as an indistinguishable empty
    result: no satellite, no/both AOI forms, an out-of-range radius, or a
    bounding box with min beyond max.
    """
    if not satellite or not satellite.strip():
        return {
            "status": "invalid_request",
            "error": "satellite is required (e.g. 'Sentinel-2', 'cartosat').",
        }

    has_bbox = any(v is not None for v in (minx, maxx, miny, maxy))
    has_point = any(v is not None for v in (lat, lon, radius_km))

    if not has_bbox and not has_point:
        return {
            "status": "invalid_request",
            "error": (
                "No area of interest. Give either a bounding box "
                "(minx, maxx, miny, maxy) or a point (lat, lon, optional "
                "radius_km) — typically from resolve_location."
            ),
        }
    if has_bbox and has_point:
        return {
            "status": "invalid_request",
            "error": (
                "Give only one area of interest: a bounding box OR a point, "
                "not both."
            ),
        }

    if has_bbox:
        if minx is None or maxx is None or miny is None or maxy is None:
            return {
                "status": "invalid_request",
                "error": "A bounding box needs all four of minx, maxx, miny, maxy.",
            }
        if minx >= maxx or miny >= maxy:
            return {
                "status": "invalid_request",
                "error": (
                    f"Bounding box is inverted or empty: need minx<maxx and "
                    f"miny<maxy, got minx={minx}, maxx={maxx}, miny={miny}, "
                    f"maxy={maxy}."
                ),
            }
    else:
        if lat is None or lon is None:
            return {
                "status": "invalid_request",
                "error": "A point needs both lat and lon (radius_km is optional).",
            }
        if radius_km is not None and not (1 <= radius_km <= 100):
            return {
                "status": "invalid_request",
                "error": f"radius_km must be between 1 and 100, got {radius_km}.",
            }

    return None


def _run_search(
    client: Any,
    satellite: str,
    start_date: str,
    end_date: str,
    *,
    minx: float | None = None,
    maxx: float | None = None,
    miny: float | None = None,
    maxy: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_km: float | None = None,
    sensor: str | None = None,
    product: str | None = None,
    save: bool = False,
    name: str | None = None,
    description: str | None = None,
) -> tuple[dict[str, Any] | None, Any, list[Any]]:
    """Resolve the satellite and run a search, stateless or saved.

    Returns ``(error, query, selections)``: on any problem ``error`` is the
    ready-to-return result dict and ``query`` is None; on success ``error`` is
    None and ``query`` is the SDK's ``QuerySchema`` (carrying ``.scenes`` and,
    when ``save=True``, a persistent ``.slug``). Shared by ``search_scenes``,
    ``preview_download``, and ``save_query`` so all three resolve the satellite,
    validate the area, and map portal errors identically. ``save`` /``name``
    /``description`` are forwarded to the SDK only when persisting a query.
    """
    aoi_error = _validate_args(
        satellite, minx, maxx, miny, maxy, lat, lon, radius_km
    )
    if aoi_error is not None:
        return (aoi_error, None, [])

    vocab = _get_vocab(client)
    resolution = resolve_satellite(satellite, vocab, threshold=FUZZY_THRESHOLD)
    if not resolution.is_confident:
        return (
            {
                "status": "ambiguous_satellite",
                "query": satellite,
                "candidates": resolution.candidates,
            },
            None,
            [],
        )

    selections = resolution.selections
    if sensor:
        for selection in selections:
            selection.sensor = sensor
    if product:
        for selection in selections:
            selection.product = product

    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError as exc:
        return (
            {
                "status": "invalid_request",
                "error": f"Invalid date — use YYYY-MM-DD. ({exc})",
            },
            None,
            [],
        )
    if end < start:
        return (
            {
                "status": "invalid_request",
                "error": (
                    f"end_date ({end_date}) is before start_date ({start_date}). "
                    "Give the range in chronological order."
                ),
            },
            None,
            [],
        )

    try:
        with sdk_console_to_stderr():
            query = client.query.create(
                start,
                end,
                selections=selections,
                minx=minx,
                maxx=maxx,
                miny=miny,
                maxy=maxy,
                lat=lat,
                lon=lon,
                radius_km=radius_km,
                name=name,
                description=description,
                save=save,
            )
    except BhoonidhiValidationError as exc:
        # The satellite resolved, but the portal rejected every selection —
        # typically the mission carries no data in this date range or area.
        # Report it as an empty, actionable result rather than a raw error.
        return (
            {
                "status": "no_searchable_scenes",
                "matched_satellites": [s.satellite for s in selections],
                "reason": str(exc),
                "total": 0,
                "scenes": [],
            },
            None,
            [],
        )
    except BhoonidhiError as exc:
        return ({"status": "error", "error": str(exc)}, None, [])

    return (None, query, selections)


def _availability_summary(scenes: list[dict[str, Any]]) -> dict[str, int]:
    """Count scenes by availability label across the full result set."""
    summary: dict[str, int] = {}
    for scene in scenes:
        label = scene_availability(scene).label
        summary[label] = summary.get(label, 0) + 1
    return summary


# Plain-English gloss for each availability state, so the agent can tell the
# user what a count means instead of leaving them to decode a label.
_STATE_PHRASE = {
    "Ready": "{n} ready to download now",
    "Archived": "{n} archived (open data, but may need a request on the portal first)",
    "OnOrder": "{n} on-order (must be requested on the portal before download)",
    "Priced": "{n} priced (requires purchase on the portal)",
}
_STATE_ORDER = ("Ready", "Archived", "OnOrder", "Priced")


def _plain_summary(counts: dict[str, int]) -> str:
    """One-sentence, plain-language read of the availability counts."""
    parts = [_STATE_PHRASE[k].format(n=counts[k]) for k in _STATE_ORDER if counts.get(k)]
    return "; ".join(parts) + "." if parts else "No scenes matched."


def _how_to_act(counts: dict[str, int]) -> dict[str, Any]:
    """What the user can do with these scenes, and which tool does it.

    The server can now persist a search (``save_query`` returns a slug) and act
    on that slug in-server: ``download_query`` for open data, ``cart_add`` for
    on-order/priced scenes. This block routes each availability state to the
    right next tool.
    """
    then: list[dict[str, str]] = []
    if counts.get("Ready") or counts.get("Archived"):
        then.append(
            {
                "for": "Ready / Archived (open data)",
                "do": "save_query, then download_query on the slug",
                "note": (
                    "Downloads run in the background — poll download_status. "
                    "Interrupted downloads restart from scratch; the portal has "
                    "no HTTP range support, so partial files cannot be resumed."
                ),
            }
        )
    if counts.get("OnOrder"):
        then.append(
            {
                "for": "OnOrder",
                "do": "save_query, then cart_add to request them on the portal",
            }
        )
    if counts.get("Priced"):
        then.append(
            {
                "for": "Priced",
                "do": "save_query, then cart_add; purchase on the Bhoonidhi portal",
            }
        )
    return {
        "mcp_status": (
            "Call save_query to persist this search and get a <slug>, then act on "
            "it in-server: download_query for open data, cart_add for on-order or "
            "priced scenes. Downloads and cart need a login — check auth_status."
        ),
        "save_first": (
            "save_query with the same arguments returns a <slug> that "
            "download_query and cart_add take."
        ),
        "then": then,
    }


# Plain-English gloss for each preview status, so the agent can explain what a
# dry-run outcome means without decoding the raw token.
_PREVIEW_PHRASE = {
    "would_download": "staged and ready — would download",
    "may_404": "open data but archived — attempted, but may 404 until requested on the portal",
    "already_here": "already present at the destination — skipped",
    "already_elsewhere": "already downloaded to another location — skipped",
    "skipped_on_order": "on-order — skipped, must be requested on the portal first",
    "skipped_priced": "priced — skipped, must be purchased on the portal",
}


def _preview_summary(total: int, ready: int, archived: int, out_dir: str) -> str:
    """One-sentence read of a download preview, honest about archived scenes."""
    if not total:
        return "No scenes matched, so nothing would be downloaded."
    skipped = total - ready - archived
    parts = [f"{ready} ready to download now"]
    if archived:
        parts.append(f"{archived} archived (attempted, but may 404 until requested)")
    if skipped:
        parts.append(f"{skipped} skipped (already present, or need a portal request/purchase)")
    return f"Into {out_dir}: " + "; ".join(parts) + "."


def preview_download(
    client: Any,
    satellite: str,
    start_date: str,
    end_date: str,
    *,
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
) -> dict[str, Any]:
    """Dry-run a download: classify what downloading these scenes would do.

    Runs the same stateless search as ``search_scenes``, then predicts, per
    scene, what a real download into ``out_dir`` would do — without fetching
    anything or needing a login. No file size is available ahead of time (the
    portal exposes it only once a download starts), so this reports what and
    where, not how big.
    """
    error, query, selections = _run_search(
        client, satellite, start_date, end_date,
        minx=minx, maxx=maxx, miny=miny, maxy=maxy,
        lat=lat, lon=lon, radius_km=radius_km, sensor=sensor, product=product,
    )
    if error is not None:
        return error

    scenes = query.scenes if query else []
    previews = _sdk_preview(scenes, out_dir, force=force)
    items = [
        {
            "id": p.scene_id,
            "status": p.status,
            "meaning": _PREVIEW_PHRASE.get(p.status, p.status),
            "filename": p.filename,
            "out_path": p.out_path,
            **({"note": p.note} if p.note else {}),
        }
        for p in previews
    ]

    status_counts: dict[str, int] = {}
    for item in items:
        status_counts[item["status"]] = status_counts.get(item["status"], 0) + 1
    ready = status_counts.get("would_download", 0)
    archived = status_counts.get("may_404", 0)

    return {
        "status": "ok",
        "matched_satellites": [s.satellite for s in selections],
        "total": len(items),
        "out_dir": out_dir,
        "status_counts": status_counts,
        "summary": _preview_summary(len(items), ready, archived, out_dir),
        "disclaimers": [
            "This is a dry run — nothing was downloaded and no login was used.",
            (
                "File sizes are unknown until a download starts; the portal "
                "exposes them only in the download response headers."
            ),
            (
                "Interrupted downloads restart from scratch — the portal has no "
                "HTTP range support, so partial files cannot be resumed."
            ),
        ],
        "scenes": items,
    }


# --- saved queries (stateful, no auth) -------------------------------------


def _shape_selection(sel: Any) -> dict[str, Any]:
    """A saved query's Selection as plain JSON: satellite plus any narrowing."""
    shaped: dict[str, Any] = {"satellite": sel.satellite}
    if getattr(sel, "sensor", None):
        shaped["sensor"] = sel.sensor
    if getattr(sel, "product", None):
        shaped["product"] = sel.product
    return shaped


def _shape_aoi(aoi: Any) -> dict[str, Any]:
    """A saved query's area of interest as the same shape search_scenes takes.

    A ``bbox`` AOI returns minx/miny/maxx/maxy; a ``location`` AOI returns the
    point and radius. Either can be handed straight back to search_scenes.
    """
    if aoi.mode == "location":
        return {
            "type": "point",
            "lat": aoi.lat,
            "lon": aoi.lon,
            "radius_km": aoi.radius_km,
        }
    return {
        "type": "bbox",
        "minx": aoi.min_lon,
        "miny": aoi.min_lat,
        "maxx": aoi.max_lon,
        "maxy": aoi.max_lat,
    }


def _shape_query_summary(query: Any) -> dict[str, Any]:
    """A saved query without its scene list — for listing many at a glance."""
    scenes = query.scenes or []
    counts = _availability_summary(scenes)
    return {
        "slug": query.slug,
        "name": query.name,
        "description": query.description or None,
        "created_at": query.created_at.isoformat(),
        "start_date": query.start_date.date().isoformat(),
        "end_date": query.end_date.date().isoformat(),
        "satellites": [s.satellite for s in query.selections],
        "aoi": _shape_aoi(query.aoi),
        "total": len(scenes),
        "availability_summary": counts,
        "summary": _plain_summary(counts),
    }


def _shape_query_detail(query: Any, max_results: int = MAX_RESULTS) -> dict[str, Any]:
    """A saved query with its shaped scenes — the full record for one slug."""
    scenes = query.scenes or []
    detail = _shape_query_summary(query)
    detail["selections"] = [_shape_selection(s) for s in query.selections]
    detail["returned"] = min(len(scenes), max_results)
    detail["scenes"] = [_shape_scene(s) for s in scenes[:max_results]]
    return detail


def save_query(
    client: Any,
    satellite: str,
    start_date: str,
    end_date: str,
    *,
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
) -> dict[str, Any]:
    """Persist a search as a saved query and return its slug.

    Runs the same resolution, validation, and search as ``search_scenes``, but
    with ``save=True`` so the portal assigns a persistent slug. That slug is
    what later download and cart steps act on. Validation and ambiguity errors
    are reported exactly as ``search_scenes`` reports them.
    """
    error, query, _ = _run_search(
        client, satellite, start_date, end_date,
        minx=minx, maxx=maxx, miny=miny, maxy=maxy,
        lat=lat, lon=lon, radius_km=radius_km, sensor=sensor, product=product,
        save=True, name=name, description=description,
    )
    if error is not None:
        return error

    detail = _shape_query_detail(query)
    return {
        "status": "ok",
        "slug": query.slug,
        "message": (
            f"Saved as '{query.slug}' with {detail['total']} scene(s). "
            "Use this slug with the bhd CLI to download or stage to cart "
            "('bhd auth login' first); in-server download and cart are planned."
        ),
        "query": detail,
    }


def list_queries(client: Any) -> dict[str, Any]:
    """List every saved query as compact summaries (no scene lists)."""
    with sdk_console_to_stderr():
        queries = client.query.list()
    return {
        "status": "ok",
        "total": len(queries),
        "queries": [_shape_query_summary(q) for q in queries],
    }


def show_query(client: Any, slug: str) -> dict[str, Any]:
    """Return one saved query by slug, with its shaped scenes."""
    try:
        with sdk_console_to_stderr():
            query = client.query.show(slug)
    except BhoonidhiNotFoundError:
        return {
            "status": "not_found",
            "slug": slug,
            "error": f"No saved query with slug '{slug}'. Call list_queries to see saved slugs.",
        }
    return {"status": "ok", "query": _shape_query_detail(query)}


def remove_query(client: Any, slug: str) -> dict[str, Any]:
    """Delete a saved query by slug."""
    try:
        with sdk_console_to_stderr():
            client.query.rm(slug)
    except BhoonidhiNotFoundError:
        return {
            "status": "not_found",
            "slug": slug,
            "error": f"No saved query with slug '{slug}'. Call list_queries to see saved slugs.",
        }
    return {"status": "ok", "slug": slug, "message": f"Deleted saved query '{slug}'."}


# --- authentication (read-only, never handles a secret) --------------------


_NOT_AUTHENTICATED = {
    "status": "not_authenticated",
    "hint": (
        "No usable Bhoonidhi session. Log in out of band with 'bhd auth login' "
        "(or set BHOONIDHI_USERNAME / BHOONIDHI_PASSWORD in the server's "
        "environment), then retry."
    ),
}


def _ensure_authenticated(client: Any) -> dict[str, Any] | None:
    """Confirm a usable session, establishing one from the environment if needed.

    Tries three sources in order: a session already held, a lapsed token renewed
    without a password, and finally a headless login from BHOONIDHI_USERNAME /
    BHOONIDHI_PASSWORD in the environment. Returns None when the client can act,
    or the clean not-authenticated result when it cannot. Never raises, and reads
    credentials only from the environment — never from a tool argument.
    """
    try:
        with sdk_console_to_stderr():
            if client.is_authenticated:
                return None
            # A session may exist on disk but its token expired — renew without
            # a password before giving up.
            if client.refresh() is not None:
                return None
            # No usable session: a headless deployment can supply credentials in
            # the environment, so log in with those rather than requiring an
            # interactive 'bhd auth login' first.
            username = os.environ.get("BHOONIDHI_USERNAME")
            password = os.environ.get("BHOONIDHI_PASSWORD")
            if username and password:
                client.login(username, password)
                if client.is_authenticated:
                    return None
    except BhoonidhiAuthError:
        pass
    return dict(_NOT_AUTHENTICATED)


def auth_status(client: Any) -> dict[str, Any]:
    """Report whether a usable Bhoonidhi session is configured.

    Establishes a session if one can be — from a held login, a renewed token, or
    BHOONIDHI_USERNAME / BHOONIDHI_PASSWORD in the environment — so the report
    matches what a download or cart action would actually find. Never returns the
    token or password. A username with a lapsed token reports authenticated=False
    so the agent tells the user to log in again.
    """
    _ensure_authenticated(client)
    try:
        with sdk_console_to_stderr():
            username = client.whoami()
            authenticated = bool(client.is_authenticated)
    except BhoonidhiAuthError:
        username, authenticated = None, False

    if authenticated:
        return {
            "status": "ok",
            "authenticated": True,
            "username": username,
            "message": f"Logged in as {username}. Downloads and cart actions are available.",
        }
    return {
        "status": "ok",
        "authenticated": False,
        "username": username,  # may be a known username with a lapsed token
        "message": _NOT_AUTHENTICATED["hint"],
    }


# --- downloads (authenticated, background job + poll) ----------------------

# A download that will move more than this many megabytes is one to hand off,
# not babysit. Size is unknown up front (the portal only sends Content-Length
# once a transfer starts), so this gate is applied to the live byte totals in a
# status snapshot, not at kick-off.
LARGE_DOWNLOAD_MB = int(os.environ.get("BHOONIDHI_MCP_LARGE_DOWNLOAD_MB", "500"))
# Longest a single download_wait call may block, so it can never wedge a worker
# thread. A watcher loops several bounded waits rather than one unbounded one.
_MAX_WAIT_S = 120.0


def _standalone_hint(slug: str, out_dir: str) -> str:
    return (
        f"Run it as a standalone command you own: 'bhd query download {slug} "
        f"--out {out_dir}' (append ' &' or use nohup to detach). It survives "
        "independently of this session, which an in-server job does not."
    )


_HANDOFF_HINT = (
    "This download runs on its own in the background — it does NOT depend on the "
    "conversation, so do not block by sleeping and re-polling. To stay informed "
    "without tying up the chat, hand off: delegate a background watcher that "
    "loops download_wait on this job_id and reports back when it finishes (or at "
    "intervals), leaving you free to keep talking. Ask for a one-off check any "
    "time with download_status. For a very large or long fetch, prefer a "
    "standalone command instead (see large_download)."
)


def download_query(
    client: Any,
    slug: str,
    *,
    select: list[int | str] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Start a background download of a saved query into the allow-listed root.

    Confines output to ``<BHOONIDHI_MCP_DOWNLOAD_ROOT>/<slug>/`` — the path is
    computed from the configured root and the slug, never taken from the caller.
    Returns immediately with a ``job_id``; the download proceeds on its own
    thread. Needs a session; returns the not-authenticated result when none is
    held.
    """
    auth_error = _ensure_authenticated(client)
    if auth_error is not None:
        return auth_error

    try:
        with sdk_console_to_stderr():
            query = client.query.show(slug)
    except BhoonidhiNotFoundError:
        return {
            "status": "not_found",
            "slug": slug,
            "error": f"No saved query with slug '{slug}'. Call list_queries to see saved slugs.",
        }

    out_dir = str(_download_root() / slug)
    downloadable = sum(
        1 for s in (query.scenes or []) if scene_availability(s).is_downloadable
    )
    job = jobs.register(slug, out_dir, total_scenes=downloadable)

    def _work(on_progress: Any) -> list[Any]:
        with sdk_console_to_stderr():
            return client.query.download(
                slug,
                out_dir,
                select=select,
                parallel=DOWNLOAD_PARALLEL,
                force=force,
                on_progress=on_progress,
            )

    jobs.run(job, _work)

    return {
        "status": "started",
        "job_id": job.job_id,
        "slug": slug,
        "out_dir": out_dir,
        "downloadable_scenes": downloadable,
        "message": (
            f"Download of {downloadable} scene(s) started into {out_dir}. "
            "Interrupted downloads restart from scratch — the portal has no "
            "resume support. File sizes are unknown until each transfer begins."
        ),
        "handoff": _HANDOFF_HINT,
        "large_download": _standalone_hint(slug, out_dir),
    }


def _augment_status(snap: dict[str, Any]) -> dict[str, Any]:
    """Add size-aware guidance to a live snapshot once bytes are known.

    The scene-count guess at kick-off can't see that three NISAR scenes are
    gigabytes; the byte totals here can. When the download has moved (or is
    expected to move) past the large-download threshold, tell the agent to hand
    off to a watcher rather than block the conversation.
    """
    if snap["status"] in ("completed", "failed"):
        return snap
    expected = snap.get("bytes_expected")
    downloaded = snap.get("bytes_downloaded", 0)
    threshold = LARGE_DOWNLOAD_MB * 1_000_000
    is_large = (expected is not None and expected > threshold) or downloaded > threshold
    if is_large:
        snap["large_download"] = True
        snap["handoff"] = _HANDOFF_HINT
    return snap


def download_status(job_id: str) -> dict[str, Any]:
    """Report a background download job's progress and outcome.

    Give the ``job_id`` from ``download_query``. Returns the live state with
    byte totals and a transfer rate: running (bytes_downloaded, mb_downloaded,
    rate_mb_s, percent when total size is known, and per-scene detail),
    completed (with per-scene outcomes), or failed (with the error). A single
    call — use it for a one-off check; to follow a job to completion without
    blocking the conversation, hand off a watcher that loops download_wait.
    Jobs live only for the server process's lifetime; an unknown id reports
    not_found.
    """
    job = jobs.get(job_id)
    if job is None:
        return {
            "status": "not_found",
            "job_id": job_id,
            "error": (
                "No download job with that id. It may have been lost when the "
                "server restarted — start a new download with download_query."
            ),
        }
    return _augment_status(job.snapshot())


def download_wait(job_id: str, timeout_s: float = 60.0) -> dict[str, Any]:
    """Block until a download finishes or ``timeout_s`` elapses, then report.

    The efficient way for a background watcher to follow a job: instead of
    sleeping and re-polling, this waits inside the server and returns the moment
    the job completes or fails — or after ``timeout_s`` with the latest progress
    if it is still running. ``timeout_s`` is capped so it never wedges the
    server; a watcher that wants to follow a long download calls this in a loop,
    checking status between calls, and stops when status is completed or failed.
    An unknown id reports not_found.
    """
    job = jobs.get(job_id)
    if job is None:
        return {
            "status": "not_found",
            "job_id": job_id,
            "error": (
                "No download job with that id. It may have been lost when the "
                "server restarted — start a new download with download_query."
            ),
        }
    capped = max(0.0, min(float(timeout_s), _MAX_WAIT_S))
    return _augment_status(job.wait(capped))


# --- cart (authenticated) --------------------------------------------------


_CART_KIND_LABEL = {
    "DIRECT": "ready",
    "ORDER": "on-order",
    "PRICED": "priced",
}


def _cart_kind_label(kind: Any) -> str:
    """A CartKind enum (or its name) as a plain lowercase label."""
    name = getattr(kind, "name", str(kind))
    return _CART_KIND_LABEL.get(name, name.lower())


def cart_add(
    client: Any, slug: str, *, select: list[int | str] | None = None
) -> dict[str, Any]:
    """Stage a saved query's scenes to the Bhoonidhi cart.

    Routes each scene to the cart its access type selects (ready / on-order /
    priced). Needs a session. Returns counts of what was staged and what failed.
    """
    auth_error = _ensure_authenticated(client)
    if auth_error is not None:
        return auth_error

    try:
        with sdk_console_to_stderr():
            added, failed, _srt = client.cart.add(slug, select=select)
    except BhoonidhiNotFoundError:
        return {
            "status": "not_found",
            "slug": slug,
            "error": f"No saved query with slug '{slug}'. Call list_queries to see saved slugs.",
        }
    except (BhoonidhiAPIError, BhoonidhiError) as exc:
        return {"status": "error", "error": str(exc)}

    staged = [
        {"id": scene.get("ID") or scene.get("id"), "cart": _cart_kind_label(kind)}
        for scene, kind in added
    ]
    not_staged = [
        {"id": scene.get("ID") or scene.get("id"), "reason": reason}
        for scene, reason in failed
    ]
    return {
        "status": "ok",
        "slug": slug,
        "added": len(staged),
        "failed": len(not_staged),
        "staged": staged,
        "not_staged": not_staged,
        "message": (
            f"Staged {len(staged)} scene(s) to the cart"
            + (f", {len(not_staged)} failed" if not_staged else "")
            + ". Priced scenes still need purchasing on the Bhoonidhi portal."
        ),
    }


def _parse_optional_date(label: str, value: str | None) -> tuple[datetime | None, dict | None]:
    """Parse an optional ISO date string, returning an error dict on failure."""
    if value is None:
        return None, None
    try:
        return datetime.fromisoformat(value), None
    except ValueError as exc:
        return None, {
            "status": "invalid_request",
            "error": f"Invalid {label} — use YYYY-MM-DD. ({exc})",
        }


def cart_list(
    client: Any,
    *,
    filter_by: str | list[str] | None = None,
    since: str | None = None,
    until: str | None = None,
    last: str | None = None,
) -> dict[str, Any]:
    """List scenes currently staged in the cart, across all three carts.

    Cart items are filed by add-date; with no window this shows today only, so
    widen it with ``since``/``until`` (ISO dates) or ``last`` (e.g. "1 week").
    ``filter_by`` limits to states: ready, archived, onorder, priced. Needs a
    session.
    """
    auth_error = _ensure_authenticated(client)
    if auth_error is not None:
        return auth_error

    since_dt, error = _parse_optional_date("since", since)
    if error is not None:
        return error
    until_dt, error = _parse_optional_date("until", until)
    if error is not None:
        return error

    try:
        with sdk_console_to_stderr():
            items = client.cart.list(
                since=since_dt, until=until_dt, filter_by=filter_by, last=last
            )
    except (BhoonidhiAPIError, BhoonidhiError) as exc:
        return {"status": "error", "error": str(exc)}

    shaped = [
        {
            "id": item.get("ID") or item.get("id"),
            "satellite": item.get("SATELLITE"),
            "sensor": item.get("SENSOR"),
            "date_of_pass": item.get("DOP"),
        }
        for item in items
    ]
    return {"status": "ok", "total": len(shaped), "items": shaped}


def cart_remove(
    client: Any,
    *,
    slug: str | None = None,
    select: list[int | str] | None = None,
    since: str | None = None,
    until: str | None = None,
    last: str | None = None,
    filter_by: str | list[str] | None = None,
) -> dict[str, Any]:
    """Remove scenes from the cart.

    Address rows two ways: pass ``slug`` to index a saved query's scenes, or
    omit it and let ``select`` index the merged cart itself (same numbers
    cart_list shows under the same ``since``/``until``/``last``/``filter_by``
    window). Needs a session.
    """
    auth_error = _ensure_authenticated(client)
    if auth_error is not None:
        return auth_error

    since_dt, error = _parse_optional_date("since", since)
    if error is not None:
        return error
    until_dt, error = _parse_optional_date("until", until)
    if error is not None:
        return error

    try:
        with sdk_console_to_stderr():
            removed, failed = client.cart.rm(
                slug=slug,
                select=select,
                since=since_dt,
                until=until_dt,
                last=last,
                filter_by=filter_by,
            )
    except BhoonidhiNotFoundError:
        return {
            "status": "not_found",
            "slug": slug,
            "error": f"No saved query with slug '{slug}'. Call list_queries to see saved slugs.",
        }
    except (BhoonidhiAPIError, BhoonidhiError) as exc:
        return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "removed": len(removed),
        "failed": len(failed),
        "removed_ids": [scene_id for scene_id, _kind in removed],
        "not_removed": [{"id": sid, "reason": reason} for sid, reason in failed],
        "message": f"Removed {len(removed)} scene(s) from the cart"
        + (f", {len(failed)} failed." if failed else "."),
    }
