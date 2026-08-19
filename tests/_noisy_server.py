"""Test fixture: a minimal MCP server whose tool floods stdout.

Run as a subprocess by the protocol-safety test. Its ``noisy`` tool writes raw
text to stdout and drives the downloader's Rich console — the worst case for a
stdio JSON-RPC server — then returns a clean result. The test asserts the
protocol wire survives anyway.

Named with a leading underscore so pytest does not collect it as a test module.
"""

import sys

from bhoonidhi_downloader.logger import get_console
from mcp.server.mcpserver import MCPServer

server = MCPServer("noisy-probe")


@server.tool()
def noisy() -> str:
    """Emit deliberate stdout noise, then return a clean result."""
    print("RAW_PRINT_SHOULD_NOT_REACH_THE_WIRE")
    sys.stdout.write("DIRECT_WRITE_SHOULD_NOT_REACH_THE_WIRE\n")
    get_console().print("[warning]a Rich console warning[/warning]")
    return "ok"


if __name__ == "__main__":
    server.run(transport="stdio")
