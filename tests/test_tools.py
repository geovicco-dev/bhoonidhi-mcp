"""The tool adapters shape SDK results for agents, without a live portal.

A fake client stands in for BhoonidhiClient so these run offline. It returns a
real archive snapshot and a realistic scene dict, so shaping is exercised
against the actual portal field names.
"""

import json
from pathlib import Path

import bhoonidhi_mcp.tools as tools_module
from bhoonidhi_mcp.tools import list_archive, search_scenes

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
    "SCENE_CENTER_LAT": "25.6",
    "SCENE_CENTER_LONG": "91.9",
}


class _FakeArchive:
    def list(self, refresh=False):
        return _ARCHIVE


class _FakeQuery:
    def __init__(self, scenes):
        self._scenes = scenes

    def create(self, *args, **kwargs):
        from types import SimpleNamespace

        return SimpleNamespace(scenes=self._scenes)


class _FakeClient:
    def __init__(self, scenes=None):
        self.archive = _FakeArchive()
        self.query = _FakeQuery(scenes or [])


def setup_function():
    # The vocabulary is module-cached; clear it so each test starts clean.
    tools_module._vocab_cache = None


def test_list_archive_shapes_records():
    out = list_archive(_FakeClient())
    sats = {s["satellite"] for s in out["satellites"]}
    assert "Sentinel-2A" in sats
    rec = next(s for s in out["satellites"] if s["satellite"] == "Sentinel-2A")
    assert rec["sensors"][0]["sensor"] == "MSI"
    assert rec["sensors"][0]["token"]  # exact search token present


def test_search_expands_constellation_and_shapes_scenes():
    out = search_scenes(
        _FakeClient(scenes=[_SCENE]),
        "Sentinel-2",
        "2024-01-01",
        "2024-01-15",
        minx=91.7,
        maxx=92.0,
        miny=25.4,
        maxy=25.7,
    )
    assert out["status"] == "ok"
    assert set(out["matched_satellites"]) == {"Sentinel-2A", "Sentinel-2B", "Sentinel-2C"}
    assert out["total"] == 1
    scene = out["scenes"][0]
    assert scene["id"] == _SCENE["ID"]
    assert scene["availability"] == "OpenData_DirectDownload"


def test_ambiguous_satellite_returns_candidates_not_search():
    out = search_scenes(
        _FakeClient(), "banana", "2024-01-01", "2024-01-15", minx=0, maxx=1, miny=0, maxy=1
    )
    assert out["status"] == "ambiguous_satellite"
    assert out["candidates"]


def test_bad_date_is_reported_cleanly():
    out = search_scenes(
        _FakeClient(), "Sentinel-2", "01-2024", "2024-01-15", minx=0, maxx=1, miny=0, maxy=1
    )
    assert out["status"] == "error"
    assert "date" in out["error"].lower()
