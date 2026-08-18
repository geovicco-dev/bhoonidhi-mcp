"""Turn a place name into coordinates and a bounding box.

An agent says "over Shillong"; the portal needs numbers. This resolves place
names to a centroid and an area of interest using geopy over OpenStreetMap's
Nominatim, so location lookup is deterministic rather than left to model memory.

The result exposes both AOI shapes ``search_scenes`` can pass to the downloader:
a bounding box for an area, or a point for "within N km of here". Coordinates
are authoritative; the returned name is advisory, since Nominatim may answer in
the local script (e.g. Bengali for a place in West Bengal).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

# Nominatim's public endpoint asks for a descriptive User-Agent and at most one
# request per second. Both are enforced here; the UA is overridable by env.
_DEFAULT_USER_AGENT = os.environ.get(
    "BHOONIDHI_MCP_GEOCODER_USER_AGENT", "bhoonidhi-mcp/0.1"
)
_MIN_DELAY_SECONDS = 1.1


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


def resolve_location(
    name: str,
    *,
    country_bias: str | None = "in",
    geocoder: _Geocoder | None = None,
) -> Place | None:
    """Resolve a place name to a :class:`Place`, or ``None`` if nothing matches.

    ``country_bias`` softly prefers results in one ISO country code (default
    India, the portal's focus) without excluding others — pass ``None`` to drop
    the preference entirely. ``geocoder`` is injectable so tests run without
    hitting the network; production builds one over Nominatim.
    """
    geocode = geocoder or _build_geocoder(_DEFAULT_USER_AGENT)

    kwargs: dict[str, object] = {"addressdetails": False}
    if country_bias:
        # A bias, not a filter: Nominatim ranks these first but still returns
        # matches elsewhere when nothing in-country fits.
        kwargs["country_codes"] = country_bias

    location = geocode(name, **kwargs)
    if location is None:
        return None

    south, north, west, east = (float(v) for v in location.raw["boundingbox"])
    return Place(
        name=location.address,
        lat=location.latitude,
        lon=location.longitude,
        bbox=(west, south, east, north),
    )
