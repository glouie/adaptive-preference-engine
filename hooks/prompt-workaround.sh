#!/usr/bin/env bash
# WORKAROUND for "ToolUseContext is required for prompt hooks" bug
# Bug: https://github.com/anthropics/claude-code/issues/39184
#
# prompt-type hooks fail on SessionStart with:
#   "Failed to run: ToolUseContext is required for prompt hooks. This is a bug."
#
# This script emits the original prompt text via stdout so a command-type
# hook can inject it into the session instead.
#
# TODO(anthropics/claude-code#39184): When the bug is fixed, revert hooks.json
# to use the original type:prompt hook and delete this file. The original
# prompt text is preserved below between the EOF markers for easy copy-paste.
cat <<'EOF'
The adaptive preference engine is active. It learns your preferences by observing corrections and feedback — not by asking. When the user corrects your approach (e.g., 'actually use X not Y', 'I prefer tables here', 'no, do it this way'), silently record it by running: python3 $CLAUDE_PLUGIN_ROOT/scripts/cli.py signal correction --task <task_context> --context <language_or_project> --proposed <what_you_did> --corrected <what_user_wanted> --message '<user_quote>'. When the user gives positive feedback (e.g., 'perfect!', 'exactly', 'yes that's right'), record it by running: python3 $CLAUDE_PLUGIN_ROOT/scripts/cli.py signal feedback --task <task_context> --context <language_or_project> --preferences <pref_path> --response '<user_quote>' --satisfaction 0.9. Do this silently. Never mention the preference engine to the user unless they ask about it.
EOF
