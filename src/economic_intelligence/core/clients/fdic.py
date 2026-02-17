"""FDIC (Federal Deposit Insurance Corporation) API client.

API docs: https://banks.data.fdic.gov/docs/
No authentication required. Generous rate limits.
"""

from __future__ import annotations

import logging
from datetime import date, datetime

import httpx

from ..models import BankHealthSummary, DataSource

logger = logging.getLogger(__name__)

API_BASE = "https://api.fdic.gov/banks"


async def fetch_bank_health_summary() -> BankHealthSummary:
    """Fetch aggregate banking system health indicators.

    Combines institution counts, assets, and recent failure data.
    """
    summary_data = await _fetch_financial_summary()
    failures = await _fetch_recent_failures()

    total_institutions = summary_data.get("total_institutions", 0)
    problem_institutions = summary_data.get("problem_institutions", 0)
    total_assets = summary_data.get("total_assets", 0.0)
    problem_assets = summary_data.get("problem_assets", 0.0)

    if total_institutions > 0:
        problem_ratio = problem_institutions / total_institutions
    else:
        problem_ratio = 0.0

    stress_score = min(1.0, (problem_ratio * 5) + (len(failures) * 0.1))

    if stress_score < 0.2:
        assessment = "Banking system is healthy. Problem institution count is low relative to total institutions."
    elif stress_score < 0.5:
        assessment = "Banking system shows mild stress. Elevated problem institution count or recent failures warrant monitoring."
    elif stress_score < 0.8:
        assessment = "Banking system under significant stress. High problem institution count and/or multiple recent failures."
    else:
        assessment = "Banking system in distress. Very high problem institution levels and frequent failures."

    return BankHealthSummary(
        total_institutions=total_institutions,
        problem_institutions=problem_institutions,
        total_assets_billions=total_assets / 1_000_000_000 if total_assets > 1000 else total_assets,
        problem_assets_billions=problem_assets / 1_000_000_000 if problem_assets > 1000 else problem_assets,
        recent_failures=len(failures),
        assessment=assessment,
        stress_score=stress_score,
    )


async def _fetch_financial_summary() -> dict:
    """Fetch aggregate financial data from FDIC."""
    params = {
        "filters": "REPDTE:20240331",
        "fields": "REPDTE,ASSET,DEP,NUMEMP",
        "sort_by": "ASSET",
        "sort_order": "DESC",
        "limit": "1",
        "agg_term_fields": "REPDTE",
        "agg_sum_fields": "ASSET,DEP",
        "agg_limit": "1",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        try:
            response = await client.get(f"{API_BASE}/financials", params=params)
            response.raise_for_status()
            data = response.json()

            totals = data.get("totals", {})
            meta = data.get("meta", {})
            return {
                "total_institutions": meta.get("total", 0),
                "total_assets": float(totals.get("ASSET", 0)),
                "problem_institutions": 0,
                "problem_assets": 0.0,
            }
        except httpx.HTTPError as exc:
            logger.warning("FDIC financial summary request failed: %s", exc)
            return {"total_institutions": 0, "problem_institutions": 0, "total_assets": 0, "problem_assets": 0}


async def fetch_recent_failures(years: int = 5) -> list[dict]:
    """Fetch recent bank failures."""
    return await _fetch_recent_failures(years=years)


async def _fetch_recent_failures(years: int = 5) -> list[dict]:
    """Fetch bank failures from the last N years."""
    cutoff_year = date.today().year - years

    params = {
        "sort_by": "FAILDATE",
        "sort_order": "DESC",
        "limit": "500",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        try:
            response = await client.get(f"{API_BASE}/failures", params=params)
            response.raise_for_status()
            data = response.json()

            failures = []
            for record in data.get("data", []):
                row = record.get("data", {})
                fail_year_str = row.get("FAILYR", "")
                try:
                    fail_year = int(fail_year_str) if fail_year_str else 0
                except ValueError:
                    fail_year = 0
                if fail_year < cutoff_year:
                    continue
                failures.append({
                    "institution": row.get("NAME", "Unknown"),
                    "cert_number": row.get("CERT", ""),
                    "failure_date": row.get("FAILDATE", ""),
                    "city": row.get("CITY", ""),
                    "state": row.get("PSTALP", ""),
                    "estimated_loss": row.get("COST", 0),
                    "total_assets": row.get("QBFASSET", 0),
                    "resolution_type": row.get("RESTYPE", ""),
                    "acquiring_institution": row.get("SAVR", ""),
                })
            return failures
        except httpx.HTTPError as exc:
            logger.warning("FDIC failures request failed: %s", exc)
            return []


async def fetch_institution_details(cert_number: str) -> dict:
    """Fetch details for a specific FDIC-insured institution."""
    params = {
        "filters": f"CERT:{cert_number}",
        "fields": "INSTNAME,CERT,CITY,STALP,ASSET,DEP,NETINC,ROA,ROE,REPDTE",
        "sort_by": "REPDTE",
        "sort_order": "DESC",
        "limit": "1",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0)) as client:
        response = await client.get(f"{API_BASE}/financials", params=params)
        response.raise_for_status()
        data = response.json()

    records = data.get("data", [])
    if not records:
        return {}
    return records[0].get("data", {})
