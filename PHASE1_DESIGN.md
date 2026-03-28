# Adaptive Preference Engine - Phase 1 Complete Design Document

## 🎯 Overview

The Adaptive Preference Engine learns user preferences through behavior observation, bidirectional associations with asymmetrical strength, and context-aware preference loading.

**Key Insight:** Preferences aren't static - they evolve based on actual usage patterns, emotional signals, and corrections.

---

## 📊 Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│                    AGENT / USER SESSION                     │
└─────────────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│         AGENT PREFERENCE HOOK (agent_hook.py)               │
│  • get_preferences_for_context()                            │
│  • report_correction()                                      │
│  • report_feedback()                                        │
│  • inject_preferences()                                     │
└─────────────────────────────────────────────────────────────┘
              │
        ┌─────┴─────┬──────────────┬───────────────┐
        ▼           ▼              ▼               ▼
    PREFERENCE  ASSOCIATION   CONTEXT        SIGNAL
    LOADER      FOLLOWER      STACK          PROCESSOR
    (Option C)  (bidirectional)(Stacking)     (Learning)
              │
              ▼
┌─────────────────────────────────────────────────────────────┐
│           STORAGE MANAGER (storage.py)                      │
│  JSONL Files:                                               │
│  • all_preferences.jsonl      (Preference data)             │
│  • associations.jsonl         (Bidirectional links)         │
│  • contexts.jsonl             (Context stacks)              │
│  • signals.jsonl              (Learning events)             │
└─────────────────────────────────────────────────────────────┘
```

---

## 📁 Data Models

### **Preference**
```python
{
  "id": "comm_bullets",
  "path": "communication.output_format.bullets",
  "parent_id": "comm_format",
  "name": "bullets",
  "type": "variant",              # selector | variant | property
  "value": "active",
  "confidence": 0.85,             # 0.0 to 1.0
  "learning": {
    "use_count": 156,
    "satisfaction_rate": 0.91,
    "trend": "increasing"         # or stable/decreasing
  }
}
```

### **Association (Bidirectional + Asymmetrical)**
```python
{
  "id": "assoc_table_datastructure",
  "from_id": "communication.output_format.table",
  "to_id": "coding.data_structure_clarity",
  "bidirectional": true,
  
  "strength_forward": 0.95,       # table → data_structure
  "strength_backward": 0.70,      # data_structure → table
  
  "learning_forward": {
    "use_count": 47,
    "satisfaction_rate": 0.89,
    "trend": "increasing",
    "weekly_usage": [3, 4, 5, 6, 7, 8, 9]
  },
  
  "learning_backward": {
    "use_count": 12,
    "satisfaction_rate": 0.75,
    "trend": "stable"
  }
}
```

### **ContextStack**
```python
{
  "id": "ctx_python_fastapi_project",
  "name": "Python FastAPI Project",
  "scope": "project",             # base | project | conversation
  "stack_level": 1,
  "active": true,
  
  "preferences": {
    "communication.output_format": {
      "value": "table",
      "confidence": 0.88,
      "source": "learned_association"
    },
    "coding.language": {
      "value": "Python",
      "confidence": 0.98,
      "source": "auto_detected"
    }
  }
}
```

### **Signal (Behavioral Learning)**
```python
{
  "id": "sig_001",
  "timestamp": "2025-03-27T14:32:00Z",
  "type": "correction",           # correction | feedback | usage
  
  "task": "api_response_design",
  "context_tags": ["FastAPI", "data_structure"],
  
  # For corrections
  "agent_proposed": "communication.output_format.bullets",
  "user_corrected_to": "communication.output_format.table",
  
  "emotional_tone": "satisfied",  # satisfied | frustrated | neutral
  "emotional_indicators": ["Yes, exactly!", "Perfect format"],
  
  "associations_affected": [
    {
      "assoc_id": "assoc_bullets_datastructure",
      "action": "decrement",
      "impact": -0.02
    }
  ],
  
  "preferences_affected": [
    {
      "pref_id": "comm_format_bullets",
      "action": "decrement_confidence"
    }
  ]
}
```

---

## 🔄 Core Algorithms

### **Algorithm 1: Load Preferences (Option C - Diminishing Confidence)**

```
1. Stack contexts (base → project → conversation)
   - Merge preferences with later overrides
   
2. Identify primary preference
   - Infer from context tags or explicit specification
   
