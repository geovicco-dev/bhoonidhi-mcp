"""The MCP server entry point.

Builds the server, registers tools, and runs the stdio transport. Phase 1
starts with a single ``ping`` tool to confirm the server loads in a client;
the real Bhoonidhi tools are registered here as they are implemented.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

server = MCPServer("bhoonidhi")


@server.tool()
def ping() -> str:
    """Health check. Returns 'pong' so a client can confirm the server is up."""
    return "pong"


def main() -> None:
    """Run the server over stdio (how desktop MCP clients launch it)."""
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
