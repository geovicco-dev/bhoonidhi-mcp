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
from typing import Any

from bhoonidhi_downloader.exceptions import BhoonidhiError, BhoonidhiValidationError
from bhoonidhi_downloader.sdk import preview_download as _sdk_preview
from bhoonidhi_downloader.sdk import scene_availability

from .geocode import resolve_location as _resolve_place
from .matching import Vocabulary, resolve_satellite
from .protocol_safety import sdk_console_to_stderr

FUZZY_THRESHOLD = int(os.environ.get("BHOONIDHI_MCP_FUZZY_THRESHOLD", "88"))
MAX_RESULTS = int(os.environ.get("BHOONIDHI_MCP_MAX_RESULTS", "50"))

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


def resolve_location(name: str, *, country_bias: str | None = "in") -> dict[str, Any]:
    """Resolve a place name to a centroid and bounding box."""
    place = _resolve_place(name, country_bias=country_bias)
    if place is None:
        return {"found": False, "query": name}
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
    max_results: int = MAX_RESULTS,
) -> dict[str, Any]:
    """Search scenes for a satellite over an area and date range (stateless).

    The satellite name is fuzzy-resolved to exact portal tokens first; if the
    name is ambiguous, candidates are returned instead of a guessed search. Give
    an area either as a bounding box (minx/maxx/miny/maxy) or a point plus radius
    (lat/lon/radius_km).
    """
    error, scenes, selections = _run_search(
        client, satellite, start_date, end_date,
        minx=minx, maxx=maxx, miny=miny, maxy=maxy,
        lat=lat, lon=lon, radius_km=radius_km, sensor=sensor,
    )
    if error is not None:
        return error

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
        create_cmd = _bhd_create_command(
            start_date, end_date, selections,
            minx, maxx, miny, maxy, lat, lon, radius_km,
        )
        result["how_to_act"] = _how_to_act(counts, create_cmd)
    return result


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
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[Any]]:
    """Resolve the satellite and run a stateless search.

    Returns ``(error, scenes, selections)``: on any problem ``error`` is the
    ready-to-return result dict and the other two are empty; on success
    ``error`` is None. Shared by ``search_scenes`` and ``preview_download`` so
    both classify the same scenes with identical resolution and error handling.
    """
    vocab = _get_vocab(client)
    resolution = resolve_satellite(satellite, vocab, threshold=FUZZY_THRESHOLD)
    if not resolution.is_confident:
        return (
            {
                "status": "ambiguous_satellite",
                "query": satellite,
                "candidates": resolution.candidates,
            },
            [],
            [],
        )

    selections = resolution.selections
    if sensor:
        for selection in selections:
            selection.sensor = sensor

    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError as exc:
        return ({"status": "error", "error": f"Invalid date (use YYYY-MM-DD): {exc}"}, [], [])

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
                save=False,
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
            [],
            [],
        )
    except BhoonidhiError as exc:
        return ({"status": "error", "error": str(exc)}, [], [])

    scenes = query.scenes if query else []
    return (None, scenes, selections)


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


def _bhd_create_command(
    start: str,
    end: str,
    selections: list[Any],
    minx: float | None,
    maxx: float | None,
    miny: float | None,
    maxy: float | None,
    lat: float | None,
    lon: float | None,
    radius_km: float | None,
) -> str:
    """Reconstruct the `bhd query create` that reproduces this search and saves it.

    The MCP search is stateless (no slug), but acting via the CLI needs one, so
    the user re-runs this saving form first. Flags mirror the verified CLI.
    """
    sats = []
    for sel in selections:
        token = sel.satellite
        if getattr(sel, "sensor", None):
            token = f"{sel.satellite}:{sel.sensor}"
        sats.append(f'--sat "{token}"')
    if minx is not None:
        aoi = f"--minx {minx} --maxx {maxx} --miny {miny} --maxy {maxy}"
    else:
        aoi = f"--lat {lat} --lon {lon} --radius {radius_km}"
    return f"bhd query create {start} {end} " + " ".join(sats) + " " + aoi


def _how_to_act(counts: dict[str, int], create_cmd: str) -> dict[str, Any]:
    """What the user can do with these scenes today, and what's coming.

    This server is read-only for now, so acting (download, cart) is done with
    the bhd CLI. Each step is spelled out with the exact command; downloading
    and cart staging are planned MCP features noted here so the agent can say so.
    """
    then: list[dict[str, str]] = []
    if counts.get("Ready") or counts.get("Archived"):
        then.append(
            {
                "for": "Ready / Archived (open data)",
                "do": "download them yourself",
                "command": "bhd query download <slug> --out ./downloads",
                "note": (
                    "Interrupted downloads restart from scratch — the portal has "
                    "no HTTP range support, so partial files cannot be resumed."
                ),
            }
        )
    if counts.get("OnOrder"):
        then.append(
            {
                "for": "OnOrder",
                "do": "request them on the portal, then download once ready",
                "command": "bhd cart add <slug> --filter onorder",
            }
        )
    if counts.get("Priced"):
        then.append(
            {
                "for": "Priced",
                "do": "stage to cart, then purchase on the Bhoonidhi portal",
                "command": "bhd cart add <slug> --filter priced",
            }
        )
    return {
        "mcp_status": (
            "This server is read-only for now; downloading scenes and staging "
            "priced/on-order scenes to your cart are planned for a future update. "
            "Until then, act with the bhd CLI — log in first with 'bhd auth login'."
        ),
        "reproduce_search": create_cmd + "   # saves the search and prints a <slug>",
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
    force: bool = False,
) -> dict[str, Any]:
    """Dry-run a download: classify what downloading these scenes would do.

    Runs the same stateless search as ``search_scenes``, then predicts, per
    scene, what a real download into ``out_dir`` would do — without fetching
    anything or needing a login. No file size is available ahead of time (the
    portal exposes it only once a download starts), so this reports what and
    where, not how big.
    """
    error, scenes, selections = _run_search(
        client, satellite, start_date, end_date,
        minx=minx, maxx=maxx, miny=miny, maxy=maxy,
        lat=lat, lon=lon, radius_km=radius_km, sensor=sensor,
    )
    if error is not None:
        return error

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
