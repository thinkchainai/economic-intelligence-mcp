"""Signal refresh scheduler.

Runs backfill on first start, then refreshes signals on a configurable schedule.
Uses asyncio tasks — no external scheduler dependency.
"""

from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_INTERVAL_HOURS = 6


class SignalScheduler:
    """Manages periodic signal computation and storage."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False
        self._interval_seconds = int(os.environ.get(
            "REFRESH_INTERVAL_HOURS",
            str(DEFAULT_REFRESH_INTERVAL_HOURS),
        )) * 3600

    async def start(self):
        """Start the background signal refresh loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Signal scheduler started (interval: %d hours)", self._interval_seconds // 3600)

    async def stop(self):
        """Stop the background signal refresh loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Signal scheduler stopped")

    async def _run_loop(self):
        """Main scheduler loop — backfill if needed, then periodic refresh."""
        from .ingestors import needs_backfill, run_backfill, run_refresh

        fred_api_key = os.environ.get("FRED_API_KEY", "")
        if not fred_api_key:
            logger.warning("FRED_API_KEY not set — signal scheduler disabled")
            return

        try:
            if await needs_backfill():
                logger.info("First run detected — running historical backfill")
                await run_backfill(fred_api_key)
            else:
                logger.info("Backfill already complete — running immediate refresh")
                await run_refresh(fred_api_key)
        except Exception as exc:
            logger.error("Initial signal computation failed: %s", exc, exc_info=True)

        while self._running:
            try:
                await asyncio.sleep(self._interval_seconds)
                if not self._running:
                    break
                await run_refresh(fred_api_key)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Scheduled signal refresh failed: %s", exc, exc_info=True)
                await asyncio.sleep(60)