3. Follow association chains
   - Start with primary (confidence = 1.0)
   - For each association, get directional strength
   - Calculate next_confidence = current_confidence × direction_strength
   - Stop if confidence < 0.45 or depth >= 3
   
4. Sort associated preferences by confidence
   
5. Return structured preference context to agent
```

### **Algorithm 2: Process Correction (Key Learning Signal)**

```
1. Detect emotional tone from user message
   - Extract sentiment indicators
   - Map to emotional_tone (satisfied/frustrated/neutral)

2. Update associations
   - Find associations with agent_proposed preference
   - Decrement use_count, satisfaction_rate
   - Recalculate strength_forward/backward
   
   - Find associations with user_corrected_to preference
   - Increment use_count, satisfaction_rate
   - Recalculate strength

3. Update preference confidences
   - Decrement agent_proposed confidence
   - Increment user_corrected_to confidence

4. Save signal to signals.jsonl
   - Records event for historical analysis
```

### **Algorithm 3: Calculate Association Strength**

```
strength = frequency_score × trend_multiplier × emotion_multiplier × recency_multiplier

Where:
  frequency_score = min(use_count / 50, 1.0)
  
  trend_multiplier = {
    strongly_increasing: 1.15,
    increasing: 1.05,
    stable: 1.0,
    decreasing: 0.85,
    strongly_decreasing: 0.7
  }
  
  emotion_multiplier = 0.5 + (satisfaction_rate × 0.5)  # Range 0.5 to 1.0
  
  recency_multiplier = 0.98 ^ days_unused              # 2% decay per day
  
Final strength = min(combined, 1.0)
```

---

## 🔌 Integration Points

### **For Agents (Claude Code, Codeium, etc.)**

```python
from scripts.agent_hook import AgentPreferenceHook

hook = AgentPreferenceHook()

# 1. Get preferences for context
prefs_json = hook.get_preferences_for_context(
    context_tags=["python", "api_design"],
    stack_contexts=["base", "project"]
)

# Parse and use in response generation
prefs = json.loads(prefs_json)
if prefs["primary_preference"]["path"].endswith("bullets"):
    # Use bullet points
elif prefs["primary_preference"]["path"].endswith("table"):
    # Use table format

# 2. Report correction
hook.report_correction(
    task="api_design",
    context_tags=["python"],
    agent_proposed="communication.output_format.bullets",
    user_corrected_to="communication.output_format.table",
    user_message="Perfect, that's what I needed!"
)

# 3. Report feedback
hook.report_feedback(
    task="api_design",
    context_tags=["python"],
    preferences_used=["communication.output_format.table", "coding.data_structure"],
    user_response="Yes, that's exactly right!",
    satisfaction_level=0.95
)
```

### **For CLI Users**

```bash
# Create a preference
adaptive-cli pref create \
  --name bullets \
  --path communication.output_format.bullets \
  --type variant \
  --parent comm_format

# Create an association
adaptive-cli assoc create \
  --from-id communication.output_format.table \
  --to-id coding.data_structure_clarity \
  --strength-forward 0.95 \
  --strength-backward 0.70

# Record a correction
adaptive-cli signal correction \
  --task api_design \
  --context python fastapi \
  --proposed communication.output_format.bullets \
  --corrected communication.output_format.table \
  --message "Perfect, that's what I needed!"

# Load preferences for context
adaptive-cli load --context python api_design

# Generate agent context JSON
adaptive-cli agent-context --context python fastapi --output context.json
```

---

## 🧠 Learning Examples

### **Example 1: Preference Strengthening**

```
Week 1: User chooses bullets 3 times
  strength = min(3/50, 1.0) × 1.0 × 0.7 × 1.0 = 0.06

Week 4: User chooses bullets 30 times total
  strength = min(30/50, 1.0) × 1.05 × 0.85 × 1.0 = 0.76

Week 8: User chooses bullets 85 times, "increasing" trend
  strength = min(85/50, 1.0) × 1.15 × 0.89 × 1.0 = 1.0 (capped)

System learns: bullets is a strong user preference
```

### **Example 2: Association Discovery**

```
Session 1:
  User corrects: "Actually use tables instead"
  system.bullets → system.datastructure (strength: 0.1)
  system.table → system.datastructure (strength: 0.9, NEW)

Session 5:
  User corrects again with satisfaction: "Perfect table format!"
  system.table → system.datastructure (strength: 0.95, growing)
  Association learned and confident

