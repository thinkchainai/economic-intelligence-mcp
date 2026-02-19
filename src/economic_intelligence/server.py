"""Economic Intelligence MCP App Server.

FastMCP server with 10 tools and MCP Apps interactive UI.
Run: economic-intelligence-mcp
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import AsyncIterator, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import get_app_html
from .core.clients import bls, fdic, fred, treasury
from .core.models import DataSource
from .core.scoring import (
    compute_recession_probability,
    score_bank_stress,
    score_housing_affordability,
    score_jobs_inflation_divergence,
    score_yield_curve,
)
from .db import close_db, init_db
from .ingestors import detect_alerts, detect_changes, get_recession_history, get_signal_history
from .scheduler import SignalScheduler

logger = logging.getLogger(__name__)

MCP_APP_MIME = "text/html;profile=mcp-app"

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

scheduler = SignalScheduler()


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[None]:
    """Initialize database, backfill signal history on first run, start refresh scheduler."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    await init_db()
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()
        await close_db()


mcp = FastMCP(
    "Economic Intelligence",
    instructions="Ask your AI about the economy — interest rates, jobs, inflation, housing, bank health. Interactive charts and cross-source analysis from FRED, BLS, Treasury, and FDIC data.",
    lifespan=lifespan,
)


def _get_fred_key() -> str:
    key = os.environ.get("FRED_API_KEY", "")
    if not key:
        raise ValueError("FRED_API_KEY environment variable is required. Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html")
    return key


def _series_to_chart_data(series_list: list) -> list[dict]:
    """Convert EconomicSeries list to chart-friendly JSON."""
    chart_data = []
    for s in series_list:
        chart_data.append({
            "series_id": s.metadata.series_id,
            "title": s.metadata.title,
            "units": s.metadata.units,
            "data": [{"date": o.date.isoformat(), "value": o.value} for o in sorted(s.observations, key=lambda o: o.date)],
        })
    return chart_data


# ─── MCP Apps UI Resource ─────────────────────────────────────────────────────

APP_RESOURCE_URI = "ui://economic-mcp/app"


@mcp.resource(
    APP_RESOURCE_URI,
    mime_type=MCP_APP_MIME,
)
def app_ui() -> str:
    """Economic Intelligence — interactive charts, dashboard, and search."""
    return get_app_html()


# ─── Tool 1: Interest Rates ──────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_interest_rates(period: str = "5y") -> dict:
    """Current and historical interest rates — Fed funds, 10Y/30Y treasury, mortgage rates, and yield curve.

    Args:
        period: Lookback period. Examples: '1y', '2y', '5y', '10y'. Default '5y'.
    """
    api_key = _get_fred_key()
    series = await fred.fetch_rate_series(api_key, period)
    return {
        "title": "Interest Rates",
        "period": period,
        "series": _series_to_chart_data(series),
        "summary": _rates_summary(series),
    }


def _rates_summary(series_list: list) -> str:
    parts = []
    for s in series_list:
        if s.latest:
            parts.append(f"{s.metadata.title}: {s.latest.value:.2f}%")
    return " | ".join(parts) if parts else "No data available"


# ─── Tool 2: Inflation ───────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_inflation(period: str = "5y") -> dict:
    """CPI, PCE, and core inflation trends.

    Args:
        period: Lookback period. Examples: '1y', '2y', '5y'. Default '5y'.
    """
    api_key = _get_fred_key()
    series = await fred.fetch_inflation_series(api_key, period)

    yoy_changes = {}
    for s in series:
        changes = s.pct_change(periods=12)
        if changes:
            yoy_changes[s.metadata.series_id] = changes[-1][1]

    return {
        "title": "Inflation",
        "period": period,
        "series": _series_to_chart_data(series),
        "year_over_year": yoy_changes,
        "summary": _inflation_summary(series, yoy_changes),
    }


def _inflation_summary(series_list: list, yoy: dict) -> str:
    parts = []
    for s in series_list:
        sid = s.metadata.series_id
        if sid in yoy:
            parts.append(f"{s.metadata.title}: {yoy[sid]:.1f}% YoY")
    return " | ".join(parts) if parts else "No data available"


# ─── Tool 3: Jobs ────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_jobs(period: str = "5y") -> dict:
    """Employment data — unemployment rate, nonfarm payrolls, wage growth, job openings.

    Args:
        period: Lookback period. Examples: '1y', '2y', '5y'. Default '5y'.
    """
    api_key = _get_fred_key()
    series = await fred.fetch_employment_series(api_key, period)
    return {
        "title": "Employment",
        "period": period,
        "series": _series_to_chart_data(series),
        "summary": _jobs_summary(series),
    }


def _jobs_summary(series_list: list) -> str:
    parts = []
    for s in series_list:
        if s.latest:
            if "Rate" in s.metadata.title or "Percent" in s.metadata.units:
                parts.append(f"{s.metadata.title}: {s.latest.value:.1f}%")
            elif "Thousands" in s.metadata.units:
                parts.append(f"{s.metadata.title}: {s.latest.value:,.0f}K")
            else:
                parts.append(f"{s.metadata.title}: {s.latest.value:,.2f}")
    return " | ".join(parts) if parts else "No data available"


