---
name: adaptive-preferences
description: >
  Adaptive Preference Engine — auto-loads learned user preferences at the start of every Claude session
  and silently records corrections and feedback to improve over time. ALWAYS trigger this skill at the
  start of any substantive task or conversation. Use it to: load preferences before responding, record
  when the user corrects Claude's output format or style, and record positive feedback signals. Trigger
  on every new task, every request for code, writing, explanations, or any output where style/format
  matters. This skill should run in the background on virtually every interaction.
---

# 🦧 Adaptive Preference Engine

This skill connects Claude to a behavior-driven preference learning system. It watches how the user
interacts, learns from corrections and feedback, and builds a growing model of what they actually prefer.

**Core philosophy:** "Your preferences aren't what you say. They're what you do."

---

## How This Skill Works

The engine stores preferences as JSONL files at `~/.adaptive-cli/`. It learns from three signal types:

1. **Corrections** — user says "actually use X not Y" → strongest learning signal
2. **Feedback** — user says "perfect!" or "not quite" → emotional signal
3. **Usage** — implicit patterns from repeated choices

---

## APE Buddy (Context Isolation)

If `adaptive-cli buddy status` returns `enabled`, delegate **all** APE operations to the
`ape-buddy` agent instead of running CLI commands directly. This keeps preference bookkeeping
out of the main context window.

**How to delegate:**

```
Agent(subagent_type="ape-buddy", prompt="load python api_design")
Agent(subagent_type="ape-buddy", prompt="record_correction task=api_design context=python proposed=bullets corrected=table message='tables work better here'", run_in_background=True)
```

**What the buddy returns:** a single summary line — apply it silently.
**When buddy is disabled:** fall through to the direct CLI instructions below.

---

## Startup: Two-Phase Preference Loading

### Phase 1 — Session start (automatic, via hook)

A `SessionStart` hook runs `adaptive-cli registry` and injects a compact payload (~30 tokens) listing
all known preference paths and context nodes. This gives Claude a map of what is available without
loading full preference trees up front.

### Phase 2 — On-demand pre-task load (standing instruction)

**Before any produce, summarize, or explain task**, silently run:

```bash
adaptive-cli agent-context --context <inferred-context>
```

Where `<inferred-context>` is one or more tags inferred from the task — e.g., `python`, `writing`,
`api_design`, `code_review`. This writes `~/.adaptive-cli/last_context.txt` so the PreCompact hook
can re-inject the same context when compaction is triggered.

If no stored preferences exist yet, skip gracefully. The engine will start learning from this session.

**Apply what you load:** If preferences indicate `communication.output_format.table` at high confidence,
use tables. If `communication.depth.detailed` is preferred, be thorough. Let the loaded preferences
silently shape your response style.

### Compact preservation

A `PreCompact` hook re-runs `agent-context` for the last known context and injects both the preferences
and this standing instruction into the compacted summary — so preferences survive compaction without
manual re-loading.

---

## During the Session: Detect and Record Signals

### Correction Signal (most important)

When the user says things like:
- "Actually, use a table instead"
- "Can you reformat that as bullets?"
- "That's too long / too short"
- "Don't use headers"
- Any explicit format/style correction

**Record it immediately:**

```bash
python <skill-scripts-path>/cli.py signal correction \
  --task <current_task> \
  --context <context_tags> \
  --proposed <what_you_used> \
  --corrected <what_they_want> \
  --message "<their exact words>"
```

### Feedback Signal

When the user says things like:
- "Perfect!", "Exactly!", "That's what I needed"
- "Not quite", "That's not right"
- Any emotional response to your output

**Record it:**

```bash
python <skill-scripts-path>/cli.py signal feedback \
  --task <current_task> \
  --context <context_tags> \
  --preferences <preferences_you_used> \
  --response "<their exact words>"
```

---

## Python Integration (for agents)

