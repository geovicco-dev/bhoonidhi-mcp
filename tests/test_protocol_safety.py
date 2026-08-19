"""The protocol channel stays clean even when a tool floods stdout.

This is the load-bearing regression guard for the whole server: a stdio MCP
server dies if anything but JSON-RPC reaches stdout, and the downloader SDK
prints on its search paths. These tests prove (a) the redirect helper works and
(b) end to end, worst-case stray stdout does not corrupt the wire.
"""

import io
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client

from bhoonidhi_mcp.protocol_safety import sdk_console_to_stderr

_NOISY_SERVER = str(Path(__file__).parent / "_noisy_server.py")


def test_helper_routes_stdout_to_stderr():
    out, err = io.StringIO(), io.StringIO()
    real_out, real_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        with sdk_console_to_stderr():
            print("noise")
    finally:
        sys.stdout, sys.stderr = real_out, real_err
    assert out.getvalue() == ""
    assert "noise" in err.getvalue()


def test_stray_stdout_does_not_corrupt_wire():
    async def run():
        params = StdioServerParameters(command=sys.executable, args=[_NOISY_SERVER])
        async with stdio_client(params) as (r, w), ClientSession(r, w) as session:
            init = await session.initialize()
            result = await session.call_tool("noisy", {})
            return init.server_info.name, result.content[0].text, result.is_error

    name, text, is_error = anyio.run(run)
    assert name == "noisy-probe"
    assert text == "ok"
    assert not is_error