# ─── Tool 4: Housing ─────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_housing(period: str = "5y") -> dict:
    """Housing data — starts, permits, home prices, mortgage rates, inventory.

    Args:
        period: Lookback period. Examples: '1y', '2y', '5y', '10y'. Default '5y'.
    """
    api_key = _get_fred_key()
    housing = await fred.fetch_housing_series(api_key, period)
    mortgage = await fred.fetch_series("MORTGAGE30US", api_key, period)

    home_prices = next((s for s in housing if s.metadata.series_id == "CSUSHPISA"), None)
    affordability = score_housing_affordability(home_prices, mortgage)

    return {
        "title": "Housing",
        "period": period,
        "series": _series_to_chart_data(housing + [mortgage]),
        "affordability": affordability.model_dump(),
        "summary": affordability.assessment,
    }


# ─── Tool 5: Bank Health ─────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_bank_health(years: int = 5) -> dict:
    """FDIC bank health indicators — capital ratios, problem bank count, failure history.

    Args:
        years: How many years of failure history to include. Default 5.
    """
    health = await fdic.fetch_bank_health_summary()
    failures = await fdic.fetch_recent_failures(years)

    return {
        "title": "Banking System Health",
        "health_summary": health.model_dump(),
        "recent_failures": failures[:20],
        "failure_count": len(failures),
        "summary": health.assessment,
    }


# ─── Tool 6: GDP ─────────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_gdp(period: str = "10y") -> dict:
    """GDP growth — nominal, real, and annualized growth rate.

    Args:
        period: Lookback period. Examples: '5y', '10y', '20y'. Default '10y'.
    """
    api_key = _get_fred_key()
    series = await fred.fetch_gdp_series(api_key, period)
    return {
        "title": "Gross Domestic Product",
        "period": period,
        "series": _series_to_chart_data(series),
        "summary": _gdp_summary(series),
    }


def _gdp_summary(series_list: list) -> str:
    growth = next((s for s in series_list if s.metadata.series_id == "A191RL1Q225SBEA"), None)
    if growth and growth.latest:
        return f"Latest real GDP growth: {growth.latest.value:.1f}% (annualized)"
    return "GDP data available"


# ─── Tool 7: Treasury ────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_treasury(period: str = "5y") -> dict:
    """Treasury rates, yield spreads, and federal debt levels.

    Args:
        period: Lookback period. Examples: '1y', '5y', '10y'. Default '5y'.
    """
    rates = await treasury.fetch_treasury_rates(period)
    debt = await treasury.fetch_federal_debt(period)

    return {
        "title": "Treasury & Federal Debt",
        "period": period,
        "series": _series_to_chart_data(rates + [debt]),
        "summary": _treasury_summary(debt),
    }


def _treasury_summary(debt) -> str:
    if debt.latest:
        trillions = debt.latest.value / 1_000_000_000_000
        return f"Total public debt: ${trillions:.2f} trillion as of {debt.latest.date}"
    return "Treasury data available"


# ─── Tool 8: Open MCP App (Interactive UI) ──────────────────────────────────


@mcp.tool(annotations=READ_ONLY, meta={"ui": {"resourceUri": APP_RESOURCE_URI}})
async def open_economic_app() -> dict:
    """Open the Economic Intelligence app — interactive charts, recession gauge, signals, search, and data explorer."""
    api_key = _get_fred_key()

    spread = await fred.fetch_series("T10Y2Y", api_key, "2y")
    unemployment = await fred.fetch_series("UNRATE", api_key, "2y")
    cpi = await fred.fetch_series("CPIAUCSL", api_key, "2y")
    bank_health = await fdic.fetch_bank_health_summary()

    signals = []
    yield_signal = score_yield_curve(spread)
    if yield_signal:
        signals.append(yield_signal)

    jobs_signal = score_jobs_inflation_divergence(unemployment, cpi)
    if jobs_signal:
        signals.append(jobs_signal)

    bank_signal = score_bank_stress(bank_health)
    signals.append(bank_signal)

    spread_value = spread.latest.value if spread.latest else None
    recession = compute_recession_probability(signals, spread_value, unemployment)

    return {
        "title": "Economic Outlook",
        "recession_probability": recession.model_dump(mode="json"),
        "signals": [s.model_dump(mode="json") for s in signals],
        "summary": recession.assessment,
    }


