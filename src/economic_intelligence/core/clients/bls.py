"""Bureau of Labor Statistics (BLS) API client.

API docs: https://www.bls.gov/developers/
v2 requires a free API key (500 req/day). v1 is unauthenticated (25 req/day).
"""

from __future__ import annotations

import logging
from datetime import date
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

API_BASE_V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
API_BASE_V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"

# Well-known BLS series
SERIES_CATALOG: dict[str, dict] = {
    # Employment
    "LNS14000000": {"title": "Unemployment Rate (Seasonally Adjusted)", "category": Category.EMPLOYMENT, "units": "Percent", "frequency": Frequency.MONTHLY},
    "CES0000000001": {"title": "Total Nonfarm Payrolls (Seasonally Adjusted)", "category": Category.EMPLOYMENT, "units": "Thousands", "frequency": Frequency.MONTHLY},
    "CES0500000003": {"title": "Average Hourly Earnings (Private, Seasonally Adjusted)", "category": Category.EMPLOYMENT, "units": "Dollars", "frequency": Frequency.MONTHLY},
    "LNS11300000": {"title": "Labor Force Participation Rate", "category": Category.EMPLOYMENT, "units": "Percent", "frequency": Frequency.MONTHLY},
    # CPI (inflation)
    "CUSR0000SA0": {"title": "CPI-U All Items (Seasonally Adjusted)", "category": Category.INFLATION, "units": "Index 1982-84=100", "frequency": Frequency.MONTHLY},
    "CUSR0000SA0L1E": {"title": "CPI-U Less Food and Energy (Core, SA)", "category": Category.INFLATION, "units": "Index 1982-84=100", "frequency": Frequency.MONTHLY},
    "CUSR0000SAF1": {"title": "CPI-U Food (Seasonally Adjusted)", "category": Category.INFLATION, "units": "Index 1982-84=100", "frequency": Frequency.MONTHLY},
    "CUSR0000SETA01": {"title": "CPI-U Gasoline (Seasonally Adjusted)", "category": Category.INFLATION, "units": "Index 1982-84=100", "frequency": Frequency.MONTHLY},
    "CUSR0000SAH1": {"title": "CPI-U Shelter (Seasonally Adjusted)", "category": Category.INFLATION, "units": "Index 1982-84=100", "frequency": Frequency.MONTHLY},
}

EMPLOYMENT_SERIES = ["LNS14000000", "CES0000000001", "CES0500000003", "LNS11300000"]
INFLATION_SERIES = ["CUSR0000SA0", "CUSR0000SA0L1E", "CUSR0000SAF1", "CUSR0000SETA01", "CUSR0000SAH1"]


def _month_to_date(year: str, month: str) -> date:
    """Convert BLS year/period to date. Period is like 'M01' for January."""
    month_num = int(month.replace("M", "").replace("S", "").replace("A", ""))
    month_num = max(1, min(12, month_num))
    return date(int(year), month_num, 1)


async def fetch_series(
    series_ids: list[str],
    api_key: Optional[str] = None,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
) -> list[EconomicSeries]:
    """Fetch one or more BLS series.

    Uses v2 API if api_key is provided (higher limits), otherwise v1.
    BLS API accepts up to 50 series per request and max 20 years range.
    """
    today = date.today()
    if end_year is None:
        end_year = today.year
    if start_year is None:
        start_year = end_year - 5

    # BLS limits to 20 years per request
    start_year = max(start_year, end_year - 20)

    payload: dict = {
        "seriesid": series_ids,
        "startyear": str(start_year),
        "endyear": str(end_year),
    }
    if api_key:
        payload["registrationkey"] = api_key

    api_url = API_BASE_V2 if api_key else API_BASE_V1

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.post(api_url, json=payload)
        response.raise_for_status()
        data = response.json()

    if data.get("status") != "REQUEST_SUCCEEDED":
        logger.warning("BLS API returned status: %s, messages: %s", data.get("status"), data.get("message", []))

    results = []
    for series_data in data.get("Results", {}).get("series", []):
        series_id = series_data.get("seriesID", "")
        observations = []

        for obs in series_data.get("data", []):
            period = obs.get("period", "")
            if not period.startswith("M"):
                continue
            try:
                point = DataPoint(
                    date=_month_to_date(obs["year"], period),
                    value=float(obs["value"]),
                    preliminary=obs.get("latest", "false") == "true",
                )
                observations.append(point)
            except (ValueError, KeyError):
                continue

        observations.sort(key=lambda o: o.date)

        catalog_entry = SERIES_CATALOG.get(series_id)
        if catalog_entry:
            metadata = SeriesMetadata(
                series_id=series_id,
                title=catalog_entry["title"],
                source=DataSource.BLS,
                category=catalog_entry["category"],
                frequency=catalog_entry["frequency"],
                units=catalog_entry["units"],
                seasonal_adjustment="Seasonally Adjusted",
            )
        else:
            metadata = SeriesMetadata(
                series_id=series_id,
                title=series_id,
                source=DataSource.BLS,
                category=Category.EMPLOYMENT,
                frequency=Frequency.MONTHLY,
                units="Unknown",
            )

        results.append(EconomicSeries(metadata=metadata, observations=observations))

    return results


async def fetch_employment_data(
    api_key: Optional[str] = None,
    years: int = 5,
) -> list[EconomicSeries]:
    """Fetch all employment series."""
    end_year = date.today().year
    return await fetch_series(EMPLOYMENT_SERIES, api_key, end_year - years, end_year)


async def fetch_cpi_data(
    api_key: Optional[str] = None,
    years: int = 5,
) -> list[EconomicSeries]:
    """Fetch CPI inflation breakdown series."""
    end_year = date.today().year
    return await fetch_series(INFLATION_SERIES, api_key, end_year - years, end_year)
