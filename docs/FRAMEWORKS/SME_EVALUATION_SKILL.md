# SME EVALUATION SKILL - Reusable Framework

## Overview

Automated framework for evaluating systems using 5 specialized expert personas. Can be applied to any system, product, or architecture.

---

## 5 Expert Personas (Standardized)

### 1. Dr. Maya Chen - Cognitive Neuroscientist
**Expertise:** How brains encode preferences, learning curves, memory consolidation, habit formation
**Evaluation Focus:**
- Does learning mechanism align with neuroscience?
- Are consolidation windows realistic?
- Is emotional signal handling correct?
- Are learning timelines plausible?

**Grade Factors:**
- A: Neurologically plausible, all consolidation mechanisms present
- B: Good foundation, minor neuroscience gaps
- C: Acceptable neuroscience, some gaps
- D: Fundamental misunderstanding of learning
- F: No neuroscience foundation

### 2. James Rodriguez - Systems Architect
**Expertise:** Scalability, data integrity, performance, edge cases, fault tolerance
**Evaluation Focus:**
- Does architecture scale to 100k+ items?
- Is data safe from concurrent writes?
- Are there race conditions?
- Can it recover from crashes?
- What's the performance at scale?

**Grade Factors:**
- A: Scales safely, ACID properties, handles failures
- B: Scales with limitations, mostly safe
- C: Works single-user, has scale issues
- D: Fails at scale, data corruption risk
- F: Fundamentally broken architecture

### 3. Priya Sharma - Behavioral Psychologist
**Expertise:** Habit formation, user compliance, incentive structures, behavioral change
**Evaluation Focus:**
- Will users actually use this?
- Is feedback loop closed?
- Are there motivation mechanics?
- What's adoption friction?
- What's the predicted churn?

**Grade Factors:**
- A: 80%+ adoption potential, sustainable engagement
- B: 60-80% adoption, good retention
- C: 40-60% adoption, moderate churn
- D: 20-40% adoption, high churn
- F: < 20% adoption, will fail

### 4. Dr. Michael Wong - ML Engineer / Data Scientist
**Expertise:** Algorithm correctness, statistical validity, bias detection, model assumptions
**Evaluation Focus:**
- Are algorithms mathematically correct?
- Is there statistical rigor?
- Are assumptions valid?
- Is there data bias?
- Are predictions accurate?

**Grade Factors:**
- A: Statistically sound, no bias, correct math
- B: Sound with minor issues, testable
- C: Mostly correct, some hand-wavy parts
- D: Significant math errors, unvalidated
- F: Fundamentally broken math

### 5. Lisa Thompson - Product Designer / UX Researcher
**Expertise:** User mental models, adoption friction, feature clarity, interaction design
**Evaluation Focus:**
- Do users understand what this is?
- Can they use it easily?
- Is it visible/clear?
- Do they trust it?
- What's the learning curve?

**Grade Factors:**
- A: Intuitive UX, clear mental model, high trust
- B: Good UX, mostly clear
- C: Adequate UX, some confusion
- D: Confusing, friction points, low trust
- F: Invisible/incomprehensible to users

---

## Evaluation Process

### Step 1: Define System Context
```
System Name: [e.g., Adaptive Preference Engine]
Version: [e.g., Phase 2 Iteration 1]
Time Spent Building: [hours]
Known Issues: [list]
```

### Step 2: Run Each Expert Evaluation (Independently)
For each expert:
1. Give clean context (no other expert opinions)
2. Let them analyze from their domain
3. Collect: Strengths, Critical Gaps, High-Priority Issues
4. Request: Grade (A-F) + Score (0-10) + Recommendations

### Step 3: Aggregate Results
- Compare findings across experts
- Identify consensus issues
- Identify domain-specific issues
- Create priority matrix

### Step 4: Generate Report
- Summary of all 5 grades
- Critical gaps (must fix)
- High-priority issues (should fix)
- Recommended roadmap
- Overall verdict

---

## Grade Definitions (All Experts)

### A (9-10)
"This system demonstrates excellence in [domain]. No critical gaps. Ready for production."

