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
// ESA open data (Sentinel-1, Sentinel-2, Landsat) is ALWAYS Ready or Archived —
// never OnOrder/Priced. Only commercial missions (e.g. Cartosat) are priced.
window.RUNS = [
  {
    key: 'shillong',
    chip: 'Sentinel-2 · Shillong',
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
      { type: 'answer', html: '<b>12 Sentinel-2 scenes</b> over Shillong in that window. <b>5 are Ready</b> to download; the other 7 are Archived open data you request first.' }
    ]
  },
  {
    key: 'loktak',
    chip: 'Sentinel-1 · Loktak Lake',
    prompt: 'Any Sentinel-1 radar over Loktak Lake in early 2024?',
    place: 'Loktak Lake, Manipur',
    bbox: { minx: 93.7633, miny: 24.5045, maxx: 93.8614, maxy: 24.6139 },
    center: [24.5584, 93.8132],
    sensor: 'SAR IW · radar',
    res: '20 m',
    window: 'Jan–Mar 2024',
    // Sentinel-1 IW swaths are wide; representative footprint, orbit-tilted.
    footprint: { w: 0.46, h: 0.58, rot: -8 },
    steps: [
      { type: 'agent', txt: 'Loktak Lake resolves to a small area in Manipur.' },
      { type: 'tool', fn: 'resolve_location', args: [['name', '"Loktak Lake"', 'n']],
        result: [
          '{ found: <s>true</s>,',
          '&nbsp;&nbsp;name: <s>"Loktak Lake, Bishnupur, Manipur, India"</s>,',
          '&nbsp;&nbsp;lat: <n>24.558</n>, lon: <n>93.813</n>,',
          '&nbsp;&nbsp;bbox: { minx: <n>93.763</n>, miny: <n>24.504</n>, maxx: <n>93.861</n>, maxy: <n>24.614</n> } }'
        ] },
      { type: 'agent', txt: 'Radar sees through cloud, which suits a monsoon wetland. In early 2024 only Sentinel-1A is flying, so only its scenes come back.' },
      { type: 'tool', fn: 'search_scenes',
        args: [['satellite', '"Sentinel-1"', 'n'], ['start_date', '"2024-01-01"', 's'], ['end_date', '"2024-03-31"', 's'], ['bbox', '93.76,24.50,93.86,24.61', 'n']],
        matched: 'Sentinel-1A · Sentinel-1B · Sentinel-1C · Sentinel-1D',
        token: 'Sentinel-1A_SAR(IW)_GRD',
        scenes: [
          { id: 'S1A_IW_GRDH_20240112T121', dop: '2024-01-12', lat: 24.52, lon: 93.78, st: 'Ready' },
          { id: 'S1A_IW_GRDH_20240205T121', dop: '2024-02-05', lat: 24.55, lon: 93.82, st: 'Archived' },
          { id: 'S1A_IW_GRDH_20240229T121', dop: '2024-02-29', lat: 24.58, lon: 93.80, st: 'Ready' },
          { id: 'S1A_IW_GRDH_20240324T121', dop: '2024-03-24', lat: 24.60, lon: 93.85, st: 'Archived' }
        ],
        summary: [['Ready', '3 Ready'], ['Archived', '3 Archived']],
        total: 6 },
      { type: 'answer', html: '<b>6 Sentinel-1 radar scenes</b> over Loktak Lake. As ESA open data, every scene is either <b>Ready</b> to download or <b>Archived</b> (request it first if it 404s) — nothing to pay for.' }
    ]
  },
  {
    key: 'chilika',
    chip: 'Cartosat · Chilika Lake',
    prompt: 'Cartosat scenes over Chilika Lake in early 2025.',
    place: 'Chilika Lake, Odisha',
    bbox: { minx: 85.0934, miny: 19.4673, maxx: 85.6574, maxy: 19.9033 },
    center: [19.6853, 85.2504],
    sensor: 'PAN + MX · optical',
    res: '0.28–1.6 m',
    window: 'Jan–Mar 2025',
    // Cartosat is high-res with a narrow swath: small footprints, orbit-tilted.
    footprint: { w: 0.12, h: 0.16, rot: -14 },
    steps: [
      { type: 'agent', txt: '"Cartosat" names a family. It expands to every Cartosat platform the portal lists.' },
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
      { type: 'answer', html: '<b>8 Cartosat scenes</b> over Chilika Lake — all high-resolution and <b>Priced</b>, so none are free downloads. The availability field says so before you try.' }
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
