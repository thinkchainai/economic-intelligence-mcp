"""SQLAlchemy models for local SQLite signal storage.

Only stores computed signals and recession probability — not raw observations.
Raw data is always fetched live from APIs. The database tracks how signals
change over time, enabling history, change detection, and alerts.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SignalSnapshot(Base):
    """A point-in-time snapshot of a scored economic signal."""

    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_name: Mapped[str] = mapped_column(String(100), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_signal_name_computed", "signal_name", "computed_at"),
        Index("ix_signal_data_as_of", "signal_name", "data_as_of"),
    )


class RecessionSnapshot(Base):
    """A point-in-time snapshot of the composite recession probability."""

    __tablename__ = "recession_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    assessment: Mapped[str] = mapped_column(Text, nullable=False)
    yield_curve_spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    unemployment_trend: Mapped[str | None] = mapped_column(String(20), nullable=True)
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    data_as_of: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_recession_computed", "computed_at"),
    )


class IngestionMeta(Base):
    """Track when the last backfill/refresh happened."""

    __tablename__ = "ingestion_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
