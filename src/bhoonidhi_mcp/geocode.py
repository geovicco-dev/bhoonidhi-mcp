"""Turn a place name into coordinates and a bounding box.

An agent says "over Shillong"; the portal needs numbers. This resolves place
names to a centroid and an area of interest using geopy over OpenStreetMap's
Nominatim, so location lookup is deterministic rather than left to model memory.

The result exposes both AOI shapes ``search_scenes`` can pass to the downloader:
a bounding box for an area, or a point for "within N km of here". Coordinates
are authoritative; the returned name is advisory, since Nominatim may answer in
the local script (e.g. Bengali for a place in West Bengal).

Nominatim ranks matches by an importance score, which prefers well-known places
(so "Tokyo" resolves to Tokyo and "Hyderabad" to the larger Indian one). Inputs
that are not place names — empty strings, bare numbers, or raw coordinates — are
rejected rather than fuzzy-matched to an unrelated place: if the caller already
has coordinates they should pass them to the search AOI directly.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

# Nominatim's public endpoint asks for a descriptive User-Agent and at most one
# request per second. Both are enforced here; the UA is overridable by env.
_DEFAULT_USER_AGENT = os.environ.get(
    "BHOONIDHI_MCP_GEOCODER_USER_AGENT", "bhoonidhi-mcp/0.3"
)
_MIN_DELAY_SECONDS = 1.1

# A place name must contain at least one letter. Bare numbers ("12345") and
# coordinate-like strings ("25.5, 91.9") are not names — geocoding them returns
# an unrelated place, so they are rejected before the network call.
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_COORD_LIKE = re.compile(r"^\s*[-+]?\d+(\.\d+)?\s*[,;/ ]\s*[-+]?\d+(\.\d+)?\s*$")


@dataclass
class Place:
    """A resolved location, ready to feed a search.

    ``bbox`` is ``(minx, miny, maxx, maxy)`` in degrees, matching the
    downloader's bounding-box parameters directly. ``lat``/``lon`` give the
    centroid for a point+radius search instead.
    """

    name: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]


class _Geocoder(Protocol):
    """The one geopy call this module needs — narrowed for easy testing."""

    def __call__(self, query: str, **kwargs: object) -> object | None: ...


def _build_geocoder(user_agent: str) -> _Geocoder:
    nominatim = Nominatim(user_agent=user_agent)
    return RateLimiter(nominatim.geocode, min_delay_seconds=_MIN_DELAY_SECONDS)


def is_place_name(name: str) -> bool:
    """True if ``name`` is worth geocoding — has letters and isn't coordinates."""
    if not name or not name.strip():
        return False
    if _COORD_LIKE.match(name):
        return False
    return bool(_HAS_LETTER.search(name))


def resolve_location(
    name: str,
    *,
    geocoder: _Geocoder | None = None,
) -> Place | None:
    """Resolve a place name to a :class:`Place`, or ``None`` if nothing matches.

    Returns ``None`` for inputs that are not place names (empty, bare numbers,
    raw coordinates) without a network call. Otherwise queries Nominatim, whose
    importance ranking prefers well-known places. ``geocoder`` is injectable so
    tests run without hitting the network; production builds one over Nominatim.
    """
    if not is_place_name(name):
        return None

    geocode = geocoder or _build_geocoder(_DEFAULT_USER_AGENT)
    location = geocode(name, addressdetails=False)
    if location is None:
        return None

    south, north, west, east = (float(v) for v in location.raw["boundingbox"])
    return Place(
        name=location.address,
        lat=location.latitude,
        lon=location.longitude,
        bbox=(west, south, east, north),
    )
