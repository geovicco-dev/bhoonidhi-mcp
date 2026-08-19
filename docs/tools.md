# Tools

Phase 1 exposes three tools plus one resource, all read-only and no-login. Each
is a thin adapter over the same `BhoonidhiClient` the `bhd` command line uses, so
no portal logic is duplicated. The agent calls them in order: discover the
vocabulary, resolve a place, search.

## list_archive

The satellites and sensors the portal supports, with their exact search tokens,
resolution, and date coverage. An agent calls this to learn what can be searched.

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `refresh` | bool | `false` | Bypass the local cache and re-fetch from the portal. |

Returns `{ "satellites": [ … ] }` — one record per satellite, each listing its
sensors, the exact `SAT_SEN_PROD` search token, resolution in metres, and the
date range it covers.

The same data is also exposed as the read-only resource `bhoonidhi://archive`.

## resolve_location

Turns a place name into a centroid and a bounding box that `search_scenes` can
use as its area of interest.

| Argument | Type | Meaning |
|---|---|---|
| `name` | str | A place such as `"Shillong"` or `"Loktak Lake"`. |

Returns `{ found, name, lat, lon, bbox }` on success, or `{ found: false }` when
the place can't be resolved — it reports the miss rather than guessing.

## search_scenes

The centerpiece: a stateless, natural-language scene search against the live
portal.

| Argument | Type | Meaning |
|---|---|---|
| `satellite` | str | A casual name (`"Sentinel-2"`, `"cartosat"`), matched to the portal's exact tokens. A constellation expands to all its platforms. |
| `start_date` / `end_date` | str | ISO dates, `YYYY-MM-DD`. |
| `minx` `maxx` `miny` `maxy` | float | A bounding box for the area of interest… |
| `lat` `lon` `radius_km` | float | …or a point plus radius instead. |
| `sensor` | str | Optional, to narrow to one sensor. |

The search is stateless (`save=False`), so agent searches never litter the local
query store.

### Availability is reported honestly

Every returned scene carries an `availability` label, classified the same way the
CLI does, so an agent can tell you what you can actually download before you try:

| Label | Meaning |
|---|---|
| **Ready** | Open data, staged — downloads now. |
| **Archived** | Open data, not currently staged — may 404 until requested on the portal. |
| **On order** | Must be requested before it can be fetched. |
| **Priced** | Commercial — requires payment. |

`Ready` and `Archived` are the two open-data states; `On order` and `Priced` come
from a scene's pricing. ESA open data (Sentinel-1, Sentinel-2, Landsat) is always
`Ready` or `Archived`; only commercial missions such as Cartosat are priced.

The result also includes an `availability_summary` counting every matched scene by
label — so the agent can answer "how many can I actually download?" over the whole
result set, not just the returned page.

### When a name is ambiguous

If the satellite name doesn't confidently match, the tool returns
`status: "ambiguous_satellite"` with candidate names instead of running a wrong
search. The agent surfaces the candidates so you can pick one.

## What's next

Downloads and cart staging need a login and arrive in **Phase 2**. They are
deliberately absent from Phase 1, which stays read-only so the natural-language
discovery story ships with no credential handling at all.
