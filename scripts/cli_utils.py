"""cli_utils.py - Shared display utilities for adaptive-cli"""
import shutil
import sys


def _supports_color() -> bool:
    return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


RESET  = "\033[0m"  if _supports_color() else ""
BOLD   = "\033[1m"  if _supports_color() else ""
DIM    = "\033[2m"  if _supports_color() else ""
GREEN  = "\033[32m" if _supports_color() else ""
YELLOW = "\033[33m" if _supports_color() else ""
CYAN   = "\033[36m" if _supports_color() else ""
RED    = "\033[31m" if _supports_color() else ""


def term_width() -> int:
    """Return current terminal width, defaulting to 80."""
    return shutil.get_terminal_size(fallback=(80, 24)).columns


def separator(char: str = "─") -> str:
    """Return a full-width separator line."""
    return char * term_width()


def header(title: str) -> str:
    """Return a titled section header with separator."""
    return f"\n{BOLD}{CYAN}{title}{RESET}\n{separator()}"


def success(msg: str) -> str:
    return f"{GREEN}✅ {msg}{RESET}"


def error(msg: str) -> str:
    return f"{RED}❌ {msg}{RESET}"


def warn(msg: str) -> str:
    return f"{YELLOW}⚠️  {msg}{RESET}"
