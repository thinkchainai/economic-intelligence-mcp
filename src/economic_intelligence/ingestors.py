"""Signal computation engine with historical backfill.

On first run, fetches 12 months of historical data and computes signals
at monthly intervals to build instant signal history. Subsequent runs
compute a fresh snapshot using live data.

All raw data is fetched live from APIs — only computed signals are persisted.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, text

from .core.clients import fdic, fred
from .core.scoring import (
    compute_recession_probability,
    score_bank_stress,
    score_jobs_inflation_divergence,
    score_yield_curve,
)
from .db import get_session_factory
from .sqlmodels import IngestionMeta, RecessionSnapshot, SignalSnapshot

logger = logging.getLogger(__name__)

BACKFILL_MONTHS = 12


async def needs_backfill() -> bool:
    """Check if we need to run the initial historical backfill."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(IngestionMeta).where(IngestionMeta.key == "backfill_complete")
        )
        return result.scalar_one_or_none() is None


async def run_backfill(fred_api_key: str) -> int:
    """Backfill 12 months of signal history by fetching historical data and scoring it.

    For each month going back BACKFILL_MONTHS months:
    1. Fetch FRED series with enough lookback for the scoring functions
    2. Trim observations to simulate "as of" that date
    3. Run scoring functions
    4. Persist signal snapshots

    Returns the number of snapshots created.
    """
    logger.info("Starting historical backfill (%d months)...", BACKFILL_MONTHS)
    today = date.today()
    snapshot_count = 0

    spread_full = await fred.fetch_series("T10Y2Y", fred_api_key, "3y")
    unemp_full = await fred.fetch_series("UNRATE", fred_api_key, "3y")
    cpi_full = await fred.fetch_series("CPIAUCSL", fred_api_key, "3y")

    for months_ago in range(BACKFILL_MONTHS, 0, -1):
        as_of = _months_back(today, months_ago)
        cutoff = as_of + timedelta(days=1)

        spread_asof = _trim_series(spread_full, cutoff)
        unemp_asof = _trim_series(unemp_full, cutoff)
        cpi_asof = _trim_series(cpi_full, cutoff)

        signals = []
        yield_signal = score_yield_curve(spread_asof)
        if yield_signal:
            signals.append(yield_signal)

        jobs_signal = score_jobs_inflation_divergence(unemp_asof, cpi_asof)
        if jobs_signal:
            signals.append(jobs_signal)

        try:
            bank_health = await fdic.fetch_bank_health_summary()
            bank_signal = score_bank_stress(bank_health)
            signals.append(bank_signal)
        except Exception as exc:
            logger.warning("FDIC fetch failed during backfill (month -%d): %s", months_ago, exc)

        if not signals:
            continue

        spread_val = spread_asof.latest.value if spread_asof and spread_asof.latest else None
        recession = compute_recession_probability(signals, spread_val, unemp_asof)

        count = await _persist_snapshot(signals, recession, as_of)
        snapshot_count += count

    session_factory = get_session_factory()
    async with session_factory() as session:
        session.add(IngestionMeta(
            key="backfill_complete",
            value=datetime.utcnow().isoformat(),
            updated_at=datetime.utcnow(),
        ))
        await session.commit()

    logger.info("Backfill complete: %d snapshots created", snapshot_count)
    return snapshot_count


async def run_refresh(fred_api_key: str) -> int:
    """Compute fresh signal snapshot using live data.

    This runs on a schedule (every 6 hours) after the initial backfill.
    Returns the number of snapshots created.
    """
    logger.info("Running signal refresh...")

    spread = await fred.fetch_series("T10Y2Y", fred_api_key, "2y")
    unemployment = await fred.fetch_series("UNRATE", fred_api_key, "2y")
    cpi = await fred.fetch_series("CPIAUCSL", fred_api_key, "2y")

    signals = []
    yield_signal = score_yield_curve(spread)
    if yield_signal:
        signals.append(yield_signal)

    jobs_signal = score_jobs_inflation_divergence(unemployment, cpi)
    if jobs_signal:
        signals.append(jobs_signal)

    try:
        bank_health = await fdic.fetch_bank_health_summary()
        bank_signal = score_bank_stress(bank_health)
        signals.append(bank_signal)
    except Exception as exc:
        logger.warning("FDIC fetch failed during refresh: %s", exc)

    if not signals:
        logger.warning("No signals computed during refresh")
        return 0

    spread_val = spread.latest.value if spread.latest else None
    recession = compute_recession_probability(signals, spread_val, unemployment)
    today = date.today()
    count = await _persist_snapshot(signals, recession, today)

    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            select(IngestionMeta).where(IngestionMeta.key == "last_refresh")
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = datetime.utcnow().isoformat()
            row.updated_at = datetime.utcnow()
        else:
            session.add(IngestionMeta(
                key="last_refresh",
                value=datetime.utcnow().isoformat(),
                updated_at=datetime.utcnow(),
            ))
        await session.commit()

    logger.info("Refresh complete: %d snapshots created", count)
    return count


