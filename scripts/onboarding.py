"""
onboarding.py - First-time user onboarding for Adaptive Preference Engine
Addresses Lisa Thompson (Product/UX SME) feedback: System invisibility
Creates ~2-minute interactive tutorial for new users
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import Preference, Association, Signal, generate_id
from scripts.storage import PreferenceStorageManager
from scripts.signal_processor import SignalProcessor
from scripts.user_feedback_system import UserFeedbackSystem
from scripts.preference_templates import PreferenceTemplateManager


class OnboardingState:
    """Tracks onboarding progress for partial completion support"""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state = self._load_state()

    def _load_state(self) -> Dict:
        """Load state from disk or create new"""
        if self.state_file.exists():
            with open(self.state_file) as f:
                return json.load(f)
        return {
            "current_step": 0,
            "started_at": datetime.now().isoformat(),
            "completed": False,
            "demo_preference_id": None,
            "demo_signal_id": None
        }

    def _save_state(self):
        """Persist state to disk"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w') as f:
            json.dump(self.state, f, indent=2)

    def get_current_step(self) -> int:
        """Get current step (0-7)"""
        return self.state.get("current_step", 0)

    def advance_step(self) -> int:
        """Move to next step"""
        self.state["current_step"] = min(self.state["current_step"] + 1, 7)
        self._save_state()
        return self.state["current_step"]

    def set_demo_preference(self, pref_id: str):
        """Store demo preference ID for later reference"""
        self.state["demo_preference_id"] = pref_id
        self._save_state()

    def set_demo_signal(self, signal_id: str):
        """Store demo signal ID for later reference"""
        self.state["demo_signal_id"] = signal_id
        self._save_state()

    def mark_complete(self):
        """Mark onboarding as complete"""
        self.state["completed"] = True
        self.state["completed_at"] = datetime.now().isoformat()
        self._save_state()

    def is_complete(self) -> bool:
        """Check if onboarding finished"""
        return self.state.get("completed", False)


