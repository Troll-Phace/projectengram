"""Per-key async debouncer for collapsing rapid filesystem events.

The file watcher may emit thousands of events for a single logical change
(e.g., ``npm install`` touching every file in ``node_modules``).  This
module provides ``AsyncDebouncer``, which collapses all events for the
same key (typically a project ID) into a single callback invocation that
fires only after a quiet period with no new events.

Implementation uses the cancel/reschedule pattern: each call to
``trigger(key)`` cancels the previous timer task for that key and starts
a fresh one.

Reference: ARCHITECTURE.md Section 8.2 — Debouncing.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

_log = logging.getLogger(__name__)

DEFAULT_DELAY: float = 5.0
"""Default debounce window in seconds."""


class AsyncDebouncer:
    """Per-key async debouncer using cancel/reschedule pattern.

    Each unique key maintains at most one pending ``asyncio.Task`` that
    sleeps for ``delay`` seconds before invoking ``callback(key)``.
    Calling ``trigger(key)`` while a timer is already pending cancels
    the existing timer and starts a new one, effectively resetting the
    debounce window.

    Args:
        delay: Debounce window in seconds.  Defaults to ``5.0``.
        callback: Async function called with the key string once the
            debounce window elapses without further triggers.

    Example::

        async def on_project_changed(project_id: str) -> None:
            await orchestrator.trigger_incremental_scan(project_id)

        debouncer = AsyncDebouncer(delay=5.0, callback=on_project_changed)
        await debouncer.trigger("proj-abc")  # starts 5s timer
        await debouncer.trigger("proj-abc")  # resets timer to 5s
        # ... 5 seconds of quiet ...
        # on_project_changed("proj-abc") is called once
    """

    def __init__(
        self,
        delay: float = DEFAULT_DELAY,
        *,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        self._delay: float = delay
        self._callback: Callable[[str], Awaitable[None]] = callback
        self._pending: dict[str, asyncio.Task[None]] = {}

    async def trigger(self, key: str) -> None:
        """Start or restart the debounce timer for the given key.

        If a timer is already pending for ``key``, it is cancelled and a
        new one is created.  The callback will fire ``delay`` seconds
        after the *last* call to ``trigger`` for this key.

        Args:
            key: Identifier for the debounce group (typically a project
                ID).
        """
        existing = self._pending.get(key)
        if existing is not None and not existing.done():
            existing.cancel()
            _log.debug("Cancelled pending debounce timer for key=%s", key)

        task = asyncio.create_task(
            self._wait_and_fire(key),
            name=f"debounce-{key}",
        )
        self._pending[key] = task

    async def cancel_all(self) -> None:
        """Cancel all pending debounce timers.

        Intended for use during application shutdown to prevent stale
        callbacks from firing after the orchestrator has stopped.
        """
        for key, task in self._pending.items():
            if not task.done():
                task.cancel()
                _log.debug("Shutdown: cancelled debounce timer for key=%s", key)

        # Await all tasks so CancelledError is raised and handled inside
        # each task before we clear the dict.
        if self._pending:
            await asyncio.gather(*self._pending.values(), return_exceptions=True)

        self._pending.clear()
        _log.debug("All debounce timers cancelled")

    async def _wait_and_fire(self, key: str) -> None:
        """Sleep for the debounce delay then invoke the callback.

        This coroutine is the body of each per-key timer task.
        ``CancelledError`` is expected when a newer trigger reschedules
        the timer and is silently swallowed.  Callback exceptions are
        logged but not propagated so one failing project does not break
        the debouncer for others.

        Args:
            key: The debounce group identifier passed to the callback.
        """
        try:
            await asyncio.sleep(self._delay)
        except asyncio.CancelledError:
            return

        # Timer elapsed — remove ourselves from pending before invoking
        # the callback so that a re-trigger during callback execution
        # starts a fresh entry.
        self._pending.pop(key, None)

        try:
            await self._callback(key)
        except Exception:
            _log.exception("Debounce callback failed for key=%s", key)
