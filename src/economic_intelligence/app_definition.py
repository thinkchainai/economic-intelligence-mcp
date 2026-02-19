"""Economic Intelligence MCP App — pure Python config, no custom JS/CSS."""

from mcpbundles_app_ui import App, Card, DarkTheme


class EconomicIntelligenceApp(App):
    """Interactive economic dashboard — tabbed engine and views from library."""

    name = "Economic Intelligence"
    subtitle = "Live data from FRED, BLS, Treasury & FDIC"
    theme = DarkTheme(
        accent="#3b82f6",
        bg_page="#0f172a",
        bg_card="#1e293b",
        bg_hover="#253048",
        text_primary="#f1f5f9",
        text_secondary="#e2e8f0",
        text_muted="#94a3b8",
        border="#334155",
        success="#10b981",
        warning="#f59e0b",
        error="#ef4444",
        chart_colors=[
            "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
            "#8b5cf6", "#06b6d4", "#f97316", "#ec4899",
            "#14b8a6", "#a855f7",
        ],
    )

    layout = [Card(title="")]

    tool_name = "open_economic_app"
    tabs = [
        {"id": "overview", "label": "Overview", "tool": "open_economic_app", "type": "dashboard"},
        {"id": "rates", "label": "Rates", "tool": "econ_interest_rates", "type": "chart", "hasPeriod": True},
        {"id": "inflation", "label": "Inflation", "tool": "econ_inflation", "type": "chart", "hasPeriod": True},
        {"id": "jobs", "label": "Jobs", "tool": "econ_jobs", "type": "chart", "hasPeriod": True},
        {"id": "housing", "label": "Housing", "tool": "econ_housing", "type": "chart", "hasPeriod": True},
        {"id": "gdp", "label": "GDP", "tool": "econ_gdp", "type": "chart", "hasPeriod": True},
        {"id": "treasury", "label": "Treasury", "tool": "econ_treasury", "type": "chart", "hasPeriod": True},
        {"id": "banking", "label": "Banking", "tool": "econ_bank_health", "type": "banking", "defaultArgs": {"years": 5}},
        {
            "id": "compare", "label": "Compare", "tool": "econ_compare", "type": "chart",
            "hasPeriod": True, "needsArgs": True,
            "promptTitle": "Compare any two FRED series side by side",
            "promptHint": 'Ask your AI \u2014 e.g., "compare unemployment and inflation"',
        },
        {
            "id": "search", "label": "Search", "tool": "econ_search", "type": "search",
            "needsArgs": True,
            "searchPlaceholder": "Search for economic data (e.g., mortgage rate, oil price)...",
        },
        {"id": "tools", "label": "Tools", "tool": None, "type": "tools"},
    ]
    periods = ["1y", "2y", "5y", "10y", "20y"]
    default_period = "5y"
    footer_text = "FRED \u00b7 BLS \u00b7 Treasury \u00b7 FDIC"

    tool_catalog_intro = (
        "This server provides <strong>13 tools</strong> your AI can call directly. "
        "One opens this interactive app, 9 fetch live data from public APIs, and 3 are <strong>stateful</strong> \u2014 "
        "they track how signals change over time using a local database with 12-month historical backfill. "
        "All tools are <strong>read-only</strong>. "
        'Periods accept values like <code>1y</code>, <code>2y</code>, <code>5y</code>, <code>10y</code>, <code>20y</code>.'
    )
    tool_catalog = [
        {"name": "open_economic_app", "label": "Open Economic App", "icon": "\U0001f4ca", "desc": "Opens this interactive dashboard with recession probability, signal analysis, and data explorer.", "usage": "No arguments needed \u2014 just call it.", "source": "FRED + BLS + Treasury + FDIC"},
        {"name": "econ_interest_rates", "label": "Interest Rates", "icon": "\U0001f4c8", "desc": "Fed funds rate, 10-year & 30-year treasury yields, 30-year mortgage rate, and yield curve.", "usage": 'econ_interest_rates(period="5y")', "source": "FRED"},
        {"name": "econ_inflation", "label": "Inflation", "icon": "\U0001f4b9", "desc": "CPI, PCE, and core inflation with year-over-year change calculations.", "usage": 'econ_inflation(period="5y")', "source": "FRED"},
        {"name": "econ_jobs", "label": "Employment", "icon": "\U0001f477", "desc": "Unemployment rate, nonfarm payrolls, wage growth, and job openings (JOLTS).", "usage": 'econ_jobs(period="5y")', "source": "FRED / BLS"},
        {"name": "econ_housing", "label": "Housing", "icon": "\U0001f3e0", "desc": "Housing starts, permits, Case-Shiller home prices, mortgage rates, and affordability scoring.", "usage": 'econ_housing(period="5y")', "source": "FRED"},
        {"name": "econ_gdp", "label": "GDP", "icon": "\U0001f3db\ufe0f", "desc": "Nominal GDP, real GDP, and annualized growth rate.", "usage": 'econ_gdp(period="10y")', "source": "FRED / BEA"},
        {"name": "econ_treasury", "label": "Treasury & Debt", "icon": "\U0001f3e6", "desc": "Treasury yields, yield spreads, and total federal public debt.", "usage": 'econ_treasury(period="5y")', "source": "Treasury Fiscal Data"},
        {"name": "econ_bank_health", "label": "Banking Health", "icon": "\U0001f3e7", "desc": "FDIC bank health indicators \u2014 total institutions, problem banks, capital ratios, and recent failure history.", "usage": "econ_bank_health(years=5)", "source": "FDIC"},
        {"name": "econ_compare", "label": "Compare Series", "icon": "\u2696\ufe0f", "desc": "Compare any two FRED series side by side with correlation analysis.", "usage": 'econ_compare(series_a="UNRATE", series_b="CPIAUCSL", period="5y")', "source": "FRED"},
        {"name": "econ_search", "label": "Search FRED", "icon": "\U0001f50d", "desc": "Search across 800,000+ FRED series by keyword.", "usage": 'econ_search(query="mortgage rate", limit=20)', "source": "FRED"},
        {"name": "econ_signal_history", "label": "Signal History", "icon": "\U0001f4c9", "desc": "How economic signals have changed over time. Backfilled 12 months on first run, updated every 6 hours. Tracks yield curve, jobs/inflation divergence, bank stress, and recession probability.", "usage": 'econ_signal_history(signal_name="", months=12)', "source": "Local SQLite (computed)", "stateful": True},
        {"name": "econ_changes", "label": "Recent Changes", "icon": "\U0001f504", "desc": "What shifted since a given date \u2014 compares latest signal values to prior snapshots. Surfaces significant score changes across all tracked signals.", "usage": "econ_changes(since_days=7)", "source": "Local SQLite (computed)", "stateful": True},
        {"name": "econ_alerts", "label": "Alerts", "icon": "\U0001f6a8", "desc": "Active economic alerts \u2014 threshold crossings (signals above 60% or below 30%), trend reversals (3+ month trend then reversal), and recession probability shifts.", "usage": "econ_alerts()", "source": "Local SQLite (computed)", "stateful": True},
    ]
