# bhoonidhi-mcp

<!-- mcp-name: io.github.geovicco-dev/bhoonidhi-mcp -->

[![PyPI](https://img.shields.io/pypi/v/bhoonidhi-mcp.svg)](https://pypi.org/project/bhoonidhi-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-listed-blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.geovicco-dev/bhoonidhi-mcp)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

An [MCP](https://modelcontextprotocol.io) server that lets an AI agent search,
save, download, and cart satellite scenes from [ISRO's Bhoonidhi Browse & Order portal](https://bhoonidhi.nrsc.gov.in/)
(NRSC) in natural language. An agent can turn a sentence like "Sentinel-2 over
Shillong last January" into a real search against the live portal, see honestly
what is available to download, save a search to reuse later, preview what a
download would fetch, and — once logged in — download open-access scenes or
stage them to the cart.

It is a thin adapter over the
[`bhoonidhi-downloader`](https://github.com/geovicco-dev/bhoonidhi-downloader)
SDK — the same client the `bhd` CLI uses — so no portal logic is duplicated.

## Status

**Search and save with no login; download and cart with one.** The tools reach
the full archive of 41 satellite missions and 79 sensors, search the live
portal, and save searches to reusable slugs — all without credentials.
Downloading open-access scenes and staging scenes to the Bhoonidhi cart need a
login, done out of band with `bhd auth login` (the server reuses that session).

## Tools

| Tool | What it does | Login |
| ------ | -------------- | ------- |
| `list_archive` | The vocabulary of satellites, sensors, and search tokens the portal supports, live from Bhoonidhi. | no |
| `resolve_location` | Turns a place name ("Loktak Lake") into a centroid and bounding box. Rejects inputs that are not place names. | no |
| `search_scenes` | Natural-language scene search over an area and date range. Resolves a casual satellite name to exact tokens, and reports each scene's availability (Ready / Archived / OnOrder / Priced). Stateless — nothing is saved. | no |
| `preview_download` | A dry run: shows what downloading the results would fetch, and what would be skipped, before anything is downloaded. | no |
| `save_query` | Persists a search (same arguments as `search_scenes`) to a reusable slug, so it can be downloaded or staged to the cart later. | no |
| `list_queries` | Lists saved queries as compact summaries: slug, name, date range, satellites, area, and availability. | no |
| `show_query` | Returns one saved query by slug, with its scenes. | no |
| `remove_query` | Deletes a saved query by slug. | no |
| `auth_status` | Reports whether a login is configured. Never handles a password or token. | no |
| `download_query` | Downloads a saved query's open-access scenes in the background, to a fixed server-configured root. Returns a `job_id` at once. | yes |
| `download_status` | One-off check of a background download by `job_id`: bytes downloaded, transfer rate, percent when the size is known, and per-scene detail. | no |
| `download_wait` | Blocks until a download finishes (or a capped timeout), then reports — the efficient primitive a background watcher loops on. | no |
| `cart_add` | Stages a saved query's scenes to the cart (routes each to ready / on-order / priced). | yes |
| `cart_list` | Lists scenes currently staged in the cart. | yes |
| `cart_remove` | Removes scenes from the cart. | yes |

Availability matters: an `OpenData` scene is not necessarily staged for
download. `search_scenes` and `preview_download` distinguish **Ready** (fetch it
now) from **Archived** (open data, but may need a request on the portal first),
so an agent does not over-promise.

Downloads run in the background, independent of the conversation:
`download_query` returns a `job_id` at once and the transfer proceeds on its own.
Check progress once with `download_status` — it reports bytes downloaded, a
transfer rate, and a percent once the size is known — or follow a job to
completion with `download_wait`, which blocks until it finishes (or a capped
timeout) so an agent can delegate a background watcher and keep the conversation
free instead of sleep-looping. A job lives only as long as the server process,
so once a download proves large the status recommends running a standalone `bhd
query download <slug>` command you own instead.

## Install

The server is a Python package with a console entry point, `bhoonidhi-mcp`. The
simplest way to run it is with [uv](https://docs.astral.sh/uv/) — `uvx` fetches,
builds, and launches it straight from the source, no clone or virtualenv needed:

```bash
uvx --from git+https://github.com/geovicco-dev/bhoonidhi-mcp bhoonidhi-mcp
```

The first run builds from source; later runs start from cache. The server speaks
stdio and is launched by an MCP client — you point the client at that command.

Prefer a local checkout (for development)? Clone and `uv sync`, then use
`.venv/bin/bhoonidhi-mcp` as the command instead:

```bash
git clone https://github.com/geovicco-dev/bhoonidhi-mcp
cd bhoonidhi-mcp
uv sync
```

## Connecting a client

Every MCP client needs the same thing: the command to launch. Point it at `uvx`
with the source and entry point as arguments.

### Claude Desktop / Claude Code

`claude_desktop_config.json` (or `claude mcp add`):

```json
{
  "mcpServers": {
    "bhoonidhi": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/geovicco-dev/bhoonidhi-mcp", "bhoonidhi-mcp"]
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
      "command": ["uvx", "--from", "git+https://github.com/geovicco-dev/bhoonidhi-mcp", "bhoonidhi-mcp"],
      "enabled": true
    }
  }
}
```

### MCP Inspector (to try it without an agent)

```bash
npx @modelcontextprotocol/inspector uvx --from git+https://github.com/geovicco-dev/bhoonidhi-mcp bhoonidhi-mcp
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

### Discover the archive

- "What satellites and sensors does Bhoonidhi have?"
- "Which sensors does ResourceSat-2A carry, and at what resolution?"
- "Does Bhoonidhi have any radar satellites?"

### Search for scenes

- "Find Sentinel-2 scenes over Shillong in January 2024."
- "Show me Cartosat imagery within 20 km of Bengaluru in the first half of 2024."
- "Any Sentinel-1 scenes over the Sundarbans in March 2024?"
- "What Landsat-8 imagery covers Kaziranga National Park last winter?"
- "Find MODIS scenes over the Rann of Kutch in December 2023."

### Check what's available to download

- "Of those Sentinel-2 scenes, how many can I actually download right now?"
- "Which of these need to be ordered or paid for?"

### Preview a download

- "Preview what downloading those scenes would fetch."

### Save a search to reuse

- "Save that Sentinel-2 search so I can download it later."
- "List my saved searches."
- "Show me what's in the search I saved as `<slug>`."
- "Delete the saved search `<slug>`."

### Download and cart (needs a login — see below)

- "Am I logged in to Bhoonidhi?"
- "Download the open-data scenes from my saved search `<slug>`."
- "How's that download going?"
- "Download `<slug>` and let me know when it's done — I'll keep working."
- "Add the priced scenes from `<slug>` to my cart."
- "What's in my cart this week?"

## Login (for downloads and cart)

Search, saved queries, and previews need no credentials. Downloading scenes and
staging them to the cart do. Log in once, out of band — the server reuses the
same session the `bhd` CLI writes:

```bash
bhd auth login
```

The MCP server never takes a username or password as a tool argument, and
`auth_status` never returns your token. For a headless setup with no interactive
login, you can instead set `BHOONIDHI_USERNAME` / `BHOONIDHI_PASSWORD` in the
server's environment; the server reads them only to establish a session.

## Configuration

Set as environment variables (all optional):

| Variable | Default | Purpose |
| ---------- | --------- | --------- |
| `BHOONIDHI_MCP_GEOCODER_USER_AGENT` | `bhoonidhi-mcp/0.3` | User-Agent sent to Nominatim (its usage policy asks for a descriptive one). |
| `BHOONIDHI_MCP_FUZZY_THRESHOLD` | `88` | Score (0–100) a satellite-name match must clear to be confident; below it, candidates are returned for the agent to confirm. |
| `BHOONIDHI_MCP_MAX_RESULTS` | `50` | Maximum scenes returned inline by `search_scenes`. |
| `BHOONIDHI_MCP_DOWNLOAD_ROOT` | `~/Downloads` | Allow-listed root every download writes under, as `<root>/<slug>/`. The agent cannot choose an arbitrary path. |
| `BHOONIDHI_MCP_DOWNLOAD_PARALLEL` | `4` | Parallel download workers. |
| `BHOONIDHI_MCP_LARGE_DOWNLOAD_MB` | `500` | Once a download's live byte total (or known size) passes this, the status flags it large and steers the agent to hand off or run a standalone command. |
| `BHOONIDHI_USERNAME` / `BHOONIDHI_PASSWORD` | *(unset)* | Optional headless login. Prefer `bhd auth login`; fill these out of band, never commit them. |

## Data usage and attribution

The imagery reached through this server belongs to ISRO/NRSC and is governed by the [Bhoonidhi EULA](https://bhoonidhi.nrsc.gov.in/bhoonidhi/htmls/TnC.html), not by this project's MIT license — that license covers the code here, nothing else. What the EULA asks of you:

- **Use your own account.** Downloads and cart actions authenticate with your own Bhoonidhi login, established out of band. The server never takes a password as a tool argument and never shares or bypasses a session.
- **Credit the source.** Anything you publish from this data must carry the caption **ISRO-IRS**.
- **Don't resell the raw data.** Scenes the portal marks as open data are free to use, publish, and build on. The original products just can't be redistributed commercially in their original form — derived and value-added products are fine.
- **Priced and on-order scenes go through the portal.** This server never bypasses payment: priced and on-order scenes are only staged to the cart, and you complete any order and payment on Bhoonidhi.

## Development

```bash
uv sync
uv run pytest        # test suite
uv run ruff check .  # lint
```

## License

MIT — see [LICENSE](LICENSE).
