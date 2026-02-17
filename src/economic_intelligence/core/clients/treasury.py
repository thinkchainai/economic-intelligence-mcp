"""Treasury Fiscal Data API client.

API docs: https://fiscaldata.treasury.gov/api-documentation/
No authentication required. Generous rate limits.
"""

from __future__ import annotations

import logging
from datetime import date

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

API_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"


async def fetch_treasury_rates(period: str = "5y") -> list[EconomicSeries]:
    """Fetch average interest rates on Treasury securities.

    Returns series for different security types (bills, notes, bonds).
    """
    today = date.today()
    years = int(period[:-1]) if period.endswith("y") else 5
    start_date = today.replace(year=today.year - years)

    params = {
        "fields": "record_date,security_desc,avg_interest_rate_amt",
        "filter": f"record_date:gte:{start_date.isoformat()}",
        "sort": "record_date",
        "page[size]": "10000",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/v2/accounting/od/avg_interest_rates", params=params)
        response.raise_for_status()
        data = response.json()

    series_map: dict[str, list[DataPoint]] = {}
    for record in data.get("data", []):
        desc = record.get("security_desc", "Unknown")
        rate_str = record.get("avg_interest_rate_amt")
        if not rate_str:
            continue
        try:
            point = DataPoint(
                date=date.fromisoformat(record["record_date"]),
                value=float(rate_str),
            )
            series_map.setdefault(desc, []).append(point)
        except (ValueError, KeyError):
            continue

    results = []
    for desc, observations in series_map.items():
        if len(observations) < 2:
            continue
        metadata = SeriesMetadata(
            series_id=f"treasury_{desc.lower().replace(' ', '_').replace(',', '')}",
            title=f"Treasury Average Interest Rate — {desc}",
            source=DataSource.TREASURY,
            category=Category.TREASURY_DEBT,
            frequency=Frequency.MONTHLY,
            units="Percent",
        )
        results.append(EconomicSeries(metadata=metadata, observations=observations))

    return results


async def fetch_federal_debt(period: str = "5y") -> EconomicSeries:
    """Fetch total federal debt outstanding."""
    today = date.today()
    years = int(period[:-1]) if period.endswith("y") else 5
    start_date = today.replace(year=today.year - years)

    params = {
        "fields": "record_date,tot_pub_debt_out_amt",
        "filter": f"record_date:gte:{start_date.isoformat()}",
        "sort": "-record_date",
        "page[size]": "10000",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/v2/accounting/od/debt_to_penny", params=params)
        response.raise_for_status()
        data = response.json()

    observations = []
    for record in data.get("data", []):
        try:
            observations.append(DataPoint(
                date=date.fromisoformat(record["record_date"]),
                value=float(record["tot_pub_debt_out_amt"]),
            ))
        except (ValueError, KeyError):
            continue

    metadata = SeriesMetadata(
        series_id="treasury_total_public_debt",
        title="Total Public Debt Outstanding",
        source=DataSource.TREASURY,
        category=Category.TREASURY_DEBT,
        frequency=Frequency.DAILY,
        units="Dollars",
    )
    return EconomicSeries(metadata=metadata, observations=observations)


async def fetch_yield_curve_rates() -> dict[str, float]:
    """Fetch the most recent daily Treasury yield curve rates.

    Returns a dict mapping maturity labels to rates, e.g.:
    {"1 Mo": 5.25, "3 Mo": 5.30, "6 Mo": 5.28, "1 Yr": 5.10, ...}
    """
    params = {
        "fields": "record_date,security_desc,avg_interest_rate_amt",
        "sort": "-record_date",
        "page[size]": "50",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/v2/accounting/od/avg_interest_rates", params=params)
        response.raise_for_status()
        data = response.json()

    latest_date = None
    rates: dict[str, float] = {}
    for record in data.get("data", []):
        record_date = record.get("record_date")
        if latest_date is None:
            latest_date = record_date
        if record_date != latest_date:
            break
        desc = record.get("security_desc", "")
        rate_str = record.get("avg_interest_rate_amt")
        if rate_str:
            try:
                rates[desc] = float(rate_str)
            except ValueError:
                continue

    return rates
