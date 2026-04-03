"""ULID generation utility for Engram primary keys."""

from ulid import ULID


def generate_ulid() -> str:
    """Generate a new ULID string for use as a database primary key.

    Returns:
        A 26-character ULID string.
    """
    return str(ULID())