# ─── Tool 9: Compare ─────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_compare(series_a: str, series_b: str, period: str = "5y") -> dict:
    """Compare any two economic data series on the same chart.

    Args:
        series_a: First FRED series ID (e.g., 'UNRATE', 'CPIAUCSL', 'DGS10').
        series_b: Second FRED series ID.
        period: Lookback period. Default '5y'.
    """
    api_key = _get_fred_key()
    sa = await fred.fetch_series(series_a, api_key, period)
    sb = await fred.fetch_series(series_b, api_key, period)

    # Compute correlation over overlapping dates
    dates_a = {o.date: o.value for o in sa.observations}
    dates_b = {o.date: o.value for o in sb.observations}
    overlap = sorted(set(dates_a.keys()) & set(dates_b.keys()))

    correlation = None
    if len(overlap) >= 10:
        vals_a = [dates_a[d] for d in overlap]
        vals_b = [dates_b[d] for d in overlap]
        correlation = _pearson_correlation(vals_a, vals_b)

    return {
        "title": f"{sa.metadata.title} vs {sb.metadata.title}",
        "period": period,
        "series": _series_to_chart_data([sa, sb]),
        "correlation": round(correlation, 4) if correlation is not None else None,
        "overlapping_observations": len(overlap),
        "summary": f"Comparing {sa.metadata.title} ({sa.metadata.units}) with {sb.metadata.title} ({sb.metadata.units}) over {period}."
        + (f" Correlation: {correlation:.3f}" if correlation is not None else ""),
    }


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / n
    std_x = (sum((a - mean_x) ** 2 for a in x) / n) ** 0.5
    std_y = (sum((b - mean_y) ** 2 for b in y) / n) ** 0.5
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


# ─── Tool 10: Search ─────────────────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_search(query: str, limit: int = 20) -> dict:
    """Search FRED for any economic data series by keyword.

    Args:
        query: Search term (e.g., 'mortgage rate', 'unemployment california', 'oil price').
        limit: Maximum number of results. Default 20.
    """
    api_key = _get_fred_key()
    results = await fred.search_series(query, api_key, limit)
    return {
        "query": query,
        "results": results,
        "count": len(results),
        "summary": f"Found {len(results)} FRED series matching '{query}'",
    }


# ─── Tool 11: Signal History (Stateful) ─────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_signal_history(signal_name: str = "", months: int = 12) -> dict:
    """How economic signals have changed over time — tracked locally with historical backfill.

    Returns score history for yield curve, jobs/inflation divergence, bank stress,
    and composite recession probability. Data is backfilled 12 months on first run.

    Args:
        signal_name: Filter to a specific signal (e.g., 'yield_curve_signal',
                     'jobs_vs._inflation_divergence', 'banking_system_stress').
                     Leave empty for all signals.
        months: How many months of history. Default 12.
    """
    signals = await get_signal_history(
        signal_name=signal_name if signal_name else None,
        months=months,
    )
    recession = await get_recession_history(months=months)

    unique_signals = list({s["signal_name"] for s in signals})

    return {
        "title": "Signal History",
        "signal_snapshots": signals,
        "recession_history": recession,
        "unique_signals": unique_signals,
        "snapshot_count": len(signals),
        "recession_snapshot_count": len(recession),
        "months": months,
        "summary": f"{len(signals)} signal snapshots and {len(recession)} recession snapshots over {months} months. "
        + (f"Signals tracked: {', '.join(unique_signals)}." if unique_signals else "No signal history yet — backfill may still be running."),
    }


# ─── Tool 12: Changes (Stateful) ────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_changes(since_days: int = 7) -> dict:
    """What economic signals shifted recently — compares latest values to a prior snapshot.

    Args:
        since_days: Compare current signals to this many days ago. Default 7.
    """
    changes = await detect_changes(since_days=since_days)

    significant = [c for c in changes if c.get("change_type", "").startswith("significant")]
    any_changes = len(changes)

    if not changes:
        summary = f"No significant signal changes in the last {since_days} days."
    elif significant:
        summary = f"{len(significant)} significant change(s) detected in the last {since_days} days: " + ", ".join(c["title"] for c in significant) + "."
    else:
        summary = f"{any_changes} signal change(s) detected in the last {since_days} days, none significant."

    return {
        "title": "Signal Changes",
        "since_days": since_days,
        "changes": changes,
        "total_changes": any_changes,
        "significant_changes": len(significant),
        "summary": summary,
    }


# ─── Tool 13: Alerts (Stateful) ─────────────────────────────────────────────


@mcp.tool(annotations=READ_ONLY)
async def econ_alerts() -> dict:
    """Active economic alerts — threshold crossings, trend reversals, and recession probability shifts.

    Automatically generated from signal history. No arguments needed.
    """
    alerts = await detect_alerts()

    high = [a for a in alerts if a["severity"] == "high"]
    medium = [a for a in alerts if a["severity"] == "medium"]

    if not alerts:
        summary = "No active alerts. All signals are stable."
    elif high:
        summary = f"{len(high)} high-severity alert(s): " + "; ".join(a["message"] for a in high)
    else:
        summary = f"{len(alerts)} alert(s) — {len(medium)} medium, {len(alerts) - len(medium)} low severity."

    return {
        "title": "Economic Alerts",
        "alerts": alerts,
        "total_alerts": len(alerts),
        "high_severity": len(high),
        "medium_severity": len(medium),
        "low_severity": len(alerts) - len(high) - len(medium),
        "summary": summary,
    }


def main():
    """Entry point for the CLI command."""
    mcp.run()


if __name__ == "__main__":
    main()