class OnboardingSystem:
    """Interactive onboarding tutorial for new users"""

    STEPS = [
        {
            "number": 1,
            "title": "Welcome to Adaptive Preference Engine",
            "duration": "~30 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║          Welcome to Adaptive Preference Engine!                ║
╚════════════════════════════════════════════════════════════════╝

This system learns YOUR preferences over time.

What does that mean?
  • Tell it what you like → it remembers
  • Correct it when wrong → it adapts
  • Use it in context → it suggests smarter
  • Over weeks → it becomes expert-level

How fast does it work?
  • ~3 corrections: System starts to notice patterns
  • ~7 corrections: Patterns solidify
  • ~15 corrections: Preference becomes "locked in"
  • ~25+ corrections: System knows your preference better than you

Real example:
  • You prefer "bullet points" in communication outputs
  • System suggests bullets the next time automatically
  • You correct it → it learns exceptions
  • Soon it knows: "bullets in updates, tables in specs"

Next: Let's create your first preference!
            """
        },
        {
            "number": 2,
            "title": "Create Your First Preference",
            "duration": "~20 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║              Step 2: Create First Preference                  ║
╚════════════════════════════════════════════════════════════════╝

A preference is something you like (a setting, style, format, etc.)

Examples of preferences:
  • Output format: "bullets", "tables", "paragraphs"
  • Code style: "type hints", "docstrings", "comments"
  • Tone: "formal", "casual", "technical"
  • Structure: "outline first", "examples first", "summary last"

Quick start: Choose a user profile that matches you:
  1. DEVELOPER - Code blocks, technical depth, API tables
  2. ANALYST   - Data tables, CSV, detailed breakdowns
  3. WRITER    - Prose, long-form, emotional depth
  4. EXECUTIVE - Bullet summaries, brevity, high-level
  5. LEARNER   - Step-by-step, examples, gentle tone

Or skip to create a custom preference.

For this demo, we'll create:
  Name: output_format
  Path: communication.output_format.bullets
  Type: variant (choose between options)
  Value: bullets

This means: "I prefer bullet points in communication"

The system will track when you use this and strengthen it.
            """
        },
        {
            "number": 3,
            "title": "Record Your First Correction",
            "duration": "~20 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║           Step 3: Record Your First Correction                ║
╚════════════════════════════════════════════════════════════════╝

Corrections are how the system learns.

Example workflow:
  1. System suggests: "I'll use paragraphs for this"
  2. You correct it: "Actually, give me bullets!"
  3. System records: "This person wanted bullets, not paragraphs"
  4. Next time (in similar context): Suggests bullets first

Each correction:
  • Strengthens the preference
  • Builds associations (e.g., "bullets work great for APIs")
  • Increases confidence
  • Tracks emotional tone (happy/frustrated/neutral)

For this demo, we'll simulate:
  "I prefer bullets over tables for this task"
  Emotional tone: happy (satisfied with the correction)

This single correction starts the learning process!
            """
        },
        {
            "number": 4,
            "title": "See What the System Learned",
            "duration": "~15 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║             Step 4: System Learning Display                   ║
╚════════════════════════════════════════════════════════════════╝

After each correction, the system shows what it learned:

Example output:
  ✓ Got it! I'll remember this.

  You corrected me: tables → bullets

  I'm building a memory of this preference.
  Each correction strengthens it.

Notice:
  • Confidence: 50% → This preference is emerging
  • Use count: 1 → You've corrected once
  • Trend: stable → Not enough data yet
  • Satisfaction: happy → You seemed pleased

After 3+ corrections, you'll see:
  🎯 EMERGING PREFERENCE: bullets format is taking shape
  After 7: Pattern confirmed!
  After 15: LOCKED IN
  After 25: Expert-level knowledge

The system is actively remembering!
            """
        },
        {
            "number": 5,
            "title": "Explore the Control Panel",
            "duration": "~20 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║              Step 5: User Control Panel                        ║
╚════════════════════════════════════════════════════════════════╝

You're always in control. View your learned preferences anytime:

Command: adaptive-cli pref list
Output:
  📊 Preferences (3 total)
  ──────────────────────────────────────────────────────────
  ✓ communication.output_format.bullets
    Value: bullets | Confidence: 82% | Uses: 7

  ○ coding.style.type_hints
    Value: true | Confidence: 45% | Uses: 2

Symbols mean:
  ✓ = Locked in (confidence > 70%)
  ○ = Emerging (confidence < 70%)

You can also:
  • See detailed preference: adaptive-cli pref show PREF_ID
  • View associations: adaptive-cli assoc show PREF_ID
  • Reset any preference: adaptive-cli pref delete ID

You're never forced to follow suggestions. You always override.
            """
        },
        {
            "number": 6,
            "title": "Agent Integration Explained",
            "duration": "~15 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║             Step 6: How Agents Use Your Preferences           ║
╚════════════════════════════════════════════════════════════════╝

The system integrates with your AI agents/assistants.

What happens:
  1. Agent loads your preferences automatically
  2. Agent uses them to personalize responses
  3. Agent notes when you correct it
  4. Each correction → system gets smarter
  5. Next similar task → better suggestions

Example:
  Task: "Write API documentation"
  Agent loads: {output_format: bullets, tone: technical}
  Agent suggests: Documentation in bullet points
  You approve → "Great!" (implicit feedback)
  Next API doc → Agent remembers this worked

No manual work needed:
  • Automatic learning from your corrections
  • Automatic loading in agent context
  • Automatic confidence updates
  • Just use the system normally!

Your preferences make agents dramatically better.
            """
        },
        {
            "number": 7,
            "title": "Quick Reference Card",
            "duration": "~10 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║              Quick Reference: Top Commands                     ║
╚════════════════════════════════════════════════════════════════╝

MOST USEFUL COMMANDS:

View your learning progress:
  $ adaptive-cli pref list                    # All preferences
  $ adaptive-cli pref show PREF_ID            # Single preference

Record what you learned:
  $ adaptive-cli signal correction \\
      --task api_design \\
      --proposed bullets --corrected tables

Check your preferences for a context:
  $ adaptive-cli load --context python coding

Generate agent context (for your AI):
  $ adaptive-cli agent-context --context python

View learning digest:
  $ adaptive-cli digest weekly              # This week's learning

Advanced:
  $ adaptive-cli recalculate                 # Refresh strength scores
  $ adaptive-cli consolidate daily           # Run daily learning cycle

CHEAT SHEET: "How to..." topics:
  • Add new preference: pref create --name X --path Y --type Z
  • Delete preference: pref delete ID
  • Create association: assoc create --from A --to B
  • Record feedback: signal feedback --task X --preferences A B
  • See all your control options: pref show ID

Next time you get recommendations, you'll see them come from
your learned preferences!
            """
        },
        {
            "number": 8,
            "title": "Setup Complete!",
            "duration": "~10 seconds",
            "content": """
╔════════════════════════════════════════════════════════════════╗
║              Onboarding Complete! You're Ready!               ║
╚════════════════════════════════════════════════════════════════╝

Summary of what you just set up:

✓ Created demo preference: output_format
✓ Recorded first correction: bullets preference
✓ Learned how system learns from corrections
✓ Explored control panel options
✓ Understood agent integration
✓ Got quick reference card

NEXT STEPS:

1. Use the system normally
   • Make requests to AI agents
   • Correct them when you want different output
   • Watch the system adapt

2. Check your progress weekly
   $ adaptive-cli digest weekly

3. Solidify preferences
   • ~3 corrections = emerging pattern
   • ~7 corrections = pattern confirmed
   • ~15 corrections = locked in!

REMEMBER:
  • Every correction makes the system smarter
  • You're always in control (override anytime)
  • Preferences work best in contexts (communication vs coding)
  • The system learns automatically - no work needed!

Questions?
  $ adaptive-cli --help
  $ adaptive-cli pref list --help

Happy learning! The system will improve with every interaction. 🚀
            """
        }
    ]

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = str(Path.home() / ".adaptive-cli")

        self.base_dir = Path(base_dir)
        self.state_file = self.base_dir / "onboarding_state.json"
        self.complete_file = self.base_dir / "onboarding_complete"

        self.storage = PreferenceStorageManager(str(self.base_dir))
        self.processor = SignalProcessor(self.storage)
        self.feedback_system = UserFeedbackSystem(self.storage)
        self.state = OnboardingState(self.state_file)

    def is_first_run(self) -> bool:
        """Check if user has completed onboarding"""
        return not self.complete_file.exists()

    def mark_complete(self):
        """Mark onboarding as complete"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.complete_file.touch()
        self.state.mark_complete()

    def run_tutorial(self, skip_demo: bool = False) -> None:
        """Run full interactive tutorial"""

        self.base_dir.mkdir(parents=True, exist_ok=True)

        print("\n" + "=" * 70)
        print("ADAPTIVE PREFERENCE ENGINE - ONBOARDING TUTORIAL")
        print("=" * 70)
        print("\nPress Enter to advance through each step.")
        print("Type 'end' to skip remaining steps.")
        print("Type 'back' to go to the previous step.\n")

        while self.state.get_current_step() < len(self.STEPS):
            step_idx = self.state.get_current_step()
            step = self.STEPS[step_idx]

            print(f"\n[Step {step['number']}/{len(self.STEPS)}] {step['title']}")
            print(f"Duration: {step['duration']}\n")
            print(step["content"])

            # Step 2: Create demo preference or apply selected template
            if step_idx == 1 and not skip_demo:
                print("\n" + "─" * 70)
                self._display_template_options()
                print("\n" + "─" * 70)

                template_manager = PreferenceTemplateManager()
                templates = template_manager.list_templates()
                keys = [t['key'] for t in templates]

                choice = input(
                    f"Choose a profile ({'/'.join(keys)}) or press Enter for the demo: "
                ).strip().upper()

                if choice in keys:
                    print(f"\nApplying {choice} template...")
                    count = template_manager.apply_template(choice, self.storage)
                    print(f"✓ Applied {choice} template ({count} preferences created)")
                    # Store first pref as demo pref for state tracking
                    all_prefs = self.storage.preferences.get_all_preferences()
                    if all_prefs:
                        self.state.set_demo_preference(all_prefs[0].id)
                else:
                    print("\nACTION: Creating demo preference...")
                    demo_pref_id = self._create_demo_preference()
                    self.state.set_demo_preference(demo_pref_id)
                    print(f"✓ Created: {demo_pref_id}")

            # Step 3: Record demo correction
            if step_idx == 2 and not skip_demo:
                print("\n" + "─" * 70)
                print("ACTION: Recording demo correction signal...")
                demo_signal_id = self._record_demo_correction()
                self.state.set_demo_signal(demo_signal_id)
                print(f"✓ Recorded: {demo_signal_id}")

            # Step 4: Display feedback
            if step_idx == 3 and not skip_demo:
                print("\n" + "─" * 70)
                print("SYSTEM FEEDBACK:")
                feedback = self.feedback_system.feedback_correction_accepted(
                    "tables", "bullets", "communication"
                )
                print(self.feedback_system.display_feedback(feedback))

            # Step 5: Show control panel
            if step_idx == 4 and not skip_demo:
                print("\n" + "─" * 70)
                print("CONTROL PANEL OUTPUT:")
                self._display_demo_control_panel()

            # Wait for user input
            user_input = input("\n> Press Enter to continue ('back' = previous step, 'end' = skip to finish): ").strip().lower()

            if user_input == "end":
                print("\n⏭️  Skipping to end of tutorial...")
                self.state.state["current_step"] = len(self.STEPS) - 1
                self.state._save_state()
            elif user_input == "back" and step_idx > 0:
                self.state.state["current_step"] = step_idx - 1
                self.state._save_state()
                print("\n⬅️  Going back to previous step...")
            else:
                self.state.advance_step()

        self.mark_complete()
        print("\n✅ Onboarding complete! Welcome to the Adaptive Preference Engine!")
        print("   Type 'adaptive-cli pref list' to see your learned preferences.\n")

    def _create_demo_preference(self) -> str:
        """Create demo preference for tutorial"""
        pref = Preference(
            id=generate_id("pref"),
            path="communication.output_format.bullets",
            parent_id=None,
            name="bullets",
            type="variant",
            value="bullets",
            confidence=0.5,
            description="Prefer bullet points for communication outputs",
            auto_detected=False
        )
        self.storage.preferences.save_preference(pref)
        return pref.id

    def _record_demo_correction(self) -> str:
        """Record demo correction signal"""
        signal = self.processor.process_correction(
            task="tutorial_demo",
            context_tags=["communication", "tutorial"],
            agent_proposed="tables",
            user_corrected_to="bullets",
            user_message="I prefer bullet points for this!"
        )
        return signal.id

    def _display_template_options(self) -> None:
        """Display available preference templates"""
        template_manager = PreferenceTemplateManager()
        templates = template_manager.list_templates()

        output = """
╔════════════════════════════════════════════════════════════════╗
║              AVAILABLE PREFERENCE TEMPLATES                    ║
╚════════════════════════════════════════════════════════════════╝

"""
        for template in templates:
            output += f"  {template['key']:10s} - {template['name']:10s}\n"
            output += f"    {template['description']}\n"
            output += f"    ({template['preference_count']} preferences)\n\n"

        output += "You can apply any of these templates to get started,\nor create a custom preference from scratch.\n"
        print(output)

    def _display_demo_control_panel(self) -> None:
        """Show example control panel output"""
        output = """
╔════════════════════════════════════════════════════════════════╗
║               YOUR LEARNED PREFERENCES                         ║
║                                                                ║
║  Total preferences learned: 1
╚════════════════════════════════════════════════════════════════╝

📁 COMMUNICATION
────────────────────────────────────────────────────────────────
  output_format:
    ✓ communication.output_format.bullets
      Value: bullets | Confidence: 50% | Uses: 1
      "I prefer bullet points in communication outputs"

Press 'adaptive-cli pref list' to see live version!
        """
        print(output.strip())

    def generate_weekly_digest(self) -> str:
        """Generate weekly progress digest with colors"""
        prefs = self.storage.preferences.get_all_preferences()
        signals = self.storage.signals.get_recent_signals(hours=168)

        corrections_this_week = sum(
            1 for s in signals
            if isinstance(s, Signal) and s.type == "correction"
        )
        positive_feedback = sum(
            1 for s in signals
            if isinstance(s, Signal) and s.emotional_tone in ["satisfied", "happy"]
        )

        # Sort by confidence
        high_conf = [p for p in prefs if p.confidence >= 0.7]
        emerging = [p for p in prefs if p.confidence < 0.7]

        from scripts.cli_utils import CYAN, GREEN, YELLOW, BOLD, RESET, term_width

        w = min(term_width(), 66)
        date_str = datetime.now().strftime('%Y-%m-%d')
        box_top    = "╔" + "═" * (w - 2) + "╗"
        box_title  = f"║{'WEEKLY LEARNING DIGEST':^{w-2}}║"
        box_date   = f"║{date_str:^{w-2}}║"
        box_bottom = "╚" + "═" * (w - 2) + "╝"

        digest = f"""
{CYAN}{box_top}
{box_title}
{box_date}
{box_bottom}{RESET}

{BOLD}THIS WEEK'S ACTIVITY:{RESET}
  Corrections made: {corrections_this_week}
  Positive feedback: {positive_feedback}
  Total preferences: {len(prefs)}

{BOLD}{GREEN}LOCKED IN (Confidence ≥ 70%):{RESET}
"""

        if high_conf:
            for pref in sorted(high_conf, key=lambda p: p.confidence, reverse=True)[:5]:
                pct = int(pref.confidence * 100)
                uses = pref.learning.use_count if pref.learning else 0
                digest += f"  ✓ {pref.name:30s} {pct:3d}%  ({uses} uses)\n"
        else:
            digest += "  (none yet - keep correcting!)\n"

        digest += f"\n{YELLOW}{BOLD}EMERGING (Confidence < 70%):{RESET}\n"
        if emerging:
            for pref in sorted(emerging, key=lambda p: p.confidence, reverse=True)[:5]:
                pct = int(pref.confidence * 100)
                uses = pref.learning.use_count if pref.learning else 0
                digest += f"  ○ {pref.name:30s} {pct:3d}%  ({uses} uses)\n"
        else:
            digest += "  (none - you're on a roll!)\n"

        digest += f"""
{BOLD}INSIGHTS:{RESET}
  • Keep correcting - patterns solidify at 7+ corrections
  • Check 'adaptive-cli pref show ID' for detailed view
  • Use 'adaptive-cli load --context X Y' to load preferences

Keep up the good work! 🚀
"""

        return digest


def check_first_run_and_onboard(base_dir: str = None, skip_onboarding: bool = False) -> bool:
    """
    Check if first run, optionally trigger onboarding.
    Call this at CLI startup.

    Returns: True if onboarding was triggered, False otherwise
    """
    onboarding = OnboardingSystem(base_dir)

    if onboarding.is_first_run() and not skip_onboarding:
        print("\n🎯 Welcome! Let's set up your Adaptive Preference Engine in ~2 minutes...\n")
        onboarding.run_tutorial()
        return True

    return False
