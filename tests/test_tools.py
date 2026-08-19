"""The tool adapters shape SDK results for agents, without a live portal.

A fake client stands in for BhoonidhiClient so these run offline. It returns a
real archive snapshot and a realistic scene dict, so shaping is exercised
against the actual portal field names.
"""

import json
from pathlib import Path

import bhoonidhi_mcp.tools as tools_module
from bhoonidhi_mcp.tools import list_archive, preview_download, search_scenes

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
    "FILENAME": "sen2a_scene",
    "DIRPATH": "archive/2024/01",
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
        self.last_selections = None

    def create(self, *args, **kwargs):
        from types import SimpleNamespace

        self.last_selections = kwargs.get("selections")
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
    """The stateless result must point at save_query and give the bhd commands."""
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
    # The agent is told to persist first, and where in-server actions are headed.
    assert "save_query" in act["mcp_status"] and "future update" in act["mcp_status"]
    assert "save_query" in act["save_first"] and "<slug>" in act["save_first"]
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
    assert out["status"] == "invalid_request"
    assert "date" in out["error"].lower()


def test_invalid_requests_are_distinct_and_actionable():
    """Malformed inputs must not collapse into one vague empty result."""
    s, e = "2024-01-01", "2024-01-15"

    # Empty satellite.
    r = search_scenes(_FakeClient(), "", s, e, minx=0, maxx=1, miny=0, maxy=1)
    assert r["status"] == "invalid_request" and "satellite" in r["error"].lower()

    # No area of interest at all.
    r = search_scenes(_FakeClient(), "Sentinel-2", s, e)
    assert r["status"] == "invalid_request" and "area" in r["error"].lower()

    # Both a bbox and a point.
    r = search_scenes(
        _FakeClient(), "Sentinel-2", s, e,
        minx=0, maxx=1, miny=0, maxy=1, lat=12.0, lon=77.0,
    )
    assert r["status"] == "invalid_request" and "only one" in r["error"].lower()

    # Inverted bounding box.
    r = search_scenes(_FakeClient(), "Sentinel-2", s, e, minx=2, maxx=1, miny=2, maxy=1)
    assert r["status"] == "invalid_request" and "invert" in r["error"].lower()

    # Radius out of the documented 1-100 range.
    for bad_radius in (0.1, 200):
        r = search_scenes(
            _FakeClient(), "Sentinel-2", s, e, lat=12.0, lon=77.0, radius_km=bad_radius
        )
        assert r["status"] == "invalid_request" and "radius" in r["error"].lower()

    # Reversed date range.
    r = search_scenes(
        _FakeClient(), "Sentinel-2", "2024-01-31", "2024-01-01",
        minx=0, maxx=1, miny=0, maxy=1,
    )
    assert r["status"] == "invalid_request" and "before" in r["error"].lower()


def test_valid_request_is_not_flagged_as_invalid():
    out = search_scenes(
        _FakeClient(scenes=[_SCENE]), "Sentinel-2", "2024-01-01", "2024-01-15",
        minx=91.7, maxx=92.0, miny=25.4, maxy=25.7,
    )
    assert out["status"] == "ok"


def test_product_narrows_every_selection_and_reaches_the_sdk():
    """product is a Selection field (the SAT_SEN_PROD token's third part), not a
    sensor — it must reach the SDK query unchanged on every expanded selection."""
    client = _FakeClient(scenes=[_SCENE])
    out = search_scenes(
        client, "Sentinel-2", "2024-01-01", "2024-01-15",
        minx=91.7, maxx=92.0, miny=25.4, maxy=25.7,
        sensor="MSI", product="Level-1C",
    )
    assert out["status"] == "ok"
    selections = client.query.last_selections
    assert selections and all(s.sensor == "MSI" for s in selections)
    assert selections and all(s.product == "Level-1C" for s in selections)


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


def test_preview_download_classifies_and_disclaims(tmp_path):
    ready = _scene("OpenData_DirectDownload", "Y")
    archived = _scene("OpenData_DirectDownload")  # not staged -> may_404
    priced = _scene("Priced")
    out = preview_download(
        _FakeClient(scenes=[ready, archived, priced]),
        "Sentinel-2",
        "2024-01-01",
        "2024-01-15",
        out_dir=str(tmp_path),
        minx=91.7,
        maxx=92.0,
        miny=25.4,
        maxy=25.7,
    )
    assert out["status"] == "ok"
    assert out["total"] == 3
    statuses = [s["status"] for s in out["scenes"]]
    assert statuses == ["would_download", "may_404", "skipped_priced"]
    assert out["status_counts"] == {
        "would_download": 1,
        "may_404": 1,
        "skipped_priced": 1,
    }
    # Every scene carries a plain-English meaning and a destination path.
    assert all(s["meaning"] and s["out_path"] for s in out["scenes"])
    # The honest disclaimers are always present.
    joined = " ".join(out["disclaimers"]).lower()
    assert "dry run" in joined
    assert "size" in joined and "cannot be resumed" in joined


def test_preview_download_reuses_search_error_paths():
    # Ambiguous satellite short-circuits before any preview.
    amb = preview_download(
        _FakeClient(), "LISS", "2024-01-01", "2024-01-15", minx=0, maxx=1, miny=0, maxy=1
    )
    assert amb["status"] == "ambiguous_satellite"
    assert amb["candidates"]


def test_preview_force_would_redownload_existing_file(tmp_path):
    ready = _scene("OpenData_DirectDownload", "Y")
    # Pre-place the file the preview expects, so a normal run says already_here.
    (tmp_path / "sen2a_scene.zip").write_bytes(b"x")
    normal = preview_download(
        _FakeClient(scenes=[ready]), "Sentinel-2", "2024-01-01", "2024-01-15",
        out_dir=str(tmp_path), minx=91.7, maxx=92.0, miny=25.4, maxy=25.7,
    )
    assert normal["scenes"][0]["status"] == "already_here"
    forced = preview_download(
        _FakeClient(scenes=[ready]), "Sentinel-2", "2024-01-01", "2024-01-15",
        out_dir=str(tmp_path), force=True, minx=91.7, maxx=92.0, miny=25.4, maxy=25.7,
    )
    assert forced["scenes"][0]["status"] == "would_download"
