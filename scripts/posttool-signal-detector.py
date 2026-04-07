#!/usr/bin/env python3
"""
posttool-signal-detector.py — Command-type PostToolUse hook for APE.

Reads the hook's stdin JSON, extracts recent user messages from the
transcript, and scans for correction/preference keywords. When a
keyword match is found, records a signal in the APE database via CLI.

Runs silently — only prints output when a signal is recorded.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ── Keyword patterns grouped by intent ───────────────────────────────

CORRECTION_KEYWORDS = [
    r"\bno[,.\s!]",
    r"\bdon'?t\b",
    r"\bstop\b",
    r"\bwrong\b",
    r"\bnot that\b",
    r"\bactually\b",
    r"\binstead\b",
    r"\brather\b",
    r"\bshould be\b",
    r"\bshould have\b",
    r"\bshouldn'?t\b",
    r"\bnever\b",
    r"\balways\b",
]

PREFERENCE_KEYWORDS = [
    r"\bprefer\b",
    r"\bpreference\b",
    r"\bi like\b",
    r"\bi want\b",
    r"\bi need\b",
    r"\bi'?d like\b",
    r"\bplease use\b",
    r"\bplease don'?t\b",
    r"\bkeep it\b",
    r"\bmake sure\b",
    r"\bfrom now on\b",
    r"\bgoing forward\b",
    r"\bin the future\b",
    r"\bremember that\b",
    r"\bremember to\b",
]

POSITIVE_KEYWORDS = [
    r"\bperfect\b",
    r"\bexactly\b",
    r"\byes[\s!.,]",
    r"\bthat'?s right\b",
    r"\bthat'?s correct\b",
    r"\bgood call\b",
    r"\bgreat\b",
    r"\bnice\b",
    r"\blove it\b",
    r"\bkeep doing\b",
]

# Skip automated/system messages
SKIP_PREFIXES = [
    "Dispatch Slack poll",
    "<system-reminder>",
    "Run a Slack monitor",
]

LOOKBACK_MESSAGES = 5


# ── Helpers ──────────────────────────────────────────────────────────

def extract_recent_user_messages(transcript_path, n=LOOKBACK_MESSAGES):
    """Extract the last N user messages from the transcript JSONL."""
    messages = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                role = entry.get("role", "")
                if role == "user":
                    content = entry.get("content", "")
                    if isinstance(content, list):
                        text_parts = [
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        content = " ".join(text_parts)
                    if isinstance(content, str) and content.strip():
                        messages.append(content.strip())
                elif entry.get("type") == "human":
                    content = entry.get("message", entry.get("text", ""))
                    if isinstance(content, str) and content.strip():
                        messages.append(content.strip())
    except (FileNotFoundError, PermissionError):
        return []

    return messages[-n:]


def should_skip(msg):
    """Return True if the message is automated and should be ignored."""
    for prefix in SKIP_PREFIXES:
        if msg.startswith(prefix):
            return True
    return False


def match_keywords(text, patterns):
    """Return all keyword patterns that match in the text."""
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def detect_context(cwd):
    """Detect git repo name from cwd, fallback to 'general'."""
    if not cwd:
        return "general"
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd, timeout=5
        )
        if result.returncode == 0:
            return os.path.basename(result.stdout.strip())
    except Exception:
        pass
    return "general"


def record_correction(cli_path, task, context, proposed, corrected, message):
    """Record a correction/preference signal via CLI."""
    cmd = [
        sys.executable, cli_path,
        "signal", "correction",
        "--task", task,
        "--context", context,
        "--proposed", proposed,
        "--corrected", corrected,
        "--message", message,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            preview = corrected[:80].replace("\n", " ")
            print(f"APE: recorded signal — {preview}")
    except Exception:
        pass


def record_feedback(cli_path, task, context, message):
    """Record a positive feedback signal via CLI."""
    cmd = [
        sys.executable, cli_path,
        "signal", "feedback",
        "--task", task,
        "--context", context,
        "--preferences", "general",
        "--response", message[:200],
        "--satisfaction", "0.9",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("APE: recorded positive feedback")
    except Exception:
        pass


# ── Main ─────────────────────────────────────────────────────────────

def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        return

    tool_name = hook_input.get("tool_name", "")
    transcript_path = hook_input.get("transcript_path", "")

    if not transcript_path or not os.path.exists(transcript_path):
        return

    plugin_root = os.environ.get(
        "CLAUDE_PLUGIN_ROOT",
        str(Path(__file__).parent.parent)
    )
    cli_path = os.path.join(plugin_root, "scripts", "cli.py")
    if not os.path.exists(cli_path):
        return

    context = detect_context(hook_input.get("cwd", ""))
    recent_messages = extract_recent_user_messages(transcript_path)
    if not recent_messages:
        return

    # Scan recent user messages (newest first) for keyword matches
    for msg in reversed(recent_messages):
        if should_skip(msg):
            continue

        correction_hits = match_keywords(msg, CORRECTION_KEYWORDS)
        preference_hits = match_keywords(msg, PREFERENCE_KEYWORDS)
        positive_hits = match_keywords(msg, POSITIVE_KEYWORDS)

        if correction_hits or preference_hits:
            task = f"{tool_name}_usage"
            tool_input = hook_input.get("tool_input", {})
            if isinstance(tool_input, dict):
                proposed = json.dumps(
                    {k: str(v)[:100] for k, v in list(tool_input.items())[:3]},
                    ensure_ascii=False
                )
            else:
                proposed = str(tool_input)[:200]

            matched = correction_hits + preference_hits
            record_correction(
                cli_path=cli_path,
                task=task,
                context=context,
                proposed=proposed,
                corrected=msg[:200],
                message=f"keywords: {', '.join(matched)}"
            )
            return  # One signal per invocation

        if positive_hits:
            record_feedback(
                cli_path=cli_path,
                task=f"{tool_name}_usage",
                context=context,
                message=msg[:200]
            )
            return


if __name__ == "__main__":
    main()