async def _persist_snapshot(
    signals: list,
    recession,
    as_of: date,
) -> int:
    """Persist signal and recession snapshots to SQLite."""
    session_factory = get_session_factory()
    count = 0

    async with session_factory() as session:
        for sig in signals:
            session.add(SignalSnapshot(
                signal_name=sig.title.lower().replace(" ", "_"),
                score=sig.score,
                title=sig.title,
                summary=sig.summary,
                tags=",".join(t.value for t in sig.tags),
                category=sig.category.value,
                data_as_of=as_of,
                computed_at=datetime.utcnow(),
            ))
            count += 1

        session.add(RecessionSnapshot(
            probability=recession.probability,
            assessment=recession.assessment,
            yield_curve_spread=recession.yield_curve_spread,
            unemployment_trend=recession.unemployment_trend,
            signal_count=len(signals),
            data_as_of=as_of,
            computed_at=datetime.utcnow(),
        ))
        count += 1

        await session.commit()

    return count


async def get_signal_history(
    signal_name: Optional[str] = None,
    months: int = 12,
) -> list[dict]:
    """Retrieve signal score history from the database.

    Args:
        signal_name: Filter to a specific signal (e.g., 'yield_curve_signal').
                     If None, returns all signals.
        months: How many months of history to return.

    Returns:
        List of dicts with signal_name, score, summary, tags, data_as_of.
    """
    session_factory = get_session_factory()
    cutoff = date.today() - timedelta(days=months * 31)

    async with session_factory() as session:
        query = select(SignalSnapshot).where(
            SignalSnapshot.data_as_of >= cutoff
        ).order_by(SignalSnapshot.data_as_of.asc())

        if signal_name:
            query = query.where(SignalSnapshot.signal_name == signal_name)

        result = await session.execute(query)
        rows = result.scalars().all()

    return [
        {
            "signal_name": r.signal_name,
            "score": r.score,
            "title": r.title,
            "summary": r.summary,
            "tags": r.tags.split(",") if r.tags else [],
            "category": r.category,
            "data_as_of": r.data_as_of.isoformat(),
        }
        for r in rows
    ]


async def get_recession_history(months: int = 12) -> list[dict]:
    """Retrieve recession probability history."""
    session_factory = get_session_factory()
    cutoff = date.today() - timedelta(days=months * 31)

    async with session_factory() as session:
        result = await session.execute(
            select(RecessionSnapshot)
            .where(RecessionSnapshot.data_as_of >= cutoff)
            .order_by(RecessionSnapshot.data_as_of.asc())
        )
        rows = result.scalars().all()

    return [
        {
            "probability": r.probability,
            "assessment": r.assessment,
            "yield_curve_spread": r.yield_curve_spread,
            "unemployment_trend": r.unemployment_trend,
            "signal_count": r.signal_count,
            "data_as_of": r.data_as_of.isoformat(),
        }
        for r in rows
    ]


async def detect_changes(since_days: int = 7) -> list[dict]:
    """Detect significant changes in signals compared to a prior period.

    Compares the latest snapshot of each signal to the snapshot closest to
    `since_days` ago. Returns signals with meaningful score changes.
    """
    session_factory = get_session_factory()
    today = date.today()
    compare_date = today - timedelta(days=since_days)

    async with session_factory() as session:
        latest_result = await session.execute(
            text("""
                SELECT s1.* FROM signal_snapshots s1
                INNER JOIN (
                    SELECT signal_name, MAX(data_as_of) as max_date
                    FROM signal_snapshots
                    GROUP BY signal_name
                ) s2 ON s1.signal_name = s2.signal_name AND s1.data_as_of = s2.max_date
            """)
        )
        latest_rows = {r.signal_name: r for r in latest_result}

        prior_result = await session.execute(
            text("""
                SELECT s1.* FROM signal_snapshots s1
                INNER JOIN (
                    SELECT signal_name, MAX(data_as_of) as max_date
                    FROM signal_snapshots
                    WHERE data_as_of <= :compare_date
                    GROUP BY signal_name
                ) s2 ON s1.signal_name = s2.signal_name AND s1.data_as_of = s2.max_date
            """),
            {"compare_date": compare_date.isoformat()},
        )
        prior_rows = {r.signal_name: r for r in prior_result}

    changes = []
    for name, latest in latest_rows.items():
        prior = prior_rows.get(name)
        if not prior:
            changes.append({
                "signal_name": name,
                "title": latest.title,
                "current_score": latest.score,
                "previous_score": None,
                "change": None,
                "change_type": "new",
                "summary": latest.summary,
                "data_as_of": latest.data_as_of.isoformat() if isinstance(latest.data_as_of, date) else latest.data_as_of,
            })
            continue

        delta = latest.score - prior.score
        if abs(delta) < 0.05:
            continue

        if delta > 0.2:
            change_type = "significant_increase"
        elif delta > 0:
            change_type = "increase"
        elif delta < -0.2:
            change_type = "significant_decrease"
        else:
            change_type = "decrease"

        changes.append({
            "signal_name": name,
            "title": latest.title,
            "current_score": latest.score,
            "previous_score": prior.score,
            "change": round(delta, 3),
            "change_type": change_type,
            "summary": latest.summary,
            "data_as_of": latest.data_as_of.isoformat() if isinstance(latest.data_as_of, date) else latest.data_as_of,
        })

    changes.sort(key=lambda c: abs(c.get("change") or 0), reverse=True)
    return changes


