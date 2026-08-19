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
    "CURR_SCENE_NO": "Y",  # staged -> Ready
    "SCENE_CENTER_LAT": "25.6",
    "SCENE_CENTER_LONG": "91.9",
}


def _scene(priced, curr_scene_no=None):
    s = dict(_SCENE, PRICED=priced)
    if curr_scene_no is None:
        s.pop("CURR_SCENE_NO", None)
    else:
        s["CURR_SCENE_NO"] = curr_scene_no
    return s


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
    # Staged open-data scene classifies as Ready and downloadable.
    assert scene["availability"] == "Ready"
    assert scene["downloadable"] is True


def test_availability_reflects_staging_not_just_pricing():
    """The bug this fixes: DirectDownload without staging is Archived, not Ready."""
    ready = _scene("OpenData_DirectDownload", "Y")
    archived = _scene("OpenData_DirectDownload")  # no CURR_SCENE_NO
    priced = _scene("Priced")
    out = search_scenes(
        _FakeClient(scenes=[ready, archived, priced]),
        "Sentinel-2",
        "2024-01-01",
        "2024-01-15",
        minx=91.7,
        maxx=92.0,
        miny=25.4,
        maxy=25.7,
    )
    assert out["availability_summary"] == {"Ready": 1, "Archived": 1, "Priced": 1}
    labels = [s["availability"] for s in out["scenes"]]
    assert labels == ["Ready", "Archived", "Priced"]
    # Both open-data states are downloadable; priced is not.
    assert [s["downloadable"] for s in out["scenes"]] == [True, True, False]
    # Plain-English summary names every non-zero state for the user.
    assert "1 ready to download now" in out["summary"]
    assert "archived" in out["summary"] and "priced" in out["summary"].lower()


def test_result_guides_the_user_on_how_to_act():
    """Read-only server must tell the user what's coming and the exact bhd command."""
    ready = _scene("OpenData_DirectDownload", "Y")
    priced = _scene("Priced")
    out = search_scenes(
        _FakeClient(scenes=[ready, priced]),
        "Sentinel-2",
        "2024-01-01",
        "2024-01-31",
        minx=91.7,
        maxx=92.0,
        miny=25.4,
        maxy=25.7,
    )
    act = out["how_to_act"]
    # The agent is told the boundary and the roadmap.
    assert "read-only" in act["mcp_status"] and "future update" in act["mcp_status"]
    # A correct, reproducible saving command with the real bbox + a slug note.
    cmd = act["reproduce_search"]
    assert cmd.startswith("bhd query create 2024-01-01 2024-01-31")
    assert "--minx 91.7" in cmd and "<slug>" in cmd
    # Priced scenes route to cart; open data routes to download with no-resume note.
    fors = {step["for"]: step for step in act["then"]}
    assert any("Priced" in k for k in fors)
    dl = next(s for s in act["then"] if "open data" in s["for"].lower())
    assert "cannot be resumed" in dl["note"]


def test_no_how_to_act_when_no_scenes():
    out = search_scenes(
        _FakeClient(scenes=[]),
        "Sentinel-2",
        "2024-01-01",
        "2024-01-15",
        minx=0,
        maxx=1,
        miny=0,
        maxy=1,
    )
    assert out["total"] == 0
    assert "how_to_act" not in out
    assert out["summary"] == "No scenes matched."


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


def test_portal_rejecting_all_selections_is_a_clean_empty_result():
    """A valid satellite with no data in range must not surface as a raw error."""
    from bhoonidhi_downloader.exceptions import BhoonidhiValidationError

    class _RejectingQuery:
        def create(self, *args, **kwargs):
            raise BhoonidhiValidationError("No valid selections to search")

    client = _FakeClient()
    client.query = _RejectingQuery()
    out = search_scenes(
        client, "Sentinel-2", "2024-01-01", "2024-01-15", minx=0, maxx=1, miny=0, maxy=1
    )
    assert out["status"] == "no_searchable_scenes"
    assert out["total"] == 0
    assert out["scenes"] == []
    assert out["matched_satellites"]  # tells the agent what was tried
    assert out["reason"]
