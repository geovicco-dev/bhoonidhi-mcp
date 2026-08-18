# bhoonidhi-mcp

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent search
and preview satellite scenes from ISRO's Bhoonidhi EO portal in natural
language. It is a thin adapter over the
[`bhoonidhi-downloader`](https://github.com/geovicco-dev/bhoonidhi-downloader)
SDK — the same client the `bhd` CLI uses — so no portal logic is duplicated.

## Status

Phase 1: read-only, no authentication. An agent can turn a sentence like
"Sentinel-2 over Shillong last winter" into a real search against the live
portal, and preview what downloading the results would do — with no credentials
configured.

## Install

```bash
pip install bhoonidhi-mcp
```

## Tools (Phase 1)

- `list_archive` — the vocabulary of satellites/sensors the portal supports.
- `resolve_location` — turn a place name into coordinates and a bounding box.
- `search_scenes` — natural-language scene search (stateless).
- `preview_download` — show what a download would fetch, before fetching.

All four need no login. Downloads and cart actions arrive in Phase 2.

## Run

The server speaks stdio and is launched by an MCP client (Claude Desktop,
Cursor, MCP Inspector). Point the client at the `bhoonidhi-mcp` command.

## License

MIT
