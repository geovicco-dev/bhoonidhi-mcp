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

from bhoonidhi_downloader.exceptions import BhoonidhiError
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
    vocab = _get_vocab(client)
    resolution = resolve_satellite(satellite, vocab, threshold=FUZZY_THRESHOLD)
    if not resolution.is_confident:
        return {
            "status": "ambiguous_satellite",
            "query": satellite,
            "candidates": resolution.candidates,
        }

    selections = resolution.selections
    if sensor:
        for selection in selections:
            selection.sensor = sensor

    try:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
    except ValueError as exc:
        return {"status": "error", "error": f"Invalid date (use YYYY-MM-DD): {exc}"}

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
    except BhoonidhiError as exc:
        return {"status": "error", "error": str(exc)}

    scenes = query.scenes if query else []
    shaped = [_shape_scene(s) for s in scenes[:max_results]]
    return {
        "status": "ok",
        "matched_satellites": [s.satellite for s in selections],
        "total": len(scenes),
        "returned": len(shaped),
        # Counts over ALL matched scenes (not just the returned page), so the
        # agent can answer "how many can I actually download?" honestly.
        "availability_summary": _availability_summary(scenes),
        "scenes": shaped,
    }


def _availability_summary(scenes: list[dict[str, Any]]) -> dict[str, int]:
    """Count scenes by availability label across the full result set."""
    summary: dict[str, int] = {}
    for scene in scenes:
        label = scene_availability(scene).label
        summary[label] = summary.get(label, 0) + 1
    return summary
