/* runs.js — example sessions and client configs.
 * Every satellite name, token, availability label, and place coordinate here is
 * real: names/tokens come from the live Bhoonidhi archive, coordinates from the
 * server's own geocoder. Scene IDs and per-scene counts are representative of a
 * live query (a landing page cannot run the live portal for every visitor).
 */

// Availability labels exactly as the server classifies them (see the SDK's
// core/search/availability.py):
//   Ready    — open data, staged, downloads now
//   Archived — open data, not staged; may 404 until requested on the portal
//   OnOrder  — must be requested before fetching (the PRICED field)
//   Priced   — commercial, requires payment
// Ready/Archived are the two open-data states; OnOrder/Priced come from pricing.
// ESA/NASA open data (Sentinel-1, Sentinel-2, Landsat, NISAR) is ALWAYS Ready or
// Archived — never OnOrder/Priced. Only commercial missions (e.g. Cartosat) are
// priced. The three runs below trace the three real uses end to end: search open
// data; find open scenes and download them; find priced data and stage the cart.
window.RUNS = [
  {
    key: 'shillong',
    chip: '1 · Search open data',
    flow: 'Search & find open data',
    prompt: 'Find Sentinel-2 scenes over Shillong from the first two weeks of January 2024.',
    place: 'Shillong, Meghalaya',
    bbox: { minx: 91.7228, miny: 25.4160, maxx: 92.0428, maxy: 25.7360 },
    center: [25.5760, 91.8828],
    sensor: 'MSI · optical',
    res: '10 m',
    window: '1–14 Jan 2024',
    // Representative acquisition footprint (deg): Sentinel-2 tiles, orbit-tilted.
    footprint: { w: 0.34, h: 0.40, rot: -12 },
    steps: [
      { type: 'agent', txt: 'Shillong is a place name. Resolve it to coordinates first.' },
      { type: 'tool', fn: 'resolve_location', args: [['name', '"Shillong"', 'n']],
        result: [
          '{ found: <s>true</s>,',
          '&nbsp;&nbsp;name: <s>"Shillong, East Khasi Hills, Meghalaya, India"</s>,',
          '&nbsp;&nbsp;lat: <n>25.576</n>, lon: <n>91.883</n>,',
          '&nbsp;&nbsp;bbox: { minx: <n>91.723</n>, miny: <n>25.416</n>, maxx: <n>92.043</n>, maxy: <n>25.736</n> } }'
        ] },
      { type: 'agent', txt: 'Now the search. "Sentinel-2" matches the constellation, so it expands to every platform the portal lists.' },
      { type: 'tool', fn: 'search_scenes',
        args: [['satellite', '"Sentinel-2"', 'n'], ['start_date', '"2024-01-01"', 's'], ['end_date', '"2024-01-14"', 's'], ['bbox', '91.72,25.42,92.04,25.74', 'n']],
        matched: 'Sentinel-2A · Sentinel-2B · Sentinel-2C',
        token: 'Sentinel-2A_MSI_Level-1C',
        scenes: [
          { id: 'S2A_MSIL1C_20240103T043', dop: '2024-01-03', lat: 25.55, lon: 91.85, st: 'Ready' },
          { id: 'S2B_MSIL1C_20240105T043', dop: '2024-01-05', lat: 25.62, lon: 91.95, st: 'Ready' },
          { id: 'S2A_MSIL1C_20240108T043', dop: '2024-01-08', lat: 25.48, lon: 91.78, st: 'Archived' },
          { id: 'S2B_MSIL1C_20240110T043', dop: '2024-01-10', lat: 25.66, lon: 91.90, st: 'Ready' },
          { id: 'S2A_MSIL1C_20240113T043', dop: '2024-01-13', lat: 25.58, lon: 92.00, st: 'Archived' }
        ],
        summary: [['Ready', '5 Ready'], ['Archived', '7 Archived']],
        total: 12 },
      { type: 'answer', html: '<b>12 Sentinel-2 scenes</b> over Shillong in that window. <b>5 are Ready</b> to download; the other 7 are Archived open data you request first. Say the word and I can save this search and pull the Ready scenes.' }
    ]
  },
  {
    key: 'nisar',
    chip: '2 · Download open scenes',
    flow: 'Find open scenes → download them',
    prompt: 'Get me NISAR radar over the Kosi river floodplain in August 2026, and download what\u2019s ready.',
    place: 'Kosi River, Bihar',
    bbox: { minx: 86.7500, miny: 25.3000, maxx: 87.1500, maxy: 25.7000 },
    center: [25.5000, 86.9500],
    sensor: 'SSAR GCOV · L-band radar',
    res: '6.5 m',
    window: 'Aug 2026',
    // NISAR swaths are wide; representative footprint, orbit-tilted.
    footprint: { w: 0.42, h: 0.52, rot: -9 },
    steps: [
      { type: 'agent', txt: 'The Kosi floodplain is the area of interest. Resolve it to a bounding box first.' },
      { type: 'tool', fn: 'resolve_location', args: [['name', '"Kosi River, Bihar"', 'n']],
        result: [
          '{ found: <s>true</s>,',
          '&nbsp;&nbsp;name: <s>"Kosi River, Bihar, India"</s>,',
          '&nbsp;&nbsp;lat: <n>25.500</n>, lon: <n>86.950</n>,',
          '&nbsp;&nbsp;bbox: { minx: <n>86.750</n>, miny: <n>25.300</n>, maxx: <n>87.150</n>, maxy: <n>25.700</n> } }'
        ] },
      { type: 'agent', txt: 'NISAR is the NASA\u2013ISRO L-band radar mission \u2014 open data, and it sees through monsoon cloud. Its archive opens August 2026, so I search that window.' },
      { type: 'tool', fn: 'search_scenes',
        args: [['satellite', '"NISAR"', 'n'], ['start_date', '"2026-08-01"', 's'], ['end_date', '"2026-08-31"', 's'], ['bbox', '86.75,25.30,87.15,25.70', 'n']],
        matched: 'NISAR',
        token: 'NISAR_SSAR_GCOV',
        scenes: [
          { id: 'NISAR_GCOV_20260809_A', dop: '2026-08-09', lat: 25.38, lon: 86.83, st: 'Ready' },
          { id: 'NISAR_GCOV_20260816_B', dop: '2026-08-16', lat: 25.46, lon: 86.98, st: 'Ready' },
          { id: 'NISAR_GCOV_20260821_C', dop: '2026-08-21', lat: 25.55, lon: 86.90, st: 'Archived' },
          { id: 'NISAR_GCOV_20260828_D', dop: '2026-08-28', lat: 25.62, lon: 87.05, st: 'Ready' }
        ],
        summary: [['Ready', '3 Ready'], ['Archived', '1 Archived']],
        total: 4 },
      { type: 'agent', txt: 'Four scenes, three Ready to pull now. I\u2019ll save the search so it has a slug, then download the Ready ones.' },
      { type: 'tool', fn: 'save_query',
        args: [['satellite', '"NISAR"', 'n'], ['name', '"kosi-nisar-aug26"', 's']],
        result: [
          '{ status: <s>"ok"</s>,',
          '&nbsp;&nbsp;slug: <s>"kosi-nisar-aug26"</s>, saved: <n>4</n> scenes }'
        ] },
      { type: 'agent', txt: 'Downloads need your Bhoonidhi login. Checking the session before I start.' },
      { type: 'tool', fn: 'auth_status', args: [],
        result: [
          '{ authenticated: <s>true</s>, username: <s>"you@example.org"</s> }'
        ] },
      { type: 'download', fn: 'download_query',
        args: [['slug', '"kosi-nisar-aug26"', 's'], ['select', '"Ready"', 's']],
        job: 'dl_7fa2',
        totalMb: 2140,
        files: 3,
        result: [
          '{ job_id: <s>"dl_7fa2"</s>, started: <n>3</n> Ready scenes,',
          '&nbsp;&nbsp;skipped: <n>1</n> Archived (request first), root: <s>"~/Downloads/kosi-nisar-aug26"</s> }'
        ] },
      { type: 'answer', html: '<b>Download complete</b> \u2014 3 NISAR GCOV scenes (\u2248 2.1 GB) landed in <span class="mono">~/Downloads/kosi-nisar-aug26</span>, each checksum-verified. The 1 Archived scene was skipped; I can request it on the portal so it stages for next time.' }
    ]
  },
  {
    key: 'chilika',
    chip: '3 · Add priced data to cart',
    flow: 'Find priced data → stage the cart',
    prompt: 'Find Cartosat scenes over Chilika Lake in early 2025 and add them to my cart.',
    place: 'Chilika Lake, Odisha',
    bbox: { minx: 85.0934, miny: 19.4673, maxx: 85.6574, maxy: 19.9033 },
    center: [19.6853, 85.2504],
    sensor: 'PAN + MX · optical',
    res: '0.28–1.6 m',
    window: 'Jan–Mar 2025',
    // Cartosat is high-res with a narrow swath: small footprints, orbit-tilted.
    footprint: { w: 0.12, h: 0.16, rot: -14 },
    steps: [
      { type: 'agent', txt: 'Resolve Chilika Lake, then search. "Cartosat" names a family, so it expands to every Cartosat platform.' },
      { type: 'tool', fn: 'resolve_location', args: [['name', '"Chilika Lake"', 'n']],
        result: [
          '{ found: <s>true</s>,',
          '&nbsp;&nbsp;name: <s>"Chilika Lake, Puri, Odisha, India"</s>,',
          '&nbsp;&nbsp;lat: <n>19.685</n>, lon: <n>85.250</n>,',
          '&nbsp;&nbsp;bbox: { minx: <n>85.093</n>, miny: <n>19.467</n>, maxx: <n>85.657</n>, maxy: <n>19.903</n> } }'
        ] },
      { type: 'tool', fn: 'search_scenes',
        args: [['satellite', '"Cartosat"', 'n'], ['start_date', '"2025-01-01"', 's'], ['end_date', '"2025-03-31"', 's'], ['bbox', '85.09,19.47,85.66,19.90', 'n']],
        matched: 'CartoSat-2 · CartoSat-2S · CartoSat-3',
        token: 'CartoSat-3_PAN(SPOT)',
        scenes: [
          { id: 'C3_PAN_20250112_A', dop: '2025-01-12', lat: 19.60, lon: 85.30, st: 'Priced' },
          { id: 'C2S_MX_20250128_B', dop: '2025-01-28', lat: 19.70, lon: 85.40, st: 'Priced' },
          { id: 'C3_MX_20250214_C',  dop: '2025-02-14', lat: 19.55, lon: 85.20, st: 'OnOrder' },
          { id: 'C2S_PAN_20250305_D', dop: '2025-03-05', lat: 19.80, lon: 85.50, st: 'Priced' }
        ],
        summary: [['Priced', '6 Priced'], ['OnOrder', '2 On order']],
        total: 8 },
      { type: 'agent', txt: 'All high-resolution and commercial \u2014 none are free downloads, so downloading would skip them. For priced and on-order scenes the right move is the cart. Saving the search first for its slug.' },
      { type: 'tool', fn: 'save_query',
        args: [['satellite', '"Cartosat"', 'n'], ['name', '"chilika-cartosat-2025"', 's']],
        result: [
          '{ status: <s>"ok"</s>,',
          '&nbsp;&nbsp;slug: <s>"chilika-cartosat-2025"</s>, saved: <n>8</n> scenes }'
        ] },
      { type: 'cart', fn: 'cart_add',
        args: [['slug', '"chilika-cartosat-2025"', 's']],
        result: [
          '{ staged: <n>8</n>, routed: { priced: <n>6</n>, onorder: <n>2</n> }, failed: <n>0</n> }'
        ] },
      { type: 'answer', html: '<b>8 scenes staged to your cart</b> \u2014 6 to the priced cart, 2 to the on-order cart, each routed by its access type. The purchase itself happens on the Bhoonidhi Browse &amp; Order portal; the agent takes it right up to that step.' }
    ]
  }
];

