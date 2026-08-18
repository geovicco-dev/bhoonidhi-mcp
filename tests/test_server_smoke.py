"""Smoke test: the server object builds and its ping tool works."""

from bhoonidhi_mcp.server import ping, server


def test_ping_returns_pong():
    assert ping() == "pong"


def test_server_has_a_name():
    assert server.name == "bhoonidhi"