```python
from scripts.agent_hook import AgentPreferenceHook

hook = AgentPreferenceHook()

# Load preferences
prefs_json = hook.get_preferences_for_context(["python", "api_design"])

# Record a correction
hook.report_correction(
    task="api_design",
    context_tags=["python"],
    agent_proposed="bullets",
    user_corrected_to="table",
    user_message="Tables work better here!"
)

# Record feedback
hook.report_feedback(
    task="explanation",
    context_tags=["python"],
    preferences_used=["communication.output_format.bullets"],
    user_response="Perfect, exactly what I needed!"
)
```

---

## Data Storage

All preference data lives at:
```
~/.adaptive-cli/
├── preferences/
│   ├── all_preferences.jsonl
│   ├── associations.jsonl
│   ├── contexts.jsonl
│   └── signals.jsonl
└── backups/
```

Human-readable JSONL format — no database required. Persists across all Claude sessions.

---

## Strength Evolution

Preference strengths update automatically:

```
strength = frequency × trend × emotion × recency
```

- **Time decay**: 2% per day unused (stale preferences fade)
- **Trend detection**: repeated corrections in same direction → multiplier boost
- **Emotional boost**: "perfect!" feedback increases confidence significantly

Run periodically to maintain the engine:

```bash
python <skill-scripts-path>/cli.py decay        # apply time decay
python <skill-scripts-path>/cli.py recalculate  # recalculate all strengths
python <skill-scripts-path>/cli.py stats        # view statistics
```

---

## Context Tags

Use these standard context tags when recording signals:

| Context | When to use |
|---------|-------------|
| `python` | Python code tasks |
| `javascript` | JS/TS tasks |
| `api_design` | API design and docs |
| `code_review` | Reviewing code |
| `writing` | Prose, emails, docs |
| `explanation` | Explaining concepts |
| `data_analysis` | Data work |
| `general` | Anything else |

---

## Silent Operation

This skill should operate **silently in the background**. Do not:
- Tell the user "I'm loading your preferences"
- Announce that you're recording a signal
- Ask permission before recording corrections

Just do it. The user should notice the system getting smarter over time, not see it working.

---

## Scripts Path

The engine scripts are bundled with this skill in `scripts/`. Reference them as:
```
<absolute-path-to-this-skill>/scripts/cli.py
<absolute-path-to-this-skill>/scripts/agent_hook.py
```

If the user has the project saved elsewhere (e.g., `~/adaptive-preference-engine/scripts/`), use that path instead.

---

## Audit Agents

The skill includes four specialized audit agents. Spawn them when the user asks for an audit,
review, health check, or "how is the engine doing?" — or proactively after every ~50 signals.

Read the relevant agent file before spawning:

| Agent | File | When to use |
|-------|------|-------------|
| **Signal Auditor** | `agents/signal-auditor.md` | Review recorded signals for quality and accuracy |
| **Preference Health Checker** | `agents/preference-health-checker.md` | Detect stale, conflicting, or overfit preferences |
| **Drift Detector** | `agents/drift-detector.md` | Find preferences that are shifting or reversing over time |
| **Coverage Auditor** | `agents/coverage-auditor.md` | Identify blind spots — contexts with no preference data |

### Running a Full Audit

When the user asks for a full audit, spawn all four agents in parallel:

```
Spawn: Signal Auditor      → reads signals.jsonl
Spawn: Health Checker      → reads preferences + associations
Spawn: Drift Detector      → reads signals ordered by date
Spawn: Coverage Auditor    → reads signals + preferences + contexts
```

Then synthesize their reports into a single **Preference Engine Audit Summary** with:
- Overall system health score (average of health + coverage scores)
- Top 3 issues to fix (ranked by impact)
- Quick-win commands to run immediately

### Audit Schedule Recommendation

- **Weekly**: Signal Auditor (catch bad signals early)
- **Monthly**: Full audit (all four agents)
- **After major project change**: Drift Detector + Coverage Auditor
