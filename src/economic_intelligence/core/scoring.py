"""Cross-source economic scoring and correlation engine.

Computes composite signals by combining data from multiple government sources.
This is the core IP — the part that makes this more than an API wrapper.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Optional

from .models import (
    BankHealthSummary,
    Category,
    DataSource,
    EconomicSeries,
    HousingAffordability,
    RecessionProbability,
    ScoredSignal,
    SignalTag,
)

logger = logging.getLogger(__name__)


def score_yield_curve(spread_10y2y: Optional[EconomicSeries]) -> Optional[ScoredSignal]:
    """Score the yield curve inversion signal.

    The 10Y-2Y spread going negative has preceded every US recession since 1970,
    typically 6-24 months before the downturn.
    """
    if not spread_10y2y or not spread_10y2y.observations:
        return None

    latest = spread_10y2y.latest
    if latest is None:
        return None

    spread = latest.value
    tags = []

    if spread < 0:
        score = min(1.0, abs(spread) / 1.0)
        tags.append(SignalTag.YIELD_CURVE_INVERTED)
        tags.append(SignalTag.RECESSION_SIGNAL)
        summary = f"Yield curve is inverted at {spread:.2f}%. The 10Y-2Y spread has been a reliable recession predictor — every inversion since 1970 was followed by a recession within 6-24 months."
    elif spread < 0.5:
        score = 0.4
        tags.append(SignalTag.RECESSION_SIGNAL)
        summary = f"Yield curve is nearly flat at {spread:.2f}%. Approaching inversion territory, which historically signals an economic slowdown."
    elif spread > 2.0:
        score = 0.1
        tags.append(SignalTag.YIELD_CURVE_STEEPENING)
        summary = f"Yield curve is steep at {spread:.2f}%, indicating market expectations of future growth and/or inflation."
    else:
        score = 0.2
        summary = f"Yield curve spread is {spread:.2f}% — in normal range. No strong signal."

    # Check for recent un-inversion (which can also signal imminent recession)
    recent_obs = [o for o in spread_10y2y.observations if o.date >= latest.date - timedelta(days=180)]
    was_inverted = any(o.value < 0 for o in recent_obs)
    now_positive = spread > 0
    if was_inverted and now_positive:
        score = max(score, 0.7)
        tags.append(SignalTag.RECESSION_SIGNAL)
        summary += " The curve recently un-inverted — historically this steepening after inversion often immediately precedes recession."

    return ScoredSignal(
        signal_id=f"yield_curve_{uuid.uuid4().hex[:8]}",
        title="Yield Curve Signal",
        summary=summary,
        score=score,
        tags=tags,
        category=Category.INTEREST_RATES,
        sources_used=[DataSource.FRED],
        contributing_series=["T10Y2Y"],
        data_as_of=latest.date,
    )


def score_jobs_inflation_divergence(
    unemployment: Optional[EconomicSeries],
    cpi: Optional[EconomicSeries],
) -> Optional[ScoredSignal]:
    """Score the jobs vs. inflation divergence signal.

    When unemployment falls while inflation rises, the economy may be overheating.
    When both are moving the same direction, the signal is less concerning.
    """
    if not unemployment or not cpi:
        return None
    if not unemployment.observations or not cpi.observations:
        return None

    unemp_changes = unemployment.pct_change(periods=3)
    cpi_changes = cpi.pct_change(periods=3)

    if len(unemp_changes) < 2 or len(cpi_changes) < 2:
        return None

    unemp_trend = unemp_changes[-1][1]
    cpi_trend = cpi_changes[-1][1]

    tags = []
    unemp_latest = unemployment.latest
    cpi_latest = cpi.latest
    data_date = max(unemp_latest.date if unemp_latest else date.min, cpi_latest.date if cpi_latest else date.min)

    if unemp_trend < -1 and cpi_trend > 1:
        score = 0.7
        tags.extend([SignalTag.OVERHEATING, SignalTag.INFLATION_RISING, SignalTag.JOBS_STRONG])
        summary = "Unemployment is falling while inflation is rising — classic overheating signal. The Fed may need to tighten further."
    elif unemp_trend > 1 and cpi_trend > 1:
        score = 0.6
        tags.extend([SignalTag.INFLATION_RISING, SignalTag.JOBS_WEAKENING])
        summary = "Stagflation risk: unemployment is rising alongside inflation. This is the worst macro scenario — economic pain without price relief."
    elif unemp_trend > 1 and cpi_trend < -0.5:
        score = 0.5
        tags.extend([SignalTag.INFLATION_COOLING, SignalTag.JOBS_WEAKENING, SignalTag.RATE_CUT_SIGNAL])
        summary = "Both unemployment rising and inflation cooling — conditions that typically lead to rate cuts. Watch for Fed pivot signals."
    elif unemp_trend < -1 and cpi_trend < -0.5:
        score = 0.2
        tags.extend([SignalTag.INFLATION_COOLING, SignalTag.JOBS_STRONG])
        summary = "Goldilocks scenario: strong job market with cooling inflation. The soft landing narrative is intact."
    else:
        score = 0.15
        summary = "No strong divergence between jobs and inflation trends. Economy is in a stable equilibrium."

    return ScoredSignal(
        signal_id=f"jobs_inflation_{uuid.uuid4().hex[:8]}",
        title="Jobs vs. Inflation Divergence",
        summary=summary,
        score=score,
        tags=tags,
        category=Category.EMPLOYMENT,
        sources_used=[DataSource.FRED, DataSource.BLS],
        contributing_series=["UNRATE", "CPIAUCSL"],
        data_as_of=data_date,
    )


def score_housing_affordability(
    home_prices: Optional[EconomicSeries],
    mortgage_rates: Optional[EconomicSeries],
    median_income_series: Optional[EconomicSeries] = None,
) -> HousingAffordability:
    """Compute composite housing affordability index.

    Combines home prices, mortgage rates, and income data.
    Index of 100 = baseline affordability (2019 average).
    Higher = more affordable.
    """
    median_home_price = None
    mortgage_rate = None

    if home_prices and home_prices.latest:
        median_home_price = home_prices.latest.value

    if mortgage_rates and mortgage_rates.latest:
        mortgage_rate = mortgage_rates.latest.value

    # Estimate monthly payment (30-year fixed, 20% down)
    monthly_payment = None
    if median_home_price and mortgage_rate and mortgage_rate > 0:
        loan_amount = median_home_price * 0.80
        monthly_rate = (mortgage_rate / 100) / 12
        num_payments = 360
        monthly_payment = loan_amount * (monthly_rate * (1 + monthly_rate) ** num_payments) / ((1 + monthly_rate) ** num_payments - 1)

    # Compute affordability index (relative to 2019 baseline)
    # 2019 baseline: ~$320K median price, ~3.9% rate, ~$68K median income
    baseline_payment = 320000 * 0.80 * (0.039 / 12 * (1 + 0.039 / 12) ** 360) / ((1 + 0.039 / 12) ** 360 - 1)
    baseline_income_monthly = 68000 / 12

    if monthly_payment and monthly_payment > 0:
        current_ratio = monthly_payment / baseline_income_monthly
        baseline_ratio = baseline_payment / baseline_income_monthly
        index_value = (baseline_ratio / current_ratio) * 100
    else:
        index_value = 100.0

    # Determine trend
    if home_prices and len(home_prices.observations) >= 6:
        recent_changes = home_prices.pct_change(periods=3)
        if recent_changes:
            latest_change = recent_changes[-1][1]
            if latest_change > 2:
                trend = "worsening"
            elif latest_change < -1:
                trend = "improving"
            else:
                trend = "stable"
        else:
            trend = "stable"
    else:
        trend = "stable"

    if index_value > 110:
        assessment = "Housing is more affordable than the 2019 baseline. Favorable conditions for buyers."
    elif index_value > 90:
        assessment = "Housing affordability is near the 2019 baseline. Market conditions are normal."
    elif index_value > 70:
        assessment = "Housing is less affordable than 2019. Elevated prices and/or rates are stretching budgets."
    else:
        assessment = "Housing affordability is severely strained. Monthly payments are far above historical norms relative to income."

    return HousingAffordability(
        index_value=round(index_value, 1),
        median_home_price=median_home_price,
        mortgage_rate_30y=mortgage_rate,
        monthly_payment_estimate=round(monthly_payment, 2) if monthly_payment else None,
        assessment=assessment,
        trend=trend,
    )


def score_bank_stress(bank_health: BankHealthSummary) -> ScoredSignal:
    """Score banking system stress from FDIC data."""
    tags = []

    if bank_health.stress_score > 0.5:
        tags.append(SignalTag.BANK_STRESS)

    if bank_health.stress_score > 0.7:
        tags.append(SignalTag.RECESSION_SIGNAL)

    return ScoredSignal(
        signal_id=f"bank_stress_{uuid.uuid4().hex[:8]}",
        title="Banking System Stress",
        summary=bank_health.assessment,
        score=bank_health.stress_score,
        tags=tags,
        category=Category.BANKING,
        sources_used=[DataSource.FDIC],
        contributing_series=[],
        data_as_of=date.today(),
    )


def compute_recession_probability(
    signals: list[ScoredSignal],
    yield_curve_spread: Optional[float] = None,
    unemployment_series: Optional[EconomicSeries] = None,
) -> RecessionProbability:
    """Compute composite recession probability from multiple signals.

    Weighs yield curve most heavily (historically the best single predictor),
    with supporting evidence from employment, inflation, and banking signals.
    """
    recession_signals = [s for s in signals if SignalTag.RECESSION_SIGNAL in s.tags]

    if not signals:
        return RecessionProbability(
            probability=0.0,
            assessment="Insufficient data to compute recession probability.",
            contributing_signals=[],
            computed_at=datetime.utcnow(),
        )

    # Weighted average of recession-tagged signals
    weights = {
        Category.INTEREST_RATES: 0.35,
        Category.EMPLOYMENT: 0.25,
        Category.INFLATION: 0.15,
        Category.BANKING: 0.15,
        Category.LEADING_INDICATORS: 0.10,
    }

    weighted_sum = 0.0
    weight_total = 0.0
    for signal in signals:
        w = weights.get(signal.category, 0.05)
        weighted_sum += signal.score * w
        weight_total += w

    probability = weighted_sum / weight_total if weight_total > 0 else 0.0
    probability = max(0.0, min(1.0, probability))

    # Determine unemployment trend
    unemp_trend = None
    if unemployment_series and len(unemployment_series.observations) >= 6:
        changes = unemployment_series.pct_change(periods=3)
        if changes:
            latest_change = changes[-1][1]
            if latest_change > 2:
                unemp_trend = "rising"
            elif latest_change < -2:
                unemp_trend = "falling"
            else:
                unemp_trend = "stable"

    if probability > 0.7:
        assessment = f"High recession probability ({probability:.0%}). Multiple economic indicators are flashing warning signs. Yield curve, employment, and/or banking stress all contributing."
    elif probability > 0.4:
        assessment = f"Elevated recession risk ({probability:.0%}). Some indicators are concerning but the signal is mixed. Monitor closely over the next 3-6 months."
    elif probability > 0.2:
        assessment = f"Mild recession risk ({probability:.0%}). Most indicators are stable with isolated areas of concern."
    else:
        assessment = f"Low recession probability ({probability:.0%}). Economic indicators are broadly healthy."

    return RecessionProbability(
        probability=round(probability, 3),
        assessment=assessment,
        contributing_signals=signals,
        yield_curve_spread=yield_curve_spread,
        unemployment_trend=unemp_trend,
    )
