# Changelog

## 0.1.0 (2026-02-17)

Initial release.

### Tools (13 total)
- **open_economic_app** — interactive dashboard with tabbed navigation, recession gauge, signal cards
- **econ_interest_rates** — Fed funds, treasury yields, mortgage rates, yield curve
- **econ_inflation** — CPI, PCE, core inflation with YoY analysis
- **econ_jobs** — unemployment, payrolls, wage growth, job openings
- **econ_housing** — starts, permits, home prices, affordability index
- **econ_bank_health** — FDIC capital ratios, problem banks, failures
- **econ_gdp** — nominal, real, annualized growth
- **econ_treasury** — treasury rates, yield spreads, federal debt
- **econ_compare** — compare any two FRED series with correlation
- **econ_search** — search 800K+ FRED series
- **econ_signal_history** — signal scores over time with 12-month backfill
- **econ_changes** — recent signal shifts and significant score deltas
- **econ_alerts** — threshold crossings, trend reversals, recession probability shifts

### Cross-Source Scoring
- Yield curve inversion analysis
- Jobs vs. inflation divergence detection
- Housing affordability composite index
- Banking system stress score
- Composite recession probability

### MCP App UI
- Single-page tabbed interface (Overview, Rates, Inflation, Jobs, Housing, GDP, Treasury, Banking, Compare, Search, Tools)
- Inline canvas chart renderer (zero external dependencies)
- ResizeObserver-based auto-fit height
- Recession probability gauge
- Interactive signal cards
- Tools reference page

### Infrastructure
- `.mcpb` packaging for one-click Claude Desktop install
- SQLite signal storage with WAL mode
- 12-month historical backfill on first run
- 6-hour automatic signal refresh
- GitHub Actions release workflow
