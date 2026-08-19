# Changelog

All notable changes to this project are documented here.

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
