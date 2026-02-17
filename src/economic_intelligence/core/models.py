"""Pydantic data models — the shared business objects.

Both the open-source FastMCP server and the MCPBundles hosted integration
use these models as the common interface for scoring, parsing, and tools.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DataSource(str, Enum):
    """Government data sources."""

    FRED = "fred"
    BLS = "bls"
    TREASURY = "treasury"
    FDIC = "fdic"
    CENSUS = "census"


class Frequency(str, Enum):
    """Data observation frequency."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    SEMIANNUAL = "semiannual"
    ANNUAL = "annual"


class Category(str, Enum):
    """Economic data category."""

    INTEREST_RATES = "interest_rates"
    INFLATION = "inflation"
    EMPLOYMENT = "employment"
    HOUSING = "housing"
    GDP = "gdp"
    BANKING = "banking"
    TREASURY_DEBT = "treasury_debt"
    LEADING_INDICATORS = "leading_indicators"


class DataPoint(BaseModel):
    """A single observation in a time series."""

    date: date
    value: float
    preliminary: bool = False


class SeriesMetadata(BaseModel):
    """Metadata about an economic data series."""

    series_id: str
    title: str
    source: DataSource
    category: Category
    frequency: Frequency
    units: str
    seasonal_adjustment: str = "Not Seasonally Adjusted"
    last_updated: Optional[datetime] = None
    notes: str = ""


class EconomicSeries(BaseModel):
    """A complete economic time series with metadata and observations."""

    metadata: SeriesMetadata
    observations: list[DataPoint]

    @property
    def latest(self) -> Optional[DataPoint]:
        if not self.observations:
            return None
        return max(self.observations, key=lambda o: o.date)

    @property
    def earliest(self) -> Optional[DataPoint]:
        if not self.observations:
            return None
        return min(self.observations, key=lambda o: o.date)

    def values_in_range(self, start: date, end: date) -> list[DataPoint]:
        return [o for o in self.observations if start <= o.date <= end]

    def pct_change(self, periods: int = 1) -> list[tuple[date, float]]:
        """Calculate period-over-period percent change."""
        sorted_obs = sorted(self.observations, key=lambda o: o.date)
        changes = []
        for i in range(periods, len(sorted_obs)):
            prev = sorted_obs[i - periods].value
            curr = sorted_obs[i].value
            if prev != 0:
                changes.append((sorted_obs[i].date, ((curr - prev) / abs(prev)) * 100))
        return changes


class SignalTag(str, Enum):
    """Tags for scored economic signals."""

    RECESSION_SIGNAL = "recession_signal"
    YIELD_CURVE_INVERTED = "yield_curve_inverted"
    YIELD_CURVE_STEEPENING = "yield_curve_steepening"
    INFLATION_RISING = "inflation_rising"
    INFLATION_COOLING = "inflation_cooling"
    JOBS_STRONG = "jobs_strong"
    JOBS_WEAKENING = "jobs_weakening"
    HOUSING_COOLING = "housing_cooling"
    HOUSING_HEATING = "housing_heating"
    BANK_STRESS = "bank_stress"
    OVERHEATING = "overheating"
    RATE_HIKE_SIGNAL = "rate_hike_signal"
    RATE_CUT_SIGNAL = "rate_cut_signal"
    LEADING_INDICATOR_DECLINE = "leading_indicator_decline"
    LEADING_INDICATOR_RISE = "leading_indicator_rise"
    REGIONAL_DIVERGENCE = "regional_divergence"


class ScoredSignal(BaseModel):
    """A scored economic signal from cross-source analysis."""

    signal_id: str = Field(description="Unique identifier for this signal")
    title: str = Field(description="Human-readable signal title")
    summary: str = Field(description="One-paragraph explanation of the signal")
    score: float = Field(ge=0.0, le=1.0, description="Signal strength from 0 (noise) to 1 (strong)")
    tags: list[SignalTag] = Field(default_factory=list)
    category: Category
    sources_used: list[DataSource] = Field(description="Which data sources contributed")
    contributing_series: list[str] = Field(default_factory=list, description="Series IDs that contributed")
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    data_as_of: date = Field(description="Most recent data date used in computation")


class RecessionProbability(BaseModel):
    """Composite recession probability from multiple indicators."""

    probability: float = Field(ge=0.0, le=1.0, description="0 = expansion, 1 = recession")
    assessment: str = Field(description="Human-readable assessment")
    contributing_signals: list[ScoredSignal]
    yield_curve_spread: Optional[float] = Field(None, description="10Y-2Y spread in percentage points")
    unemployment_trend: Optional[str] = Field(None, description="rising/stable/falling")
    leading_index_trend: Optional[str] = Field(None, description="rising/stable/falling")
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class HousingAffordability(BaseModel):
    """Composite housing affordability index."""

    index_value: float = Field(description="Higher = more affordable, 100 = baseline")
    median_home_price: Optional[float] = None
    median_income: Optional[float] = None
    mortgage_rate_30y: Optional[float] = None
    monthly_payment_estimate: Optional[float] = None
    assessment: str = Field(description="Human-readable affordability assessment")
    trend: str = Field(description="improving/stable/worsening")
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class BankHealthSummary(BaseModel):
    """Summary of banking system health from FDIC data."""

    total_institutions: int
    problem_institutions: int
    total_assets_billions: float
    problem_assets_billions: float
    avg_tier1_ratio: Optional[float] = None
    recent_failures: int = Field(description="Failures in last 12 months")
    assessment: str
    stress_score: float = Field(ge=0.0, le=1.0, description="0 = healthy, 1 = stressed")
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class EconomicComparison(BaseModel):
    """Comparison of two economic series over time."""

    series_a: EconomicSeries
    series_b: EconomicSeries
    correlation: Optional[float] = Field(None, description="Pearson correlation over overlapping period")
    summary: str = Field(description="Human-readable comparison summary")
