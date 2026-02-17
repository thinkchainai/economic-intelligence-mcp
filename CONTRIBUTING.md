# Contributing

Thanks for your interest in contributing to Economic Intelligence MCP.

## Getting Started

```bash
git clone https://github.com/thinkchainai/economic-intelligence-mcp.git
cd economic-intelligence-mcp
python -m venv .venv && source .venv/bin/activate
pip install -e .
export FRED_API_KEY=your_key_here
economic-intelligence-mcp
```

## What We're Looking For

- **New scoring algorithms** — new cross-source signals beyond yield curve, jobs/inflation, bank stress
- **New data sources** — add clients in `src/economic_intelligence/core/clients/`
- **UI improvements** — the app is a single HTML file at `src/economic_intelligence/ui/app.html`
- **Bug fixes** — especially around API edge cases and data parsing
- **Documentation** — README, AGENTS.md, inline code comments

## How to Contribute

1. Fork the repo
2. Create a branch (`git checkout -b feature/my-change`)
3. Make your changes
4. Test locally by running the server and calling tools
5. Rebuild the `.mcpb` (`./build-mcpb.sh`)
6. Open a pull request

## Adding a New Tool

1. Add the tool function in `server.py` with `@mcp.tool(annotations=READ_ONLY)`
2. If it needs a new API client, add it in `core/clients/`
3. If it needs a new scoring function, add it in `core/scoring.py`
4. Update `TOOL_CATALOG` in `ui/app.html` for the Tools tab
5. Update `manifest.json` with the new tool entry

## Adding a New Signal

1. Create the scoring function in `core/scoring.py` returning `ScoredSignal`
2. Call it from `ingestors.py` in both `run_backfill()` and `run_refresh()`
3. It will automatically appear in `econ_signal_history`, `econ_changes`, and `econ_alerts`

## Code Style

- No TODOs — build it production-ready or don't build it
- No `print()` — use `logger = logging.getLogger(__name__)`
- Imports at the top: stdlib → third-party → local
- All tools return dicts, not strings
- Use `httpx.AsyncClient` with explicit timeouts for API calls

## Questions?

Open an issue or reach out at [mcpbundles.com](https://mcpbundles.com).
