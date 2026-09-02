# Changelog

All notable changes to this project are documented here.

## [0.3.0]

Every tool now declares its trust hints, the landing page's demo map runs on
a basemap that needs no API key, and the server publishes to PyPI on release.

### Added

- **Every tool declares its readOnly / destructive / idempotent / openWorld hints** — none of the 15 tools carried these before, so any host had to treat every call as maximally risky by default, even a pure read like `list_archive`. Read-only search/list/show tools now report `read_only_hint=True`; `remove_query` and `cart_remove` (which drop state that is not trivially recreated) report `destructive_hint=True`; anything that starts a new background job or portal-side action (`save_query`, `download_query`, `cart_add`) reports `idempotent_hint=False`. Some directories reject a tool listing outright when any hint is missing.
- **The server publishes to PyPI on a GitHub Release**, authenticating via PyPI's trusted-publisher OIDC flow rather than a stored token — nothing to rotate or leak.

### Changed

- **`CITATION.cff` and a `mcp-name` marker in the README** support GitHub's "Cite this repository" button and the official MCP registry's PyPI ownership check, ahead of the server's first real PyPI publish.
- **The landing page's demo map switched from CartoDB to Esri World Imagery** — CartoDB's dark basemap started requiring an API key; Esri's tile service is free and needs no key, so it replaces it as the shared basemap across all four demo flows.

## [0.2.0]

Adds stateful saved queries and authenticated actions: an agent can now save a
search, then download open-access scenes or stage scenes to the cart, all in
conversation.

### Added

- **Saved queries turn a stateless search into a reusable slug** — `save_query` persists a search (the same arguments `search_scenes` takes) and `list_queries` / `show_query` / `remove_query` manage the slugs, so a search can be acted on later instead of evaporating; the portal keys every download and cart action off that slug, so persistence had to come first.
- **`auth_status` reports whether a login is configured** — read-only and secret-free by construction, it reflects the session the `bhd` CLI writes (or optional `BHOONIDHI_USERNAME` / `BHOONIDHI_PASSWORD` env credentials) without ever accepting a password as a tool argument or returning a token.
- **`download_query` fetches open-access scenes as a background job** — it confines output to a configured allow-listed root (`<root>/<slug>/`, never a caller-chosen path), returns a job id immediately, and runs on a daemon thread independent of the conversation, because a stdio server cannot stream progress inside a blocking tool call.
- **`download_status` and `download_wait` expose live byte-level progress** — status reports megabytes, transfer rate, and a percent once sizes are known (the portal only sends them once a transfer starts), and wait blocks until completion or a capped timeout so a delegated watcher can follow a long download without the main agent sleep-looping to babysit it.
- **`cart_add` / `cart_list` / `cart_remove` stage scenes that are not free-and-ready** — on-order and priced scenes route to the Bhoonidhi cart, with priced scenes still needing purchase on the portal afterwards.

### Changed

- **Search results now steer to the in-server tools** — the `how_to_act` block points at `save_query`, `download_query`, and `cart_add` for each availability state instead of printing `bhd` CLI commands, and a large download is flagged from live byte totals rather than a scene count, so a small-count multi-gigabyte fetch is caught.

## [0.1.1]

### Added

- **`search_scenes` and `preview_download` take a `product` filter** — the SDK's `Selection` already carried a `product` field (the third part of the portal's `SAT:SEN:PROD` token, e.g. `GCOV` under `NISAR:SSAR`), but the MCP tools only ever set `sensor`, so narrowing to a specific product silently fell back to a full-sensor search; `product` now reaches every resolved selection and shows up correctly in the reproduced `bhd` command.

## [0.1.0]

First working release: the Phase 1 read-only, no-authentication server, with all
four tools driving the live portal.

### Added

- **`list_archive` returns the portal's satellite and sensor vocabulary** — every satellite, its sensors, the exact search tokens, and each product's resolution and date coverage, fetched live from Bhoonidhi so an agent can discover what is searchable before querying.
- **`resolve_location` turns a place name into a centroid and bounding box** via geopy over OpenStreetMap's Nominatim, so an agent can search "over Shillong" without knowing coordinates; inputs that are not place names (empty, bare numbers, raw coordinates) are rejected rather than fuzzy-matched to an unrelated place.
- **`search_scenes` runs a stateless natural-language scene search** — a casual satellite name ("Sentinel-2", "cartosat") is fuzzy-resolved to the portal's exact tokens and a constellation expands to all its platforms, over a bounding box or a point-and-radius area, with no login and nothing persisted.
- **Search results report honest availability** — each scene is classified Ready, Archived (open data but may need a portal request), OnOrder, or Priced, with a per-scene downloadable flag, a plain-English summary of the counts, and a how_to_act block giving the exact `bhd` commands for downloading or cart-staging, so an agent can tell a user what is actually fetchable instead of over-promising.
- **`preview_download` is a no-auth dry run of a download** — it classifies what fetching the results would do per scene (would_download, may_404, already_here, already_elsewhere, skipped_on_order, skipped_priced) with predicted filenames and destinations, and states plainly that nothing is downloaded, that file sizes are unknown until a download starts, and that interrupted downloads cannot be resumed.
- **The JSON-RPC channel is guarded from stray stdout** — the downloader SDK's progress output is diverted to stderr so it can never corrupt the protocol wire, with a permanent regression test.

### Notes

- Built as a thin adapter over the public `bhoonidhi-downloader` SDK (>=0.5.3); no portal logic is duplicated, and the server never imports the SDK's internals.
- Malformed requests (reversed dates, missing or conflicting area of interest, an inverted bounding box, an out-of-range radius, an empty satellite) return a distinct `invalid_request` with a message that says how to fix it, kept separate from a genuine empty result.
- Everything is read-only and needs no credentials. Downloading scenes and staging to the cart require a login and are planned for Phase 2.
