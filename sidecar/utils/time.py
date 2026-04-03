"""Shared time utilities for the Engram sidecar."""

from datetime import UTC, datetime


def now_iso() -> str:
    """Return the current UTC time as an ISO 8601 string.

    Returns:
        A string in ``YYYY-MM-DDTHH:MM:SSZ`` format.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
