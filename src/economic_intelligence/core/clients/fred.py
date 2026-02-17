"""FRED (Federal Reserve Economic Data) API client.

API docs: https://fred.stlouisfed.org/docs/api/fred/
Rate limit: 120 requests/minute with API key.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

import httpx

from ..models import (
    Category,
    DataPoint,
    DataSource,
    EconomicSeries,
    Frequency,
    SeriesMetadata,
)

logger = logging.getLogger(__name__)

API_BASE = "https://api.stlouisfed.org/fred"

# Well-known FRED series mapped to categories
SERIES_CATALOG: dict[str, dict] = {
    # Interest rates
    "FEDFUNDS": {"title": "Federal Funds Effective Rate", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.MONTHLY},
    "DFF": {"title": "Federal Funds Effective Rate (Daily)", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    "DGS2": {"title": "2-Year Treasury Constant Maturity Rate", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    "DGS10": {"title": "10-Year Treasury Constant Maturity Rate", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    "DGS30": {"title": "30-Year Treasury Constant Maturity Rate", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    "MORTGAGE30US": {"title": "30-Year Fixed Rate Mortgage Average", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.WEEKLY},
    "MORTGAGE15US": {"title": "15-Year Fixed Rate Mortgage Average", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.WEEKLY},
    "T10Y2Y": {"title": "10-Year Treasury Minus 2-Year Treasury", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    "T10Y3M": {"title": "10-Year Treasury Minus 3-Month Treasury", "category": Category.INTEREST_RATES, "units": "Percent", "frequency": Frequency.DAILY},
    # Inflation
    "CPIAUCSL": {"title": "Consumer Price Index (All Urban Consumers)", "category": Category.INFLATION, "units": "Index 1982-1984=100", "frequency": Frequency.MONTHLY},
    "CPILFESL": {"title": "Core CPI (Less Food and Energy)", "category": Category.INFLATION, "units": "Index 1982-1984=100", "frequency": Frequency.MONTHLY},
    "PCEPI": {"title": "Personal Consumption Expenditures Price Index", "category": Category.INFLATION, "units": "Index 2017=100", "frequency": Frequency.MONTHLY},
    "PCEPILFE": {"title": "Core PCE Price Index (Less Food and Energy)", "category": Category.INFLATION, "units": "Index 2017=100", "frequency": Frequency.MONTHLY},
    "MICH": {"title": "University of Michigan Inflation Expectations", "category": Category.INFLATION, "units": "Percent", "frequency": Frequency.MONTHLY},
    # Employment
    "UNRATE": {"title": "Unemployment Rate", "category": Category.EMPLOYMENT, "units": "Percent", "frequency": Frequency.MONTHLY},
    "PAYEMS": {"title": "All Employees, Total Nonfarm", "category": Category.EMPLOYMENT, "units": "Thousands of Persons", "frequency": Frequency.MONTHLY},
    "ICSA": {"title": "Initial Claims (Seasonally Adjusted)", "category": Category.EMPLOYMENT, "units": "Number", "frequency": Frequency.WEEKLY},
    "AHETPI": {"title": "Average Hourly Earnings (Private)", "category": Category.EMPLOYMENT, "units": "Dollars per Hour", "frequency": Frequency.MONTHLY},
    "JTSJOL": {"title": "Job Openings (JOLTS)", "category": Category.EMPLOYMENT, "units": "Thousands", "frequency": Frequency.MONTHLY},
    # Housing
    "HOUST": {"title": "Housing Starts", "category": Category.HOUSING, "units": "Thousands of Units", "frequency": Frequency.MONTHLY},
    "PERMIT": {"title": "New Privately-Owned Housing Units Authorized", "category": Category.HOUSING, "units": "Thousands of Units", "frequency": Frequency.MONTHLY},
    "CSUSHPISA": {"title": "S&P/Case-Shiller U.S. National Home Price Index", "category": Category.HOUSING, "units": "Index Jan 2000=100", "frequency": Frequency.MONTHLY},
    "MSPUS": {"title": "Median Sales Price of Houses Sold", "category": Category.HOUSING, "units": "Dollars", "frequency": Frequency.QUARTERLY},
    "MSACSR": {"title": "Monthly Supply of New Houses", "category": Category.HOUSING, "units": "Months' Supply", "frequency": Frequency.MONTHLY},
    # GDP
    "GDP": {"title": "Gross Domestic Product", "category": Category.GDP, "units": "Billions of Dollars", "frequency": Frequency.QUARTERLY},
    "GDPC1": {"title": "Real Gross Domestic Product", "category": Category.GDP, "units": "Billions of Chained 2017 Dollars", "frequency": Frequency.QUARTERLY},
    "A191RL1Q225SBEA": {"title": "Real GDP Growth Rate (Annualized)", "category": Category.GDP, "units": "Percent Change", "frequency": Frequency.QUARTERLY},
    # Leading indicators
    "UMCSENT": {"title": "University of Michigan Consumer Sentiment", "category": Category.LEADING_INDICATORS, "units": "Index 1966:Q1=100", "frequency": Frequency.MONTHLY},
    "USSLIND": {"title": "Leading Index for the United States", "category": Category.LEADING_INDICATORS, "units": "Percent", "frequency": Frequency.MONTHLY},
}

RATE_SERIES = ["FEDFUNDS", "DFF", "DGS2", "DGS10", "DGS30", "MORTGAGE30US", "MORTGAGE15US", "T10Y2Y", "T10Y3M"]
INFLATION_SERIES = ["CPIAUCSL", "CPILFESL", "PCEPI", "PCEPILFE", "MICH"]
EMPLOYMENT_SERIES = ["UNRATE", "PAYEMS", "ICSA", "AHETPI", "JTSJOL"]
HOUSING_SERIES = ["HOUST", "PERMIT", "CSUSHPISA", "MSPUS", "MSACSR"]
GDP_SERIES = ["GDP", "GDPC1", "A191RL1Q225SBEA"]


def _parse_period(period: str) -> date:
    """Convert period string like '1y', '5y', '6m', '30d' to a start date."""
    today = date.today()
    amount = int(period[:-1])
    unit = period[-1].lower()
    if unit == "y":
        return today.replace(year=today.year - amount)
    elif unit == "m":
        month = today.month - amount
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        return today.replace(year=year, month=month)
    elif unit == "d":
        from datetime import timedelta
        return today - timedelta(days=amount)
    raise ValueError(f"Invalid period format: {period}. Use '1y', '6m', '30d', etc.")


def _parse_observation(obs: dict) -> Optional[DataPoint]:
    """Parse a FRED API observation into a DataPoint."""
    value_str = obs.get("value", ".")
    if value_str == ".":
        return None
    try:
        return DataPoint(
            date=date.fromisoformat(obs["date"]),
            value=float(value_str),
        )
    except (ValueError, KeyError):
        return None


async def fetch_series(
    series_id: str,
    api_key: str,
    period: str = "5y",
    frequency: Optional[str] = None,
) -> EconomicSeries:
    """Fetch a FRED series with observations for the given period.

    Args:
        series_id: FRED series ID (e.g., 'FEDFUNDS', 'UNRATE').
        api_key: FRED API key.
        period: Lookback period ('1y', '5y', '6m', '30d').
        frequency: Optional aggregation frequency override.

    Returns:
        EconomicSeries with metadata and observations.
    """
    start_date = _parse_period(period)

    params: dict = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date.isoformat(),
        "sort_order": "asc",
    }
    if frequency:
        params["frequency"] = frequency

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/series/observations", params=params)
        response.raise_for_status()
        data = response.json()

    observations = []
    for obs in data.get("observations", []):
        point = _parse_observation(obs)
        if point is not None:
            observations.append(point)

    catalog_entry = SERIES_CATALOG.get(series_id)
    if catalog_entry:
        metadata = SeriesMetadata(
            series_id=series_id,
            title=catalog_entry["title"],
            source=DataSource.FRED,
            category=catalog_entry["category"],
            frequency=catalog_entry["frequency"],
            units=catalog_entry["units"],
            seasonal_adjustment="Seasonally Adjusted" if series_id.endswith("SL") or series_id.endswith("SA") else "Not Seasonally Adjusted",
        )
    else:
        series_resp = await _fetch_series_info(series_id, api_key)
        metadata = SeriesMetadata(
            series_id=series_id,
            title=series_resp.get("title", series_id),
            source=DataSource.FRED,
            category=Category.LEADING_INDICATORS,
            frequency=Frequency.MONTHLY,
            units=series_resp.get("units", "Unknown"),
            seasonal_adjustment=series_resp.get("seasonal_adjustment", "Not Seasonally Adjusted"),
            notes=series_resp.get("notes", ""),
        )

    return EconomicSeries(metadata=metadata, observations=observations)


async def _fetch_series_info(series_id: str, api_key: str) -> dict:
    """Fetch series metadata from FRED."""
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/series", params=params)
        response.raise_for_status()
        data = response.json()

    series_list = data.get("seriess", [])
    if series_list:
        return series_list[0]
    return {}


async def fetch_multiple_series(
    series_ids: list[str],
    api_key: str,
    period: str = "5y",
) -> list[EconomicSeries]:
    """Fetch multiple FRED series concurrently."""
    import asyncio
    tasks = [fetch_series(sid, api_key, period) for sid in series_ids]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    series_list = []
    for sid, result in zip(series_ids, results):
        if isinstance(result, Exception):
            logger.warning("Failed to fetch FRED series %s: %s", sid, result)
        else:
            series_list.append(result)
    return series_list


async def fetch_rate_series(api_key: str, period: str = "5y") -> list[EconomicSeries]:
    """Fetch all interest rate series."""
    return await fetch_multiple_series(RATE_SERIES, api_key, period)


async def fetch_inflation_series(api_key: str, period: str = "5y") -> list[EconomicSeries]:
    """Fetch all inflation series."""
    return await fetch_multiple_series(INFLATION_SERIES, api_key, period)


async def fetch_employment_series(api_key: str, period: str = "5y") -> list[EconomicSeries]:
    """Fetch all employment series."""
    return await fetch_multiple_series(EMPLOYMENT_SERIES, api_key, period)


async def fetch_housing_series(api_key: str, period: str = "5y") -> list[EconomicSeries]:
    """Fetch all housing series."""
    return await fetch_multiple_series(HOUSING_SERIES, api_key, period)


async def fetch_gdp_series(api_key: str, period: str = "10y") -> list[EconomicSeries]:
    """Fetch all GDP series."""
    return await fetch_multiple_series(GDP_SERIES, api_key, period)


async def search_series(
    query: str,
    api_key: str,
    limit: int = 20,
) -> list[dict]:
    """Search FRED for series matching a query.

    Returns a list of dicts with series_id, title, frequency, units, popularity.
    """
    params = {
        "search_text": query,
        "api_key": api_key,
        "file_type": "json",
        "limit": limit,
        "order_by": "search_rank",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/series/search", params=params)
        response.raise_for_status()
        data = response.json()

    results = []
    for s in data.get("seriess", []):
        results.append({
            "series_id": s["id"],
            "title": s.get("title", ""),
            "frequency": s.get("frequency", ""),
            "units": s.get("units", ""),
            "seasonal_adjustment": s.get("seasonal_adjustment", ""),
            "popularity": s.get("popularity", 0),
            "last_updated": s.get("last_updated", ""),
        })
    return results
