"""Smoke test: the server builds and registers the expected tools."""

import anyio

from bhoonidhi_mcp.server import server


def test_server_has_a_name():
    assert server.name == "bhoonidhi"


def test_expected_tools_are_registered():
    tools = anyio.run(server.list_tools)
    names = {t.name for t in tools}
    assert {"list_archive", "resolve_location", "search_scenes"} <= names
