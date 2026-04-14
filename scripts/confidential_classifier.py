"""Classify knowledge entries as confidential based on content pattern matching."""

from typing import List, Optional

DEFAULT_PATTERNS = [
    "~/notes-vault",
    "~/learning/",
    "/Users/",
    "cd.splunkdev.com",
    "@cisco.com",
]


def is_confidential(content: str, patterns: Optional[List[str]] = None) -> bool:
    """Return True if content matches any confidential pattern."""
    check_patterns = patterns if patterns is not None else DEFAULT_PATTERNS
    for pattern in check_patterns:
        if pattern in content:
            return True
    return False