window.CLIENTS = [
  { name: 'MCP Inspector',
    desc: 'A browser UI to click each tool and watch live responses. No client config — a good first check that the server runs.',
    code: '<span class="cm"># after: git clone + uv sync</span>\nnpx @modelcontextprotocol/inspector \\\n  /path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp',
    note: 'Start here to confirm the server handshakes before wiring a real client.' },
  { name: 'Claude Code',
    desc: 'Register it with the <code>claude</code> CLI. Inside a session, <code>/mcp</code> lists it as connected.',
    code: 'claude mcp add bhoonidhi -- \\\n  /path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp\n\n<span class="cm"># inside a claude session:</span>\n<span class="cm"># /mcp  ->  "bhoonidhi" connected</span>',
    note: 'Run inside a project directory to write a local .mcp.json, or add --scope user for global.' },
  { name: 'OpenCode',
    desc: 'Add a local server block to <code>~/.config/opencode/opencode.json</code>, then restart.',
    code: '{\n  <span class="str">"$schema"</span>: <span class="str">"https://opencode.ai/config.json"</span>,\n  <span class="str">"mcp"</span>: {\n    <span class="str">"bhoonidhi"</span>: {\n      <span class="str">"type"</span>: <span class="str">"local"</span>,\n      <span class="str">"command"</span>: [<span class="str">"/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp"</span>],\n      <span class="str">"enabled"</span>: <span class="kw">true</span>\n    }\n  }\n}',
    note: 'Use the absolute path to the entry point in the project\u2019s .venv — most reliable across clients.' },
  { name: 'Claude Desktop',
    desc: 'Edit <code>claude_desktop_config.json</code> (create it if missing), then fully quit and relaunch. Tools appear under the plug icon.',
    code: '{\n  <span class="str">"mcpServers"</span>: {\n    <span class="str">"bhoonidhi"</span>: {\n      <span class="str">"command"</span>: <span class="str">"/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp"</span>,\n      <span class="str">"args"</span>: []\n    }\n  }\n}',
    note: 'GUI apps often miss your shell PATH, so point at the absolute path to the entry point.' },
  { name: 'Any stdio client',
    desc: 'The same shape works across MCP clients: a named server with a command and empty args.',
    code: '{\n  <span class="str">"mcpServers"</span>: {\n    <span class="str">"bhoonidhi"</span>: {\n      <span class="str">"command"</span>: <span class="str">"/path/to/bhoonidhi-mcp/.venv/bin/bhoonidhi-mcp"</span>,\n      <span class="str">"args"</span>: []\n    }\n  }\n}',
    note: 'Downloads and cart also need a Bhoonidhi login — run bhd auth login once, out of band.' }
];
