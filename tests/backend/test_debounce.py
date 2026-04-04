"""Tests for the async debouncer utility.

Covers the cancel/reschedule pattern: single trigger, rapid collapse
of same-key events, independent keys, cancel_all shutdown, callback
error isolation, and re-trigger after previous fire.

All tests use a very short delay (0.05s) so the suite runs quickly.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# sys.path setup — mirrors conftest.py convention
# ---------------------------------------------------------------------------

_SIDECAR_DIR = str(Path(__file__).resolve().parent.parent.parent / "sidecar")
if _SIDECAR_DIR not in sys.path:
    sys.path.insert(0, _SIDECAR_DIR)

from utils.debounce import AsyncDebouncer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHORT_DELAY: float = 0.05
"""Debounce delay used by all tests — short enough for fast CI runs."""

WAIT: float = SHORT_DELAY + 0.05
"""Time to sleep so that the debounce timer has definitely elapsed."""


# ===========================================================================
# Tests
# ===========================================================================


class TestAsyncDebouncer:
    """Core debounce behaviour of ``AsyncDebouncer``."""

    @pytest.mark.asyncio
    async def test_trigger_fires_after_delay(self) -> None:
        """A single trigger should invoke the callback exactly once
        after the debounce delay elapses."""
        callback = AsyncMock()
        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=callback)

        await debouncer.trigger("proj-1")
        await asyncio.sleep(WAIT)

        callback.assert_awaited_once_with("proj-1")

    @pytest.mark.asyncio
    async def test_rapid_triggers_same_key_collapse(self) -> None:
        """Rapid triggers for the same key should collapse into a single
        callback invocation — this is the core debounce guarantee."""
        callback = AsyncMock()
        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=callback)

        for _ in range(5):
            await debouncer.trigger("proj-1")

        await asyncio.sleep(WAIT)

        callback.assert_awaited_once_with("proj-1")

    @pytest.mark.asyncio
    async def test_different_keys_fire_independently(self) -> None:
        """Triggers for distinct keys should each fire their own
        callback, independently and without interfering."""
        callback = AsyncMock()
        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=callback)

        await debouncer.trigger("key-a")
        await debouncer.trigger("key-b")
        await asyncio.sleep(WAIT)

        assert callback.await_count == 2
        callback.assert_any_await("key-a")
        callback.assert_any_await("key-b")

    @pytest.mark.asyncio
    async def test_cancel_all_prevents_callback(self) -> None:
        """Calling ``cancel_all`` before the delay elapses should
        prevent the callback from ever being invoked."""
        callback = AsyncMock()
        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=callback)

        await debouncer.trigger("proj-1")
        await debouncer.cancel_all()
        await asyncio.sleep(WAIT)

        callback.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_error_is_isolated(self) -> None:
        """If the callback raises an exception the debouncer should
        log it and remain functional — subsequent triggers must still
        work."""
        call_count = 0

        async def flaky_callback(key: str) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("boom")

        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=flaky_callback)

        # First trigger — callback raises
        await debouncer.trigger("proj-1")
        await asyncio.sleep(WAIT)
        assert call_count == 1

        # Second trigger — callback should still fire despite previous error
        await debouncer.trigger("proj-2")
        await asyncio.sleep(WAIT)
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_trigger_after_previous_fires(self) -> None:
        """Triggering the same key again after its timer has already
        fired should invoke the callback a second time."""
        callback = AsyncMock()
        debouncer = AsyncDebouncer(delay=SHORT_DELAY, callback=callback)

        # First trigger + wait for it to fire
        await debouncer.trigger("proj-1")
        await asyncio.sleep(WAIT)
        assert callback.await_count == 1

        # Second trigger for the same key
        await debouncer.trigger("proj-1")
        await asyncio.sleep(WAIT)
        assert callback.await_count == 2

        # Both calls should have received the same key
        callback.assert_awaited_with("proj-1")
