"""Phase 2b: authenticated actions — auth_status, downloads, cart. Offline.

Fakes stand in for the authenticated BhoonidhiClient. The download tests drive
the real background job registry (jobs.py) and wait for the daemon thread to
finish, so the poll state machine is exercised end to end without a portal.
"""

import time
from dataclasses import dataclass
from types import SimpleNamespace

from bhoonidhi_downloader.exceptions import BhoonidhiAuthError, BhoonidhiNotFoundError

import bhoonidhi_mcp.jobs as jobs_module
from bhoonidhi_mcp.tools import (
    auth_status,
    cart_add,
    cart_list,
    cart_remove,
    download_query,
    download_status,
)


@dataclass
class _Outcome:
    scene_id: str
    status: str
    path: str | None = None
    sha256: str | None = None
    bytes_downloaded: int = 0
    error: str | None = None
    restarted_bytes: int = 0


_READY = {"ID": "S1", "PRICED": "OpenData_DirectDownload", "CURR_SCENE_NO": "Y"}


class _FakeQuery:
    def __init__(self, scenes, download_impl=None):
        self._scenes = scenes
        self._download_impl = download_impl
        self.download_calls = []

    def show(self, slug):
        if slug == "missing":
            raise BhoonidhiNotFoundError("no such slug")
        return SimpleNamespace(scenes=self._scenes)

    def download(self, slug, out, *, select=None, parallel=4, force=False,
                 on_progress=None):
        self.download_calls.append({"slug": slug, "out": out, "force": force})
        if self._download_impl is not None:
            return self._download_impl(on_progress)
        if on_progress:
            on_progress("S1", 100, 100)
        return [_Outcome("S1", "downloaded", path=f"{out}/S1.zip", bytes_downloaded=100)]


class _FakeCart:
    def __init__(self, add=None, listing=None, rm=None):
        self._add = add
        self._listing = listing if listing is not None else []
        self._rm = rm

    def add(self, slug, select=None, on_progress=None):
        if slug == "missing":
            raise BhoonidhiNotFoundError("no such slug")
        return self._add

    def list(self, filter_by=None, last=None):
        return self._listing

    def rm(self, slug=None, select=None, since=None, until=None, last=None,
           filter_by=None, on_progress=None):
        return self._rm


class _FakeClient:
    def __init__(self, *, authenticated=True, username="alice",
                 scenes=None, download_impl=None, cart=None, refresh_ok=False):
        self.is_authenticated = authenticated
        self._username = username
        self._refresh_ok = refresh_ok
        self.query = _FakeQuery(scenes if scenes is not None else [_READY],
                                download_impl=download_impl)
        self.cart = cart if cart is not None else _FakeCart()

    def whoami(self):
        # A username can be known even with a lapsed token, so it is not gated
        # on is_authenticated here.
        return self._username

    def refresh(self):
        return object() if self._refresh_ok else None


def setup_function():
    jobs_module._reset()


