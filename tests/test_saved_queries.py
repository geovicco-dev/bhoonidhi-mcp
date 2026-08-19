"""The saved-query lifecycle (Phase 2a): save, list, show, remove — offline.

A fake client models the portal's saved-query store in memory. ``create`` with
save=True mints a real ``QuerySchema`` so the shaping runs against the actual
SDK schema, not a stand-in.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from bhoonidhi_downloader.exceptions import BhoonidhiNotFoundError
from bhoonidhi_downloader.schemas.aoi import AOISchema
from bhoonidhi_downloader.schemas.query import QuerySchema

import bhoonidhi_mcp.tools as tools_module
from bhoonidhi_mcp.tools import list_queries, remove_query, save_query, show_query

_ARCHIVE = json.loads(
    (Path(__file__).parent / "fixtures" / "archive_sample.json").read_text()
)

_SCENE = {
    "ID": "SEN2A_MSI_zzz_06JAN2024_133_T46RDP",
    "SATELLITE": "SEN2A",
    "SENSOR": "MSI",
    "SELECTION": "Sentinel-2A_MSI_Level-1C",
    "DOP": "06JAN2024",
    "PRICED": "OpenData_DirectDownload",
    "CURR_SCENE_NO": "Y",
    "SCENE_CENTER_LAT": "25.6",
    "SCENE_CENTER_LONG": "91.9",
}


class _FakeArchive:
    def list(self, refresh=False):
        return _ARCHIVE


class _FakeQuery:
    """A saved-query store: create mints a slug, list/show/rm read it back."""

    def __init__(self, scenes):
        self._scenes = scenes
        self._saved: dict[str, QuerySchema] = {}
        self._n = 0

    def create(self, start, end, *, selections=None, save=False, name=None,
               description=None, minx=None, maxx=None, miny=None, maxy=None,
               lat=None, lon=None, radius_km=None):
        if lat is not None:
            aoi = AOISchema(mode="location", min_lon=lat, min_lat=lat,
                            max_lon=lat, max_lat=lat, lat=lat, lon=lon,
                            radius_km=radius_km)
        else:
            aoi = AOISchema(mode="bbox", min_lon=minx, min_lat=miny,
                            max_lon=maxx, max_lat=maxy)
        if not save:
            return QuerySchema(
                slug="", name=name or "", description=description or "",
                created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), selections=selections or [],
                aoi=aoi, start_date=start, end_date=end, scenes=self._scenes,
            )
        self._n += 1
        slug = f"q{self._n}"
        query = QuerySchema(
            slug=slug, name=name or slug, description=description or "",
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc), selections=selections or [],
            aoi=aoi, start_date=start, end_date=end, scenes=self._scenes,
        )
        self._saved[slug] = query
        return query

    def list(self):
        return list(self._saved.values())

    def show(self, slug):
        if slug not in self._saved:
            raise BhoonidhiNotFoundError(f"no such slug {slug}")
        return self._saved[slug]

    def rm(self, slug):
        if slug not in self._saved:
            raise BhoonidhiNotFoundError(f"no such slug {slug}")
        del self._saved[slug]


class _FakeClient:
    def __init__(self, scenes=None):
        self.archive = _FakeArchive()
        self.query = _FakeQuery(scenes or [])


def setup_function():
    tools_module._vocab_cache = None


_BBOX = {"minx": 91.7, "maxx": 92.0, "miny": 25.4, "maxy": 25.7}


def test_save_query_mints_a_slug_and_shapes_the_query():
    client = _FakeClient(scenes=[_SCENE])
    out = save_query(
        client, "Sentinel-2", "2024-01-01", "2024-01-15",
        name="Shillong winter", **_BBOX,
    )
    assert out["status"] == "ok"
    assert out["slug"] == "q1"
    assert "q1" in out["message"]
    q = out["query"]
    assert q["slug"] == "q1"
    assert q["name"] == "Shillong winter"
    assert set(q["satellites"]) == {"Sentinel-2A", "Sentinel-2B", "Sentinel-2C"}
    assert q["aoi"] == {"type": "bbox", "minx": 91.7, "miny": 25.4,
                        "maxx": 92.0, "maxy": 25.7}
    assert q["total"] == 1
    assert q["scenes"][0]["id"] == _SCENE["ID"]
    assert q["scenes"][0]["availability"] == "Ready"


def test_save_query_reuses_search_validation():
    """Ambiguous or invalid input must be rejected before anything is saved."""
    client = _FakeClient()
    amb = save_query(client, "banana", "2024-01-01", "2024-01-15", **_BBOX)
    assert amb["status"] == "ambiguous_satellite"
    assert amb["candidates"]

    bad = save_query(client, "Sentinel-2", "2024-01-31", "2024-01-01", **_BBOX)
    assert bad["status"] == "invalid_request" and "before" in bad["error"].lower()

    # Nothing was persisted by either failed attempt.
    assert list_queries(client)["total"] == 0


def test_list_queries_summarises_without_scene_lists():
    client = _FakeClient(scenes=[_SCENE])
    save_query(client, "Sentinel-2", "2024-01-01", "2024-01-15", **_BBOX)
    save_query(client, "Sentinel-2", "2024-02-01", "2024-02-15", **_BBOX)
    out = list_queries(client)
    assert out["status"] == "ok"
    assert out["total"] == 2
    first = out["queries"][0]
    assert first["slug"] == "q1"
    assert "scenes" not in first  # summaries omit the full scene list
    assert first["total"] == 1
    assert "ready to download now" in first["summary"]


def test_show_query_returns_full_detail_then_not_found_after_remove():
    client = _FakeClient(scenes=[_SCENE])
    save_query(client, "Sentinel-2", "2024-01-01", "2024-01-15", **_BBOX)

    shown = show_query(client, "q1")
    assert shown["status"] == "ok"
    assert shown["query"]["scenes"][0]["id"] == _SCENE["ID"]
    assert shown["query"]["selections"][0]["satellite"] == "Sentinel-2A"

    removed = remove_query(client, "q1")
    assert removed["status"] == "ok" and removed["slug"] == "q1"

    gone = show_query(client, "q1")
    assert gone["status"] == "not_found"
    assert "q1" in gone["error"]


def test_remove_unknown_slug_is_a_clean_not_found():
    out = remove_query(_FakeClient(), "nope")
    assert out["status"] == "not_found"
    assert "nope" in out["error"]


def test_point_aoi_round_trips_as_a_point():
    client = _FakeClient(scenes=[_SCENE])
    out = save_query(
        client, "Sentinel-2", "2024-01-01", "2024-01-15",
        lat=25.6, lon=91.9, radius_km=20,
    )
    assert out["query"]["aoi"] == {
        "type": "point", "lat": 25.6, "lon": 91.9, "radius_km": 20,
    }