async def detect_alerts() -> list[dict]:
    """Detect threshold crossings and trend reversals in signal history.

    Alerts are generated when:
    - A signal crosses above 0.6 (elevated risk)
    - A signal crosses below 0.3 (risk diminishing)
    - Recession probability crosses 0.3 or 0.5
    - A consistent trend reversal is detected (3+ months in same direction then reverses)
    """
    session_factory = get_session_factory()

    async with session_factory() as session:
        sig_result = await session.execute(
            select(SignalSnapshot)
            .order_by(SignalSnapshot.signal_name, SignalSnapshot.data_as_of.asc())
        )
        all_signals = sig_result.scalars().all()

        rec_result = await session.execute(
            select(RecessionSnapshot).order_by(RecessionSnapshot.data_as_of.asc())
        )
        all_recession = rec_result.scalars().all()

    alerts = []

    by_name: dict[str, list] = {}
    for s in all_signals:
        by_name.setdefault(s.signal_name, []).append(s)

    for name, snapshots in by_name.items():
        if len(snapshots) < 2:
            continue

        latest = snapshots[-1]
        prev = snapshots[-2]

        if latest.score >= 0.6 and prev.score < 0.6:
            alerts.append({
                "type": "threshold_crossed",
                "severity": "high",
                "signal_name": name,
                "title": f"{latest.title} — Elevated Risk",
                "message": f"{latest.title} crossed above 60% (was {prev.score:.0%}, now {latest.score:.0%})",
                "current_score": latest.score,
                "previous_score": prev.score,
                "data_as_of": latest.data_as_of.isoformat(),
            })
        elif latest.score < 0.3 and prev.score >= 0.3:
            alerts.append({
                "type": "threshold_crossed",
                "severity": "low",
                "signal_name": name,
                "title": f"{latest.title} — Risk Diminishing",
                "message": f"{latest.title} dropped below 30% (was {prev.score:.0%}, now {latest.score:.0%})",
                "current_score": latest.score,
                "previous_score": prev.score,
                "data_as_of": latest.data_as_of.isoformat(),
            })

        if len(snapshots) >= 4:
            recent_3 = [s.score for s in snapshots[-4:-1]]
            was_rising = all(recent_3[i] <= recent_3[i + 1] for i in range(len(recent_3) - 1))
            was_falling = all(recent_3[i] >= recent_3[i + 1] for i in range(len(recent_3) - 1))
            now_reversed = False

            if was_rising and latest.score < prev.score:
                now_reversed = True
                direction = "peaked and is now declining"
            elif was_falling and latest.score > prev.score:
                now_reversed = True
                direction = "bottomed and is now rising"

            if now_reversed:
                alerts.append({
                    "type": "trend_reversal",
                    "severity": "medium",
                    "signal_name": name,
                    "title": f"{latest.title} — Trend Reversal",
                    "message": f"{latest.title} has {direction} (now {latest.score:.0%})",
                    "current_score": latest.score,
                    "previous_score": prev.score,
                    "data_as_of": latest.data_as_of.isoformat(),
                })

    if len(all_recession) >= 2:
        r_latest = all_recession[-1]
        r_prev = all_recession[-2]
        for threshold in [0.3, 0.5]:
            if r_latest.probability >= threshold and r_prev.probability < threshold:
                alerts.append({
                    "type": "recession_threshold",
                    "severity": "high" if threshold >= 0.5 else "medium",
                    "signal_name": "recession_probability",
                    "title": f"Recession Probability — Crossed {threshold:.0%}",
                    "message": f"Composite recession probability rose above {threshold:.0%} (was {r_prev.probability:.0%}, now {r_latest.probability:.0%})",
                    "current_score": r_latest.probability,
                    "previous_score": r_prev.probability,
                    "data_as_of": r_latest.data_as_of.isoformat(),
                })
            elif r_latest.probability < threshold and r_prev.probability >= threshold:
                alerts.append({
                    "type": "recession_threshold",
                    "severity": "low",
                    "signal_name": "recession_probability",
                    "title": f"Recession Probability — Dropped Below {threshold:.0%}",
                    "message": f"Composite recession probability fell below {threshold:.0%} (was {r_prev.probability:.0%}, now {r_latest.probability:.0%})",
                    "current_score": r_latest.probability,
                    "previous_score": r_prev.probability,
                    "data_as_of": r_latest.data_as_of.isoformat(),
                })

    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 3))
    return alerts


def _months_back(d: date, months: int) -> date:
    """Return a date N months before d."""
    month = d.month - months
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    day = min(d.day, 28)
    return date(year, month, day)


def _trim_series(series, cutoff: date):
    """Return a copy of an EconomicSeries with observations before cutoff only."""
    from .core.models import EconomicSeries

    trimmed_obs = [o for o in series.observations if o.date < cutoff]
    return EconomicSeries(metadata=series.metadata, observations=trimmed_obs)