def _wait_for(job_id, terminal=("completed", "failed", "not_found"), timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = download_status(job_id)
        if snap["status"] in terminal:
            return snap
        time.sleep(0.01)
    return download_status(job_id)


# --- auth_status ------------------------------------------------------------


def test_auth_status_reports_logged_in_without_leaking_a_secret():
    out = auth_status(_FakeClient(authenticated=True, username="alice"))
    assert out["status"] == "ok"
    assert out["authenticated"] is True
    assert out["username"] == "alice"
    # No secret material anywhere in the payload.
    blob = repr(out).lower()
    assert "jwt" not in blob and "password" not in blob and "token" not in blob


def test_auth_status_reports_not_logged_in():
    out = auth_status(_FakeClient(authenticated=False))
    assert out["status"] == "ok"
    assert out["authenticated"] is False
    assert "bhd auth login" in out["message"]


def test_auth_status_survives_an_auth_error():
    class _Broken(_FakeClient):
        @property
        def is_authenticated(self):
            raise BhoonidhiAuthError("boom")

        @is_authenticated.setter
        def is_authenticated(self, v):
            pass

    out = auth_status(_Broken(authenticated=True))
    assert out["authenticated"] is False


# --- download gating + root safety -----------------------------------------


def test_download_requires_authentication():
    out = download_query(_FakeClient(authenticated=False), "q1")
    assert out["status"] == "not_authenticated"
    assert "bhd auth login" in out["hint"]


def test_expired_token_refresh_unblocks_download():
    client = _FakeClient(authenticated=False, refresh_ok=True)
    out = download_query(client, "q1")
    assert out["status"] == "started"


def test_download_unknown_slug_is_not_found():
    out = download_query(_FakeClient(), "missing")
    assert out["status"] == "not_found"


def test_download_writes_under_the_configured_root(monkeypatch, tmp_path):
    monkeypatch.setenv("BHOONIDHI_MCP_DOWNLOAD_ROOT", str(tmp_path))
    client = _FakeClient()
    out = download_query(client, "q1")
    assert out["status"] == "started"
    # Path is computed as <root>/<slug>, never caller-chosen.
    assert out["out_dir"] == str(tmp_path / "q1")
    snap = _wait_for(out["job_id"])
    assert snap["status"] == "completed"
    assert client.query.download_calls[0]["out"] == str(tmp_path / "q1")


def test_download_root_defaults_to_downloads(monkeypatch):
    monkeypatch.delenv("BHOONIDHI_MCP_DOWNLOAD_ROOT", raising=False)
    out = download_query(_FakeClient(), "q1")
    assert out["out_dir"].endswith("/Downloads/q1")


# --- download poll state machine -------------------------------------------


def test_download_status_progresses_to_completed_with_outcomes(monkeypatch, tmp_path):
    monkeypatch.setenv("BHOONIDHI_MCP_DOWNLOAD_ROOT", str(tmp_path))

    def impl(on_progress):
        on_progress("S1", 50, 100)
        on_progress("S2", 50, 100)
        return [
            _Outcome("S1", "downloaded", path="a.zip", bytes_downloaded=100),
            _Outcome("S2", "skipped_priced"),
        ]

    out = download_query(_FakeClient(download_impl=impl), "q1")
    assert out["status"] == "started"
    snap = _wait_for(out["job_id"])
    assert snap["status"] == "completed"
    assert snap["scenes_started"] == 2
    ids = [o["id"] for o in snap["outcomes"]]
    assert ids == ["S1", "S2"]
    # Each outcome is glossed in plain language.
    priced = next(o for o in snap["outcomes"] if o["id"] == "S2")
    assert "priced" in priced["meaning"].lower()


def test_download_failure_is_captured_not_raised(monkeypatch, tmp_path):
    monkeypatch.setenv("BHOONIDHI_MCP_DOWNLOAD_ROOT", str(tmp_path))

    def impl(on_progress):
        raise RuntimeError("portal exploded")

    out = download_query(_FakeClient(download_impl=impl), "q1")
    snap = _wait_for(out["job_id"])
    assert snap["status"] == "failed"
    assert "portal exploded" in snap["error"]


def test_download_status_unknown_job_is_not_found():
    assert download_status("deadbeef")["status"] == "not_found"


def test_large_download_suggests_a_standalone_command(monkeypatch, tmp_path):
    monkeypatch.setenv("BHOONIDHI_MCP_DOWNLOAD_ROOT", str(tmp_path))
    many = [dict(_READY, ID=f"S{i}") for i in range(40)]
    out = download_query(_FakeClient(scenes=many), "big")
    assert "large_download" in out
    assert "bhd query download big" in out["large_download"]
    _wait_for(out["job_id"])


# --- cart -------------------------------------------------------------------


def test_cart_add_shapes_added_and_failed():
    added = [({"ID": "S1"}, SimpleNamespace(name="PRICED"))]
    failed = [({"ID": "S2"}, "already staged")]
    client = _FakeClient(cart=_FakeCart(add=(added, failed, "srt-1")))
    out = cart_add(client, "q1")
    assert out["status"] == "ok"
    assert out["added"] == 1 and out["failed"] == 1
    assert out["staged"][0] == {"id": "S1", "cart": "priced"}
    assert out["not_staged"][0]["reason"] == "already staged"


def test_cart_add_requires_authentication():
    out = cart_add(_FakeClient(authenticated=False), "q1")
    assert out["status"] == "not_authenticated"


def test_cart_add_unknown_slug_is_not_found():
    client = _FakeClient(cart=_FakeCart(add=([], [], None)))
    out = cart_add(client, "missing")
    assert out["status"] == "not_found"


def test_cart_list_shapes_items():
    items = [{"ID": "S1", "SATELLITE": "SEN2A", "SENSOR": "MSI", "DOP": "06JAN2024"}]
    out = cart_list(_FakeClient(cart=_FakeCart(listing=items)))
    assert out["status"] == "ok"
    assert out["total"] == 1
    assert out["items"][0] == {
        "id": "S1", "satellite": "SEN2A", "sensor": "MSI", "date_of_pass": "06JAN2024",
    }


def test_cart_remove_shapes_removed_and_failed():
    removed = [("S1", SimpleNamespace(name="DIRECT"))]
    failed = [("S2", "not in cart")]
    client = _FakeClient(cart=_FakeCart(rm=(removed, failed)))
    out = cart_remove(client, slug="q1")
    assert out["status"] == "ok"
    assert out["removed"] == 1 and out["failed"] == 1
    assert out["removed_ids"] == ["S1"]
    assert out["not_removed"][0]["reason"] == "not in cart"


def test_cart_remove_requires_authentication():
    out = cart_remove(_FakeClient(authenticated=False), slug="q1")
    assert out["status"] == "not_authenticated"