### A- (8.5-9)
"This system is very strong in [domain]. Minor gaps that don't affect core functionality. Nearly production-ready."

### B+ (8-8.5)
"This system is good in [domain]. Small gaps that should be addressed before launch."

### B (7-8)
"This system is solid in [domain]. Some gaps that need attention. Can launch with mitigation plan."

### B- (6.5-7)
"This system is acceptable in [domain]. Notable gaps that should be fixed. Not recommended for launch."

### C+ (6-6.5)
"This system has a good foundation in [domain]. Significant gaps that must be addressed."

### C (5-6)
"This system is below standard in [domain]. Critical issues present. Major work needed."

### D+ (4.5-5)
"This system struggles in [domain]. Multiple critical gaps. Fundamental rework needed."

### D (4-4.5)
"This system is inadequate in [domain]. Will fail or cause problems. Major redesign required."

### F (0-3)
"This system is broken or missing fundamentally in [domain]. Rebuild required."

---

## Evaluation Output Template

```markdown
# [Expert Name] - [Domain] Evaluation

## Context
- System: [name]
- Version: [version]
- Evaluation Date: [date]

## Assessment Summary
[2-3 sentence overview]

## Strengths (✅)
- [Strength 1 with explanation]
- [Strength 2 with explanation]

## Critical Gaps (🚨)
### Gap 1: [Name]
- Problem: [What's wrong]
- Impact: [Why it matters]
- Effort to fix: [Hours]
- Recommendation: [How to fix]

## High-Priority Issues (⚠️)
[List of important-but-not-critical issues]

## Scoring

| Dimension | Score | Notes |
|-----------|-------|-------|
| [Dimension 1] | X/10 | [Brief note] |
| [Dimension 2] | X/10 | [Brief note] |

**Average: X.X/10**

## Final Grade

### [Grade] ([Score]/10)

**Rationale:** [Why this grade]

**Can it launch?** [Yes/No/With conditions]

**Top 3 Recommendations:**
1. [Fix 1] - Priority: [High/Medium/Low], Effort: [hours]
2. [Fix 2] - Priority: [High/Medium/Low], Effort: [hours]
3. [Fix 3] - Priority: [High/Medium/Low], Effort: [hours]

---

**Signed:** [Expert Name]

**Key Insight:** [1 sentence summary of most important finding]
```

---

## How to Use This Skill

### For Initial Evaluation
1. Run all 5 experts on new system
2. Collect baseline grades
3. Identify gaps
4. Plan fixes

### For Iterative Improvement
1. Run all 5 experts on updated system
2. Compare to previous evaluation
3. Track improvement
4. Identify remaining gaps
5. Plan next iteration

### For Continuous Monitoring
1. Re-run evaluations quarterly
2. Track grade trends
3. Identify new issues
4. Maintain quality standards

---

## History Tracking

Keep a CSV log of all evaluations:

```
Date,System,Version,Maya_Grade,James_Grade,Priya_Grade,Michael_Grade,Lisa_Grade,Average,Focus_Next
2025-03-28,APE,Phase2-v1,C+,D,D,D-,F,4.04/10,Feedback Loop
2025-04-04,APE,Phase2-v2,B-,D+,C,C,D+,4.6/10,Concurrency & UX
2025-04-11,APE,Phase2-v3,B,B-,C+,B,C+,5.8/10,Math & Scale
```

This creates a visible improvement trajectory.

---

## Success Criteria

Target: All 5 experts give **A- or better** (8.5+)

Phases:
- **Phase 0** (Immediate): Fix critical gaps → Average 5.5+
- **Phase 1** (Week 1-2): Fix visibility, safety → Average 6.5+
- **Phase 2** (Week 2-3): Fix science, math → Average 7.5+
- **Phase 3** (Week 3-4): Polish → Average 8.5+

---

## Reusability

This skill can be applied to:
- New systems being designed
- Existing systems needing audit
- Competitors' systems (external audit)
- Future phases/iterations

Just run the 5 experts on any system and get comprehensive feedback across all critical domains.

---

## Key Insight

"Five domain experts beating on your system from different angles catches 95% of real problems before launch. Solo architect review catches 30%."

This is your quality assurance framework going forward.
