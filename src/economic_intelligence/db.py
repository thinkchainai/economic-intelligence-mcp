"""SQLite database connection and schema management.

Data is stored in ~/.economic-mcp/data.db by default.
WAL mode is enabled for concurrent read/write from ingestors and tool queries.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = os.path.expanduser("~/.economic-mcp")


def get_data_dir() -> Path:
    """Get the data directory, creating it if needed."""
    data_dir = Path(os.environ.get("DATA_DIR", DEFAULT_DATA_DIR))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_url() -> str:
    """Get the SQLite database URL."""
    db_path = get_data_dir() / "data.db"
    return f"sqlite+aiosqlite:///{db_path}"


def _set_wal_mode(dbapi_connection, connection_record):
    """Enable WAL mode for concurrent reads during writes."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_db_url(), echo=False)
        event.listen(_engine.sync_engine, "connect", _set_wal_mode)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def init_db():
    """Create all tables if they don't exist."""
    from .sqlmodels import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database initialized at %s", get_data_dir() / "data.db")


async def close_db():
    """Close the database engine."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
