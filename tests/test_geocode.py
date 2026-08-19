"""Place-name resolution shapes coordinates and a bbox for search.

Uses a stub geocoder so no live Nominatim call happens in CI. The stub returns a
Nominatim-shaped object (Shillong's real bounding box) so the field mapping is
exercised against realistic data.
"""

from types import SimpleNamespace

from bhoonidhi_mcp.geocode import Place, resolve_location

# Nominatim's boundingbox order is [south, north, west, east] as strings.
_SHILLONG = SimpleNamespace(
    address="Shillong, East Khasi Hills, Meghalaya, India",
    latitude=25.5760,
    longitude=91.8828,
    raw={"boundingbox": ["25.416", "25.736", "91.723", "92.043"]},
)


def _stub(result):
    calls = {}

    def geocode(query, **kwargs):
        calls["query"] = query
        calls["kwargs"] = kwargs
        return result

    geocode.calls = calls
    return geocode


def test_resolves_place_to_centroid_and_bbox():
    place = resolve_location("Shillong", geocoder=_stub(_SHILLONG))
    assert isinstance(place, Place)
    assert (place.lat, place.lon) == (25.5760, 91.8828)
    # bbox is (minx, miny, maxx, maxy) = (west, south, east, north)
    assert place.bbox == (91.723, 25.416, 92.043, 25.736)
    assert "Shillong" in place.name


def test_no_match_returns_none():
    assert resolve_location("asdfqwerzzz", geocoder=_stub(None)) is None


def test_no_country_filter_is_sent():
    # A hard country filter mis-resolved foreign places to tiny Indian ones;
    # the geocoder now relies on Nominatim's importance ranking instead.
    stub = _stub(_SHILLONG)
    resolve_location("Shillong", geocoder=stub)
    assert "country_codes" not in stub.calls["kwargs"]


def test_non_place_inputs_are_rejected_without_a_call():
    # Empty, whitespace, bare numbers, and coordinates are not place names —
    # they must return None without ever hitting the geocoder.
    for bad in ["", "   ", "12345", "25.5, 91.9", "-12.3;45.6"]:
        stub = _stub(_SHILLONG)
        assert resolve_location(bad, geocoder=stub) is None
        assert "query" not in stub.calls  # geocoder never invoked


def test_real_place_names_still_reach_the_geocoder():
    stub = _stub(_SHILLONG)
    assert resolve_location("Shillong", geocoder=stub) is not None
    assert stub.calls["query"] == "Shillong"
