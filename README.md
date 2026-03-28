# Adaptive Preference Engine - Phase 1 Implementation

## 🎯 What You've Built

A **behavior-driven preference learning system** that grows with your coding habits through intelligent observation, bidirectional associations, and context-aware loading.

**Not a preference tracker. A preference learner.**

---

## 📦 What's Included

### Core Modules

| Module | Purpose |
|--------|---------|
| **models.py** | Data structures (Preference, Association, ContextStack, Signal) |
| **storage.py** | JSONL file persistence and queries |
| **preference_loader.py** | Load prefs with associations (Option C: diminishing confidence) |
| **signal_processor.py** | Process corrections/feedback, update strengths dynamically |
| **cli.py** | Full command-line interface |
| **agent_hook.py** | Integration point for AI agents |

### Documentation

| Document | Purpose |
|----------|---------|
| **PHASE1_DESIGN.md** | Complete architecture and algorithms |
| **README.md** | This file |
| **demo.py** | Working example of complete workflow |

---

## 🚀 Quick Start

### Installation

```bash
# Clone/copy the project
cd adaptive-preference-engine

# Optional: Make CLI executable
chmod +x scripts/cli.py

# Run demo
python demo.py
```

### Basic Usage

```bash
# Create a preference
python scripts/cli.py pref create \
  --name bullets \
  --path communication.output_format.bullets \
  --type variant

# Create an association
python scripts/cli.py assoc create \
  --from-id communication.output_format.table \
  --to-id coding.data_structure_clarity \
  --strength-forward 0.95 \
  --strength-backward 0.70

# Record a correction (learning signal)
python scripts/cli.py signal correction \
  --task api_design \
  --context python fastapi \
  --proposed communication.output_format.bullets \
  --corrected communication.output_format.table \
  --message "Perfect! That's exactly what I needed!"

# Load preferences for a context
python scripts/cli.py load --context python api_design

# Generate JSON for agent
python scripts/cli.py agent-context --context python fastapi
```

---

## 🧠 Core Concepts

### **1. Preferences (Hierarchical)**

Preferences form trees with three levels:

```
communication/
  output_format (selector)
    ├── bullets (variant)
    ├── table (variant)
    └── prose (variant)
```

Each preference has:
- **Value**: Current selection
- **Confidence**: How sure system is (0-1)
- **Learning data**: Use count, satisfaction rate, trend

### **2. Associations (Bidirectional + Asymmetrical)**

Two preferences can be linked with **different strengths in each direction**:

```
table ──→ data_structure_clarity  (strength: 0.95)
     ←─────────                    (strength: 0.50)
```

