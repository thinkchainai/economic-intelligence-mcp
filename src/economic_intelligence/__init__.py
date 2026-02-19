"""Economic Intelligence MCP App Server.

Ask your AI about the economy — interest rates, jobs, inflation, housing, bank health.
Interactive charts and cross-source analysis from FRED, BLS, Treasury, and FDIC data.
"""

__version__ = "0.1.0"

from .app_definition import EconomicIntelligenceApp


def get_app_html() -> str:
    """Return the MCP App HTML content. Re-renders each call for hot reload."""
    return EconomicIntelligenceApp().render()
