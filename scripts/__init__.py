"""
Compatibility package for legacy ``scripts.*`` imports.

Phase 1 of the Claude-first migration keeps the existing import surface stable
while core runtime modules live under ``src/adaptive_preference_engine``.
"""

from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"

if _SRC.is_dir():
    src_str = str(_SRC)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