**Why asymmetrical?** 
- table → data_structure: strong (tables explain structure well)
- data_structure → table: weaker (structure doesn't always need tables)

### **3. Context Stacking**

Three levels of context, later overrides earlier:

```
Base level (always active)
  ↓
Project level (when working on specific project)
  ↓
Conversation level (for this chat/session)
```

### **4. Behavioral Signals**

System learns through three types of signals:

1. **Corrections**: "Actually, I prefer X not Y" (strongest signal)
2. **Feedback**: "Yes, exactly what I needed!" (emotional signal)
3. **Usage**: Implicit learning from what you choose

---

## 🔄 How It Learns

### Example Flow

```
You: "Help me design an API"
System: Loads base + project preferences
Agent: Uses bullets format (your stated preference)

You: "Actually, use a table to show the response structure"
System: 
  1. Detects correction
  2. Finds associations with "table" preference
  3. Increments table's confidence
  4. Decrements bullets' confidence
  5. Strengthens table ↔ data_structure association
  6. Records emotional signal (you were satisfied)

Next time you ask about API responses:
  System: "Last time you corrected to tables for this..."
  Agent: Automatically uses table format
```

### Strength Calculation

Association strength evolves based on:

```
strength = frequency × trend × emotion × recency

Where:
  frequency = how often used (0-1)
  trend = direction of change (0.7 to 1.15)
  emotion = user satisfaction (0.5 to 1.0)
  recency = time decay (2% per day unused)
```

---

## 🔧 Key Features

✅ **Bidirectional Associations**
- Preferences can link to other preferences
- Each direction has independent strength
- Learn which preferences cluster together

✅ **Dynamic Strength Evolution**
- Not static, changes with behavior
- Emotional signals boost confidence
- Time decay prevents stale preferences
- Trend detection shows direction

✅ **Context Stacking**
- Project-specific preferences override base
- Conversation context can override both
- Clean separation of concerns

✅ **Option C Preference Loading**
- Follow association chains with diminishing confidence
- Stop when confidence drops below threshold (0.45)
- Max depth prevents infinite chains (3 levels)
- Smart preference discovery through associations

✅ **Behavioral Learning**
- Corrections treated as learning moments, not failures
- Emotional tone extracted from user messages
- No manual preference definition needed
- Aspirational vs. actual preference detection

✅ **Agent Integration**
- Preferences injected into agent context
- Agent knows confidence levels
- Feedback/corrections loop back into system

---

## 📊 Data Flow Diagram

```
┌──────────────────┐
│  USER / AGENT    │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│  PREFERENCE LOADER (Option C)            │
│  • Load primary preference               │
│  • Follow associations with              │
│    diminishing confidence                │
│  • Stack contexts (base→project→conv)    │
└──────────────┬───────────────────────────┘
               │
               ▼
        ┌─────────────┐
        │ AGENT SEES: │
        │ {           │
        │  primary: ...,
        │  associated: [...]
        │  confidences: [...]
        │ }           │
        └──────┬──────┘
               │
               ▼
      ┌────────────────┐
      │ AGENT RESPONDS │
      └────────┬───────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
  Accept    Correct    Feedback
    │          │          │
    └──────────┼──────────┘
               │
               ▼
    ┌──────────────────────┐
    │ SIGNAL PROCESSOR     │
    │ • Update association │
    │   strengths          │
    │ • Update confidence  │
    │ • Record signal      │
    └──────────┬───────────┘
               │
               ▼
    ┌──────────────────────┐
    │ STORAGE              │
    │ • preferences.jsonl  │
    │ • associations.jsonl │
    │ • contexts.jsonl     │
    │ • signals.jsonl      │
    └──────────────────────┘
```

---

## 📁 Project Structure

```
adaptive-preference-engine/
├── scripts/
│   ├── models.py              # Data models
│   ├── storage.py             # JSONL storage
│   ├── preference_loader.py   # Core loading logic
│   ├── signal_processor.py    # Learning from signals
│   ├── cli.py                 # Command-line interface
│   └── agent_hook.py          # Agent integration
├── PHASE1_DESIGN.md           # Complete design doc
├── README.md                  # This file
├── demo.py                    # Working example
└── ~/.adaptive-cli/           # Data storage (runtime)
    ├── preferences/
    │   ├── all_preferences.jsonl
    │   ├── associations.jsonl
    │   ├── contexts.jsonl
    │   └── signals.jsonl
    └── backups/
```

---

## 🎓 Usage Examples

### Example 1: Python Project with Context

```bash
# Create base preferences
adaptive-cli pref create --name python --path coding.language.python --type variant
adaptive-cli pref create --name fastapi --path coding.framework.fastapi --type variant

# Create project context
adaptive-cli context create --name "FastAPI Project" --scope project
adaptive-cli context set-pref <ctx_id> coding.language python 0.95

# Agent loads preferences
adaptive-cli agent-context --context python fastapi --stack ctx_base <ctx_id>

# User makes corrections
adaptive-cli signal correction \
  --task api_documentation \
  --context python fastapi \
  --proposed communication.output_format.bullets \
  --corrected communication.output_format.table \
  --message "Yes, tables are perfect for showing API endpoints!"

# System learns: FastAPI + tables = strong association
```

### Example 2: Learning from Feedback

```bash
# Record positive feedback
adaptive-cli signal feedback \
  --task code_explanation \
  --context python \
  --preferences communication.output_format.bullets communication.depth.detailed \
  --response "That explanation was crystal clear! Exactly the level of detail I needed." \
  --satisfaction 0.95

# System boosts confidence in both preferences
# Strengthens association between bullets + detailed depth
```

---

## 🔮 What's NOT Included (Phase 2+)

- ❌ Automatic category creation
- ❌ Web UI / dashboard
- ❌ IDE plugins
- ❌ Team/collaborative preferences
- ❌ ML-based predictions
- ❌ Agentic automation loops
- ❌ Advanced analytics

These will be Phase 2, 3, and beyond as the system matures.

---

## 🧪 Testing

Run the demo to see everything in action:

```bash
python demo.py
```

Output shows:
- ✓ Creating preferences
- ✓ Creating associations
- ✓ Creating contexts
- ✓ Loading with Option C
- ✓ Processing corrections
- ✓ Strength evolution
- ✓ Agent JSON generation

---

## 🤝 For Agent Integration

Agents can integrate simply:

```python
from scripts.agent_hook import AgentPreferenceHook

hook = AgentPreferenceHook()

# Get preferences
prefs = hook.get_preferences_for_context(["python", "api_design"])

# Use in response generation
# ...

# Report correction
hook.report_correction(
    task="api_design",
    context_tags=["python"],
    agent_proposed="bullets",
    user_corrected_to="table",
    user_message="Perfect!"
)
```

---

## 📈 Strength Evolution Example

```
Day 1: User corrects bullets → table
  table strength: 0.40 → 0.50

Day 3: User corrects bullets → table again
  table strength: 0.50 → 0.65

Day 7: Trend detected (increasing)
  trend_multiplier = 1.15
  table strength: 0.65 → 0.75

Day 14: User says "Yes, tables are perfect!"
  satisfaction_rate: 0.75 → 0.85
  emotion_multiplier increases
  table strength: 0.75 → 0.88

System learns: User strongly prefers tables
```

---

## ✅ Phase 1 Completion

- ✅ Core data models
- ✅ JSONL storage with full CRUD
- ✅ Option C preference loading (diminishing confidence)
- ✅ Bidirectional associations with asymmetrical strength
- ✅ Context stacking (base/project/conversation)
- ✅ Signal processing (corrections + feedback)
- ✅ Dynamic strength calculation
- ✅ Time decay for stale preferences
- ✅ Emotional signal detection
- ✅ Full CLI interface
- ✅ Agent integration hook
- ✅ Complete documentation
- ✅ Working demo

---

## 🎯 Philosophy

> **Your preferences aren't what you say. They're what you do.**

This system doesn't ask you to define preferences. It watches, learns, and suggests. When you correct it, that's a learning moment. When you express satisfaction, that's evidence. Over time, the system becomes an extension of your thinking—anticipating your needs before you voice them.

---

## 🚀 Next Phase (Phase 2)

When you're ready:
- Auto-detect new preference categories
- Implement agentic feedback loops
- Add predictive suggestions
- Build web dashboard
- Integrate with IDE plugins

The foundation is solid. The learning mechanism is in place. Phase 2 will build intelligence on top of this.

---

## 📞 Quick Reference

```bash
# Create
adaptive-cli pref create --name X --path Y --type Z
adaptive-cli assoc create --from-id A --to-id B --strength-forward 0.9
adaptive-cli context create --name X --scope base|project|conversation

# View
adaptive-cli pref show <id>
adaptive-cli pref list
adaptive-cli assoc show <id>
adaptive-cli context show <id>

# Learn
adaptive-cli signal correction --task X --context Y --proposed A --corrected B
adaptive-cli signal feedback --task X --context Y --preferences A B --response "..."

# Load
adaptive-cli load --context X Y Z
adaptive-cli agent-context --context X Y Z

# Maintain
adaptive-cli recalculate       # Recalculate all strengths
adaptive-cli decay             # Apply time decay
adaptive-cli stats             # Show statistics
adaptive-cli reset             # Reset everything
```

---

**Phase 1 is complete. You have a working, testable, extensible preference learning engine.**

Ready to evolve to Phase 2? 🚀
