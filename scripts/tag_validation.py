"""Tag validation for APE knowledge entries and signal tags."""

import re

TAG_REGEX = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]*$')


def validate_tag(tag: str) -> bool:
    """Return True if tag matches the allowed pattern.

    Allowed: alphanumeric start, then alphanumeric plus '.' and '-'.
    Rejected: underscore and percent (SQLite LIKE wildcards), spaces, empty.
    """
    if not tag:
        return False
    return TAG_REGEX.match(tag) is not None
