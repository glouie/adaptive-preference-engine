# Pre-Push Adversarial Review Hook — Design Spec

**Date:** 2026-04-25
**Status:** Approved
**Branch:** feat/pre-push-adversarial-hook

## Overview

A global git pre-push hook that runs adversarial review on every push. Blocks on critical/high code findings and on LLM instruction drift. Writes a full markdown report; prints a terminal summary.

## Goals

1. Block pushes with critical or high severity code issues (via Codex review)
2. For `.md` files targeting LLMs: red-team the changes and the full instruction chain for bypass/drift
3. Block pushes where compaction vulnerability ≤ 2 cycles
4. Produce an audit trail of findings per push
5. Run reviews in parallel to minimise wall-clock time

## Non-Goals

- Does not replace CI; this is a local safety gate
- Does not auto-fix code (report only)
- Does not push to any remote system
- Does not purge old reports (audit trail preserved indefinitely)

## Architecture

```
pre-push (bash shim)
  └── pre-push.py (Python orchestrator)
        ├── lib/detector.py      → detect active LLM
        ├── lib/models.py        → Severity, Finding, CodeReviewResult, RedTeamResult
        ├── lib/code_review.py   → run_code_review(), parse_findings()
        ├── lib/red_team.py      → run_red_team_change(), run_red_team_drift()
        └── lib/report.py        → write_report(), print_terminal_summary()

prompts/
  red_team_change.txt            → diff-level prompt
  red_team_drift.txt             → full instruction-chain prompt

reports/
  <timestamp>-<repo>-<branch>.md → per-push audit report
```

## LLM Identity Detection (lib/detector.py)

Detection order (first match wins):

1. `CLAUDE_MODEL` or `ANTHROPIC_MODEL` env vars → identity = `claude`
2. `CODEX_MODEL` env var → identity = `codex`
3. Parent process name via `ps -p $PPID -o comm=` → substring match `claude`/`codex`
4. Default → identity = `claude`

When identity = `claude`: Codex runs red-team (`codex exec "<prompt>"`)
When identity = `codex`: Claude runs red-team (`claude -p "<prompt>"`)
When default: Claude runs red-team (`claude -p "<prompt>"`)

## Parallel Workers (pre-push.py)

Three workers via `ThreadPoolExecutor(max_workers=3)`:

1. **code_review**: `codex review --base <upstream_sha>` — always runs
2. **red_team_change**: diff-only red-team — runs only if `.md` files changed
3. **red_team_drift**: full instruction-chain red-team — runs only if `.md` files changed

### Upstream SHA Resolution

- Fetch remote tracking branch SHA if it exists
- If new branch with no upstream: compare against `main` → `master` → `HEAD~1`

### Dynamic Timeout

Computed once before workers launch, shared by all:

```python
timeout = min(60 + (diff_files * 2) + (diff_lines // 50), 300)
```

Where `diff_files` = number of changed files, `diff_lines` = total changed lines.

## Code Review Worker (lib/code_review.py)

Command: `codex review --base <upstream_sha>`

### Severity Parsing

- Parse findings from stdout with `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`, `INFO` markers
- Unknown severity strings → default to `MEDIUM` (never silently dropped)
- Timeout → treated as block (fail-safe)

### Block Condition

Push blocked if any finding has severity `CRITICAL` or `HIGH`.

## Red-Team Workers (lib/red_team.py)

### Pass 1 — Change-Level (red_team_change.txt)

Prompt receives:
- The unified diff of changed `.md` files only
- Task: reason whether this diff weakens, bypasses, or introduces exploitable ambiguity in LLM instructions

### Pass 2 — Layered Drift (red_team_drift.txt)

Prompt receives the full instruction stack:
1. `~/.claude/CLAUDE.md` (global)
2. Project `CLAUDE.md` (if present)
3. `agents/*.md` (all agent files, alphabetical)
4. `SKILL.md` (if present)
5. The unified diff appended at the end

Task: reason whether the cumulative instruction stack drifts from its stated purpose, and estimate compaction vulnerability.

### Compaction Vulnerability

Red-team prompt asks the model to estimate: "how many `/compact` cycles before critical constraints fall out of context?" The response must include a line:

```
COMPACTION_CYCLES: <integer>
```

Parsed by report.py; block if `COMPACTION_CYCLES <= 2`.

### Block Condition

Push blocked if red-team severity `CRITICAL` or `HIGH`, OR `COMPACTION_CYCLES <= 2`.

## Severity Enum (lib/models.py)

```
CRITICAL > HIGH > MEDIUM > LOW > INFO
```

Parsed case-insensitively. Unknown strings → MEDIUM.

## Report Format (lib/report.py)

File: `~/.git-hooks/reports/<ISO8601>-<repo>-<branch>.md`

Sections:
1. Header: repo, branch, push SHA, timestamp, total elapsed time
2. Decision: BLOCKED / PASSED / SKIPPED
3. Code Review Findings: table of severity, file, description
4. Red-Team Pass 1 (Change-Level): severity, summary, key reasoning
5. Red-Team Pass 2 (Layered Drift): severity, compaction estimate, drift summary
6. Decision Audit: which rule triggered block (if blocked)

### Terminal Summary

Printed to stderr on completion:

```
─── Pre-Push Review ─────────────────────────────
  Status : BLOCKED
  Reason : code review found 2 HIGH findings
  Code   : 2 HIGH, 1 MEDIUM
  RedTeam: Pass 1 MEDIUM | Pass 2 HIGH (compaction: 3 cycles)
  Report : ~/.git-hooks/reports/2026-04-25T...md
─────────────────────────────────────────────────
```

## Skip / Bypass

`SKIP_REVIEW=1 git push` — skips workers, writes report with `[SKIPPED]` status, push proceeds.

- Never silently skips: report always written.
- Prints warning to stderr: `⚠  SKIP_REVIEW is set — adversarial review bypassed`
- Not recommended in CI: any process that can set env vars can bypass all blocking.

## Installation (install.sh)

1. Creates `~/.git-hooks/` directory tree
2. Writes `pre-push` bash shim (executable)
3. Runs `git config --global core.hooksPath ~/.git-hooks`
4. Verifies `python3`, `codex`, `claude` are on PATH (warns if missing, does not block)

## Key Design Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Python orchestrator (not bash) | Parallel workers, structured parsing, testable |
| 2 | Dynamic timeout formula | Proportional to change size; avoids false timeouts on tiny diffs |
| 3 | Timeout = block | Fail-safe: a slow/broken review should not silently pass a push |
| 4 | Unknown severity → MEDIUM | Never silently drop findings |
| 5 | Compaction threshold ≤ 2 → block | 2 cycles is too fragile for production instruction integrity |
| 6 | Missing `COMPACTION_CYCLES` → block | Fail-safe: model refusal or format deviation must not silently pass |
| 7 | Reports preserved indefinitely | Audit trail; user can prune manually |
| 8 | SKIP_REVIEW always writes report + warns stderr | Bypass is visible, not silent |
| 9 | Cross-model diversity | Claude reviews what Codex writes and vice versa — reduces blind spots |
| 10 | Red-team pass 1 + pass 2 in parallel | Both take similar time; no dependency between them |
| 11 | New branch → compare against main/master/HEAD~1 | Graceful fallback when no remote tracking branch exists |
| 12 | Report filename sanitized (alphanumeric/-/_) | Prevents path traversal from malicious repo/branch names |
| 13 | Instruction stack snapshotted before workers launch | Avoids race condition if push itself adds agent `.md` files |
