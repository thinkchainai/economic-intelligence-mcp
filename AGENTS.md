# Economic Intelligence MCP — Agent Instructions

## What This Is

An MCP App Server for economic data. 13 tools — 1 interactive app, 9 live API tools, 3 stateful signal-tracking tools. Built with FastMCP (Python). Runs locally with a SQLite database for signal history.

## Architecture

```
src/economic_intelligence/
├── server.py          # FastMCP server — all 13 tool definitions + MCP App resource
├── db.py              # SQLite engine (aiosqlite, WAL mode, ~/.economic-mcp/data.db)
├── sqlmodels.py       # SQLAlchemy models: SignalSnapshot, RecessionSnapshot, IngestionMeta
├── ingestors.py       # Signal engine — backfill, refresh, history queries, change detection, alerts
├── scheduler.py       # Background scheduler — backfill on first run, refresh every 6 hours
├── core/
│   ├── models.py      # Pydantic business objects (EconomicSeries, ScoredSignal, RecessionProbability, etc.)
│   ├── scoring.py     # Scoring algorithms (yield curve, jobs/inflation, housing, bank stress, recession probability)
│   └── clients/
│       ├── fred.py    # FRED API client (800K+ series, rate/inflation/jobs/housing/GDP)
│       ├── bls.py     # BLS API client (employment, wages)
│       ├── treasury.py # Treasury Fiscal Data client (rates, federal debt)
│       └── fdic.py    # FDIC API client (bank health, failures)
└── ui/
    └── app.html       # Single-page MCP App — tabbed dashboard, inline canvas charts, no external dependencies
```

## Key Patterns

### Tools
- All tools are defined in `server.py` using `@mcp.tool(annotations=READ_ONLY)`.
- Only `open_economic_app` has `meta={"ui": {"resourceUri": APP_RESOURCE_URI}}` — this makes it the single interactive tool.
- The other 12 tools return plain dicts (auto-serialized to JSON by FastMCP).
- Tool annotations: all tools use `READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)`.

### MCP App UI
- One HTML file (`ui/app.html`) — fully self-contained, zero external dependencies.
- Charts rendered with inline canvas (no Chart.js CDN — blocked in iframe sandbox).
- Height managed by `ResizeObserver` sending `ui/notifications/size-changed` to the host.
- MCP client protocol: `ui/initialize` → `ui/notifications/initialized` → `tools/call` → `ui/notifications/tool-result`.
- Resource declared with `mime_type="text/html;profile=mcp-app"`.

### Signal History (Stateful)
- On first startup, `ingestors.py:run_backfill()` fetches 3 years of FRED data and computes signals at monthly intervals going back 12 months.
- Only computed signals are stored (not raw observations). Schema: `SignalSnapshot` (name, score, summary, tags, data_as_of) and `RecessionSnapshot` (probability, assessment, spread, trend).
- `IngestionMeta` table tracks backfill state — `backfill_complete` key prevents re-running.
- Scheduler refreshes every 6 hours via `run_refresh()`.
- Three stateful tools query the database: `econ_signal_history`, `econ_changes`, `econ_alerts`.

### API Clients
- All clients use `httpx.AsyncClient` with explicit timeouts.
- FRED requires `FRED_API_KEY` env var. BLS key is optional. Treasury and FDIC need no auth.
- `fred.py` has a `SERIES_CATALOG` mapping well-known series IDs to metadata.
- Period parsing: `_parse_period("5y")` → date 5 years ago. Supports `y`, `m`, `d` suffixes.

### Scoring
- `scoring.py` contains the cross-source analysis functions.
- Each scorer takes `EconomicSeries` objects and returns `ScoredSignal` (score 0.0–1.0).
- `compute_recession_probability()` does weighted averaging across signal categories.
- Scores are deterministic given the same input data — no randomness.

## Code Quality Rules
- No TODOs — everything is production-ready.
- No `print()` — use `logger = logging.getLogger(__name__)`.
- Imports at the top of files. Order: stdlib → third-party → local.
- SQLite upserts use `index_elements=` (not `constraint=` — that's PostgreSQL-only).
- All tools return dicts, not strings. FastMCP handles serialization.
- Error handling: `ToolError` for MCP tool errors, `httpx.HTTPError` for API failures.

## Dependencies
- `httpx` — async HTTP client for all API calls
- `pydantic` — data models and validation
- `sqlalchemy` + `aiosqlite` + `greenlet` — async SQLite for signal storage
- `mcp[cli]` — FastMCP framework

## Building
- `./build-mcpb.sh` — packs into `.mcpb` for Claude Desktop
- `.mcpbignore` excludes `.venv`, `.git`, `__pycache__`, `*.png`, `.github`
- `manifest.json` declares env vars (`FRED_API_KEY` required, `BLS_API_KEY` optional)

## Adding a New Tool
1. Add the tool function in `server.py` with `@mcp.tool(annotations=READ_ONLY)`.
2. If it needs a new API client, add it in `core/clients/`.
3. If it needs a new scoring function, add it in `core/scoring.py`.
4. Update `TOOL_CATALOG` in `ui/app.html` for the Tools tab.
5. Run `./build-mcpb.sh` to rebuild.

## Adding a New Signal
1. Create the scoring function in `core/scoring.py` returning `ScoredSignal`.
2. Call it from `ingestors.py:run_backfill()` and `run_refresh()`.
3. It will automatically appear in `econ_signal_history`, `econ_changes`, and `econ_alerts`.
