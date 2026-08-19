# bhoonidhi-mcp

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent search,
save, and preview satellite scenes from [ISRO's Bhoonidhi Browse & Order portal](https://bhoonidhi.nrsc.gov.in/)
(NRSC) in natural language. An agent can turn a sentence like "Sentinel-2 over
Shillong last January" into a real search against the live portal, see honestly
what is available to download, save a search to reuse later, and preview what a
download would fetch — with no credentials configured.

It is a thin adapter over the
[`bhoonidhi-downloader`](https://github.com/geovicco-dev/bhoonidhi-downloader)
SDK — the same client the `bhd` CLI uses — so no portal logic is duplicated.

## Status

**Read-only and stateful, no authentication.** The tools below reach the full
archive of 41 satellite missions and 79 sensors, search the live portal, and
save searches to reusable slugs — all without a login. Downloading scenes and
staging them to the Bhoonidhi cart need credentials and are planned next; until
then, save a search with `save_query` and act on its slug with the `bhd` CLI.

## Tools

| Tool | What it does |
|------|--------------|
| `list_archive` | The vocabulary of satellites, sensors, and search tokens the portal supports, live from Bhoonidhi. |
| `resolve_location` | Turns a place name ("Loktak Lake") into a centroid and bounding box. Rejects inputs that are not place names. |
| `search_scenes` | Natural-language scene search over an area and date range. Resolves a casual satellite name to exact tokens, and reports each scene's availability (Ready / Archived / OnOrder / Priced). Stateless — nothing is saved. |
| `preview_download` | A dry run: shows what downloading the results would fetch, and what would be skipped, before anything is downloaded. |
| `save_query` | Persists a search (same arguments as `search_scenes`) to a reusable slug, so it can be downloaded or staged to the cart later. |
| `list_queries` | Lists saved queries as compact summaries: slug, name, date range, satellites, area, and availability. |
| `show_query` | Returns one saved query by slug, with its scenes. |
| `remove_query` | Deletes a saved query by slug. |

Availability matters: an `OpenData` scene is not necessarily staged for
download. `search_scenes` and `preview_download` distinguish **Ready** (fetch it
now) from **Archived** (open data, but may need a request on the portal first),
so an agent does not over-promise.

## Install

The server is a Python package with a console entry point, `bhoonidhi-mcp`.
Install it from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/geovicco-dev/bhoonidhi-mcp
cd bhoonidhi-mcp
uv sync
```

This exposes the `bhoonidhi-mcp` command at `.venv/bin/bhoonidhi-mcp`. The server
speaks stdio and is launched by an MCP client — you point the client at that
command.

## Connecting a client

Every MCP client needs the same thing: the command to launch. Use the absolute
path to the entry point (most reliable across GUI and CLI clients):

```
/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp
```

### Claude Desktop / Claude Code

`claude_desktop_config.json` (or `claude mcp add`):

```json
{
  "mcpServers": {
    "bhoonidhi": {
      "command": "/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp",
      "args": []
    }
  }
}
```

### OpenCode

`~/.config/opencode/opencode.json`:

```json
{
  "mcp": {
    "bhoonidhi": {
      "type": "local",
      "command": ["/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp"],
      "enabled": true
    }
  }
}
```

### MCP Inspector (to try it without an agent)

```bash
npx @modelcontextprotocol/inspector /path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp
```

## Example

Ask an agent, in plain language:

> "What Sentinel-2 scenes are over Shillong in January 2024, and how many can I
> actually download?"

The agent calls `resolve_location` for Shillong, then `search_scenes`, and
answers from the result — for example, that all scenes are *Archived* (open
data, but each may need a request on the portal before it will download), rather
than claiming they are all ready.

## Prompts to try

Copy these into any connected agent to get a feel for what it can do.

**Discover the archive**

- "What satellites and sensors does Bhoonidhi have?"
- "Which sensors does ResourceSat-2A carry, and at what resolution?"
- "Does Bhoonidhi have any radar satellites?"

**Search for scenes**

- "Find Sentinel-2 scenes over Shillong in January 2024."
- "Show me Cartosat imagery within 20 km of Bengaluru in the first half of 2024."
- "Any Sentinel-1 scenes over the Sundarbans in March 2024?"
- "What Landsat-8 imagery covers Kaziranga National Park last winter?"
- "Find MODIS scenes over the Rann of Kutch in December 2023."

**Check what's available to download**

- "Of those Sentinel-2 scenes, how many can I actually download right now?"
- "Which of these need to be ordered or paid for?"

**Preview a download**

- "Preview what downloading those scenes would fetch."

**Save a search to reuse**

- "Save that Sentinel-2 search so I can download it later."
- "List my saved searches."
- "Show me what's in the search I saved as <slug>."
- "Delete the saved search <slug>."

## Configuration

All optional, set as environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `BHOONIDHI_MCP_GEOCODER_USER_AGENT` | `bhoonidhi-mcp/0.1` | User-Agent sent to Nominatim (its usage policy asks for a descriptive one). |
| `BHOONIDHI_MCP_FUZZY_THRESHOLD` | `88` | Score (0–100) a satellite-name match must clear to be confident; below it, candidates are returned for the agent to confirm. |
| `BHOONIDHI_MCP_MAX_RESULTS` | `50` | Maximum scenes returned inline by `search_scenes`. |

## Development

```bash
uv sync
uv run pytest        # test suite
uv run ruff check .  # lint
```

## License

MIT — see [LICENSE](LICENSE).