System now knows: tables + data_structure = strong match
When discussing data_structure, table format is suggested
```

### **Example 3: Context-Dependent Preferences**

```
Base context:
  communication.output_format = "bullets" (confidence: 0.85)

Python project context:
  communication.output_format = "table" (overrides base)
  confidence: 0.90

Specific API design conversation:
  communication.output_format = "numbered_steps" (overrides both)
  confidence: 0.75

When loading preferences:
  - Base: bullets (0.85)
  - Python project active: table (0.90)
  - Conversation active: numbered_steps (0.75)
  
Final: numbered_steps used (highest level wins)
```

---

## 📈 Strength Decay & Maintenance

### **Time Decay**
```
Each preference/association has decay_factor = 0.98

Days unused → strength multiplier:
  0 days: 1.0
  7 days: 0.98^7 ≈ 0.87
  14 days: 0.98^14 ≈ 0.76
  30 days: 0.98^30 ≈ 0.55
  90 days: 0.98^90 ≈ 0.10
```

### **Recalculation**
```
Automated maintenance tasks:

adaptive-cli recalculate     # Recalculate all strengths
adaptive-cli decay           # Apply time decay
adaptive-cli stats           # Show storage statistics
```

---

## ✅ Phase 1 Completeness Checklist

- ✅ **Data Models**: Preference, Association, ContextStack, Signal
- ✅ **Storage**: JSONL-based storage with filtering/querying
- ✅ **Preference Loader**: Option C (diminishing confidence, chain following)
- ✅ **Association System**: Bidirectional with asymmetrical strength
- ✅ **Signal Processor**: Corrections and feedback learning
- ✅ **Context Stacking**: Base/project/conversation level merging
- ✅ **Agent Hook**: Integration for AI agents
- ✅ **CLI Interface**: Full command-line control
- ✅ **Strength Calculation**: Frequency × trend × emotion × recency
- ✅ **Time Decay**: Daily decay factor application
- ✅ **Emotional Signal Detection**: Tone extraction from user messages

---

## 🚀 Next Steps (Phase 2+)

- [ ] Auto-detection of new preference categories
- [ ] Machine learning for trend analysis
- [ ] Web dashboard for visualization
- [ ] IDE plugin integration (VS Code, JetBrains)
- [ ] Team/collaborative preferences
- [ ] Preference versioning and rollback
- [ ] Advanced analytics and reporting
- [ ] Agentic loops (preferences that automate workflows)

---

## 📚 File Reference

| File | Purpose |
|------|---------|
| `models.py` | Core data models (Preference, Association, etc.) |
| `storage.py` | JSONL file management and queries |
| `preference_loader.py` | Load preferences with association chains |
| `signal_processor.py` | Process corrections/feedback, update strengths |
| `cli.py` | Command-line interface |
| `agent_hook.py` | Integration point for agents |

---

## 🎓 Usage Walkthrough

### Scenario: Python API Development

**Step 1: Create base preferences**
```bash
adaptive-cli pref create \
  --name bullets \
  --path communication.output_format.bullets \
  --type variant \
  --value active

adaptive-cli pref create \
  --name python \
  --path coding.language.python \
  --type variant \
  --value active
```

**Step 2: Create association**
```bash
adaptive-cli assoc create \
  --from-id communication.output_format.table \
  --to-id coding.data_structure_clarity \
  --strength-forward 0.90 \
  --strength-backward 0.60 \
  --description "Tables help explain data structures"
```

**Step 3: Create project context**
```bash
adaptive-cli context create \
  --name "Python FastAPI Project" \
  --scope project

adaptive-cli context set-pref <ctx_id> coding.language python 0.98
adaptive-cli context set-pref <ctx_id> communication.output_format table 0.88
```

**Step 4: Agent uses preferences**
```python
hook = AgentPreferenceHook()
prefs = hook.get_preferences_for_context(
    context_tags=["python", "fastapi", "api_design"],
    stack_contexts=["base", "project"]
)
# Agent reads preferences and tailors response
```

**Step 5: User corrects if needed**
```bash
adaptive-cli signal correction \
  --task "api_response_format" \
  --context python fastapi \
  --proposed communication.output_format.bullets \
  --corrected communication.output_format.table \
  --message "Yes, the table format is perfect!"
```

System learns: In FastAPI projects, tables are preferred for data structures.

---

This is **Phase 1 complete** - a solid foundation for behavior-driven preference learning that can evolve into agentic automation in Phase 2+.
