"""
onboarding.py - First-time user onboarding for Adaptive Preference Engine
Addresses Lisa Thompson (Product/UX SME) feedback: System invisibility
Creates ~2-minute interactive tutorial for new users
"""

from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import json

from scripts.models import Preference, Association, Signal, generate_id
from scripts.paths import get_base_dir
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
        defaults = {
            "current_step": 0,
            "started_at": datetime.now().isoformat(),
            "completed": False,
            "starter_profile": None,
            "demo_preference_id": None,
            "demo_signal_id": None,
            "starter_preference_ids": [],
            "demo_preference_ids": [],
            "managed_signal_ids": [],
        }
        if self.state_file.exists():
            with open(self.state_file) as f:
                loaded = json.load(f)
            for key, value in defaults.items():
                loaded.setdefault(key, value if not isinstance(value, list) else list(value))
            if "managed_preference_ids" in loaded:
                legacy_ids = list(loaded.get("managed_preference_ids", []))
                if not loaded.get("starter_preference_ids") and not loaded.get("demo_preference_ids"):
                    loaded["starter_preference_ids"] = legacy_ids
            return loaded
        return defaults

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

    def set_demo_preference(self, pref_id: Optional[str]):
        """Store demo preference ID for later reference"""
        self.state["demo_preference_id"] = pref_id
        self._save_state()

    def set_demo_signal(self, signal_id: Optional[str]):
        """Store demo signal ID for later reference"""
        self.state["demo_signal_id"] = signal_id
        self._save_state()

    def set_starter_profile(self, starter_profile: Optional[str]):
        """Store the selected onboarding starter profile."""
        self.state["starter_profile"] = starter_profile
        self._save_state()

    def get_starter_profile(self) -> Optional[str]:
        """Return the saved onboarding starter profile."""
        return self.state.get("starter_profile")

    def set_starter_preference_ids(self, preference_ids: List[str]):
        """Store starter-profile-managed preference IDs."""
        self.state["starter_preference_ids"] = list(preference_ids)
        self._save_state()

    def get_starter_preference_ids(self) -> List[str]:
        """Return starter-profile-managed preference IDs."""
        return list(self.state.get("starter_preference_ids", []))

    def set_demo_preference_ids(self, preference_ids: List[str]):
        """Store demo-bundle preference IDs."""
        self.state["demo_preference_ids"] = list(preference_ids)
        self._save_state()

    def get_demo_preference_ids(self) -> List[str]:
        """Return demo-bundle preference IDs."""
        return list(self.state.get("demo_preference_ids", []))

    def get_managed_preference_ids(self) -> List[str]:
        """Return all onboarding-managed preference IDs."""
        seen = []
        for pref_id in self.get_starter_preference_ids() + self.get_demo_preference_ids():
            if pref_id not in seen:
                seen.append(pref_id)
        return seen

    def set_managed_signal_ids(self, signal_ids: List[str]):
        """Store onboarding-managed signal IDs."""
        self.state["managed_signal_ids"] = list(signal_ids)
        self._save_state()

    def get_managed_signal_ids(self) -> List[str]:
        """Return onboarding-managed signal IDs."""
        return list(self.state.get("managed_signal_ids", []))

    def mark_complete(self):
        """Mark onboarding as complete"""
        self.state["completed"] = True
        self.state["current_step"] = 8
        self.state["completed_at"] = datetime.now().isoformat()
        self._save_state()

    def is_complete(self) -> bool:
        """Check if onboarding finished"""
        return self.state.get("completed", False)

    def reset(self):
        """Reset onboarding progress while preserving the state file location."""
        self.state = {
            "current_step": 0,
            "started_at": datetime.now().isoformat(),
            "completed": False,
            "starter_profile": None,
            "demo_preference_id": None,
            "demo_signal_id": None,
            "starter_preference_ids": [],
            "demo_preference_ids": [],
            "managed_signal_ids": [],
        }
        self._save_state()


class OnboardingSystem:
    """Interactive onboarding tutorial for new users"""

    DEMO_BUNDLE_PATHS = {
        "communication.output_format",
        "communication.output_format.bullets",
        "communication.output_format.tables",
    }

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
        self.base_dir = get_base_dir(base_dir)
        self.state_file = self.base_dir / "onboarding_state.json"
        self.complete_file = self.base_dir / "onboarding_complete"

        self.storage = PreferenceStorageManager(str(self.base_dir))
        self.processor = SignalProcessor(self.storage)
        self.feedback_system = UserFeedbackSystem(self.storage)
        self.state = OnboardingState(self.state_file)

    def is_first_run(self) -> bool:
        """Check if user has completed onboarding"""
        return not (self.complete_file.exists() or self.state.is_complete())

    def mark_complete(self):
        """Mark onboarding as complete"""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.complete_file.touch()
        self.state.mark_complete()

    def reset_progress(self):
        """Reset onboarding progress and completion marker."""
        self.complete_file.unlink(missing_ok=True)
        self.state.reset()

    def cleanup_managed_setup(self):
        """Remove onboarding-managed preferences and signals only."""
        for signal_id in self.state.get_managed_signal_ids():
            self.storage.delete_signal(signal_id)

        for pref_id in self.state.get_managed_preference_ids():
            self.storage.delete_preference(pref_id)

        self.state.set_managed_signal_ids([])
        self.state.set_starter_preference_ids([])
        self.state.set_demo_preference_ids([])
        self.state.set_demo_signal(None)
        self.state.set_demo_preference(None)
        self.state.set_starter_profile(None)

    def _ensure_demo_bundle(self) -> str:
        """Ensure the demo preference bundle exists and return the bullets preference ID."""
        if self.has_demo_preference():
            return self.state.state["demo_preference_id"]
        for pref_id in self.state.get_demo_preference_ids():
            self.storage.delete_preference(pref_id)
        self.state.set_demo_preference_ids([])
        self.state.set_demo_preference(None)
        return self._create_demo_preference()

    def reset_all_setup(self):
        """Reset onboarding progress and remove onboarding-managed artifacts."""
        self.cleanup_managed_setup()
        self.reset_progress()

    def has_demo_preference(self) -> bool:
        """Return True when the full demo preference bundle already exists."""
        managed_paths = {pref.path for pref in self._get_demo_preferences()}
        return self.DEMO_BUNDLE_PATHS.issubset(managed_paths)

    def has_demo_signal(self) -> bool:
        """Return True when the demo correction signal already exists."""
        demo_signal_id = self.state.state.get("demo_signal_id")
        return bool(demo_signal_id and self.storage.signals.get_signal(demo_signal_id))

    def _confirm_quit(self) -> bool:
        """Confirm early exit from onboarding."""
        response = input("Quit onboarding now? Progress will be saved. (y/N): ").strip().lower()
        return response in {"y", "yes"}

    def _prompt_step_action(self, step_idx: int) -> str:
        """Prompt for the next onboarding action."""
        actions = [
            "[Enter/1] Continue",
            "[b] Back" if step_idx > 0 else None,
            "[s] Skip to finish",
            "[q] Quit",
        ]
        prompt = "  ".join(action for action in actions if action)

        while True:
            user_input = input(f"\n> {prompt}: ").strip().lower()
            if user_input in {"", "1"}:
                return "continue"
            if user_input == "b" and step_idx > 0:
                return "back"
            if user_input == "s":
                return "skip"
            if user_input == "q":
                if self._confirm_quit():
                    return "quit"
                continue
            print("Invalid choice. Use Enter/1 to continue, b to go back, s to skip, or q to quit.")

    def _select_template_choice(self) -> Optional[str]:
        """Prompt for a numbered template selection or demo mode."""
        template_manager = PreferenceTemplateManager()
        templates = template_manager.list_templates()

        print("\nChoose how to start:")
        print("  0. Demo preference only")
        for index, template in enumerate(templates, start=1):
            print(f"  {index}. {template['key']:10s} - {template['name']}")
        print("  q. Quit onboarding")

        while True:
            choice = input("Select an option [0]: ").strip().lower()
            if choice == "":
                return None
            if choice == "q":
                if self._confirm_quit():
                    return "quit"
                continue
            if choice.isdigit():
                selected = int(choice)
                if selected == 0:
                    return None
                if 1 <= selected <= len(templates):
                    return templates[selected - 1]["key"]
            print("Invalid choice. Enter 0 for the demo, a numbered template, or q to quit.")

    def _apply_starter_choice(self, template_key: Optional[str]) -> None:
        """Apply a starter profile or demo-only setup and track created IDs."""
        if template_key:
            template_manager = PreferenceTemplateManager()
            print(f"\nApplying {template_key} template...")
            created_ids = template_manager.apply_template(template_key, self.storage)
            print(f"✓ Applied {template_key} template ({len(created_ids)} preferences created)")
            self.state.set_starter_profile(template_key)
            self.state.set_starter_preference_ids(created_ids)
            return

        print("\nACTION: Creating demo preference...")
        demo_pref_id = self._ensure_demo_bundle()
        self.state.set_starter_profile("DEMO")
        print(f"✓ Created: {demo_pref_id}")

    def _record_and_track_demo_signal(self) -> str:
        """Record the demo correction and mark it as onboarding-managed."""
        demo_signal_id = self._record_demo_correction()
        self.state.set_managed_signal_ids([demo_signal_id])
        self.state.set_demo_signal(demo_signal_id)
        return demo_signal_id

    def _get_managed_preferences(self) -> List[Preference]:
        """Return existing onboarding-managed preferences."""
        preferences = []
        for pref_id in self.state.get_managed_preference_ids():
            pref = self.storage.preferences.get_preference(pref_id)
            if pref:
                preferences.append(pref)
        return preferences

    def _get_demo_preferences(self) -> List[Preference]:
        """Return existing demo-bundle preferences."""
        preferences = []
        for pref_id in self.state.get_demo_preference_ids():
            pref = self.storage.preferences.get_preference(pref_id)
            if pref:
                preferences.append(pref)
        return preferences

    def _remove_managed_preference_id(self, pref_id: str) -> None:
        """Remove a preference ID from onboarding-managed state."""
        self.state.set_starter_preference_ids(
            [candidate for candidate in self.state.get_starter_preference_ids() if candidate != pref_id]
        )
        self.state.set_demo_preference_ids(
            [candidate for candidate in self.state.get_demo_preference_ids() if candidate != pref_id]
        )
        if self.state.state.get("demo_preference_id") == pref_id:
            self.state.set_demo_preference(None)

    def _edit_managed_preferences(self) -> None:
        """Edit onboarding-managed preferences one by one."""
        while True:
            preferences = self._get_managed_preferences()
            if not preferences:
                print("\nNo onboarding-managed preferences are currently tracked.")
                return

            print("\nManaged preferences:")
            for index, pref in enumerate(preferences, start=1):
                print(f"  {index}. {pref.path} = {pref.value} (confidence {pref.confidence:.0%})")
            print("  q. Back")

            choice = input("Select a preference to edit: ").strip().lower()
            if choice == "q":
                return
            if not choice.isdigit() or not (1 <= int(choice) <= len(preferences)):
                print("Invalid choice.")
                continue

            pref = preferences[int(choice) - 1]
            print("\nEdit options:")
            print("  1. Change value")
            print("  2. Change confidence")
            print("  3. Change description")
            print("  4. Delete this onboarding-managed preference")
            print("  5. Back")
            edit_choice = input("Select an option [5]: ").strip()

            if edit_choice == "1":
                new_value = input(f"New value for {pref.path} [{pref.value}]: ").strip()
                if new_value:
                    pref.value = new_value
                    self.storage.preferences.save_preference(pref)
            elif edit_choice == "2":
                new_confidence = input(f"New confidence for {pref.path} (0.0-1.0) [{pref.confidence}]: ").strip()
                if new_confidence:
                    try:
                        confidence = float(new_confidence)
                    except ValueError:
                        print("Confidence must be a number.")
                        continue
                    if not 0.0 <= confidence <= 1.0:
                        print("Confidence must be between 0.0 and 1.0.")
                        continue
                    pref.confidence = confidence
                    self.storage.preferences.save_preference(pref)
            elif edit_choice == "3":
                pref.description = input(f"New description for {pref.path}: ").strip()
                self.storage.preferences.save_preference(pref)
            elif edit_choice == "4":
                self.storage.delete_preference(pref.id)
                self._remove_managed_preference_id(pref.id)
            else:
                continue

    def show_setup_summary(self) -> None:
        """Display the current onboarding-managed setup."""
        managed_prefs = self._get_managed_preferences()
        print("\n" + "=" * 70)
        print("CURRENT ONBOARDING SETUP")
        print("=" * 70)
        print(f"Starter profile: {self.state.get_starter_profile() or 'None'}")
        print(f"Completed: {'yes' if not self.is_first_run() else 'no'}")
        print(f"Demo bundle present: {'yes' if self.has_demo_preference() else 'no'}")
        print(f"Demo correction recorded: {'yes' if self.has_demo_signal() else 'no'}")
        print(f"Starter preferences: {len(self.state.get_starter_preference_ids())}")
        print(f"Demo preferences: {len(self.state.get_demo_preference_ids())}")
        print(f"Managed preferences: {len(managed_prefs)}")
        for index, pref in enumerate(managed_prefs[:10], start=1):
            print(f"  {index}. {pref.path} = {pref.value} ({pref.confidence:.0%})")

    def run_modify_setup(self) -> bool:
        """Interactive editor for onboarding-managed starter setup."""
        self.base_dir.mkdir(parents=True, exist_ok=True)

        while True:
            starter_profile = self.state.get_starter_profile() or "None"
            managed_pref_count = len(self.state.get_managed_preference_ids())
            has_demo_signal = self.has_demo_signal()

            print("\n" + "=" * 70)
            print("ONBOARDING SETUP MODIFIER")
            print("=" * 70)
            print(f"Current starter profile: {starter_profile}")
            print(f"Managed preferences: {managed_pref_count}")
            print(f"Demo correction recorded: {'yes' if has_demo_signal else 'no'}")
            print("\nOptions:")
            print("  1. Change starter profile or demo setup")
            print("  2. Recreate demo correction")
            print("  3. Review current setup")
            print("  4. Edit managed preferences")
            print("  5. Exit")

            choice = input("Select an option [5]: ").strip()
            if choice in {"", "5"}:
                return True

            if choice == "1":
                print("\nReplacing onboarding-managed setup only. Learned preferences outside onboarding are preserved.")
                template_key = self._select_template_choice()
                if template_key == "quit":
                    continue
                self.cleanup_managed_setup()
                self._apply_starter_choice(template_key)
                recreate_signal = input("Record the demo correction now? (Y/n): ").strip().lower()
                if recreate_signal not in {"n", "no"}:
                    demo_signal_id = self._record_and_track_demo_signal()
                    print(f"✓ Recorded: {demo_signal_id}")
                print("✓ Starter setup updated.")
                continue

            if choice == "2":
                if not self.has_demo_preference():
                    create_demo_bundle = input(
                        "No demo bundle exists yet. Create the demo bundle now? (Y/n): "
                    ).strip().lower()
                    if create_demo_bundle in {"n", "no"}:
                        continue
                    demo_pref_id = self._ensure_demo_bundle()
                    if not self.state.get_starter_profile():
                        self.state.set_starter_profile("DEMO")
                    print(f"✓ Created demo preference bundle: {demo_pref_id}")
                for signal_id in self.state.get_managed_signal_ids():
                    self.storage.delete_signal(signal_id)
                self.state.set_managed_signal_ids([])
                demo_signal_id = self._record_and_track_demo_signal()
                print(f"✓ Re-recorded demo correction: {demo_signal_id}")
                continue

            if choice == "3":
                self.show_setup_summary()
                continue

            if choice == "4":
                self._edit_managed_preferences()
                continue

            print("Invalid choice. Enter 1, 2, 3, 4, or 5.")

    def run_tutorial(self, skip_demo: bool = False) -> bool:
        """Run full interactive tutorial. Returns True if completed."""

        self.base_dir.mkdir(parents=True, exist_ok=True)

        print("\n" + "=" * 70)
        print("ADAPTIVE PREFERENCE ENGINE - ONBOARDING TUTORIAL")
        print("=" * 70)
        print("\nControls:")
        print("  Enter or 1 = continue")
        print("  b = back")
        print("  s = skip to finish")
        print("  q = quit (with confirmation)\n")

        while self.state.get_current_step() < len(self.STEPS):
            step_idx = self.state.get_current_step()
            step = self.STEPS[step_idx]

            print(f"\n[Step {step['number']}/{len(self.STEPS)}] {step['title']}")
            print(f"Duration: {step['duration']}\n")
            print(step["content"])

            # Step 2: Create demo preference or apply selected template
            if step_idx == 1 and not skip_demo:
                if self.state.get_managed_preference_ids():
                    print("\nACTION: Starter setup already exists. Reusing previous setup.")
                else:
                    print("\n" + "─" * 70)
                    self._display_template_options()
                    print("\n" + "─" * 70)

                    template_key = self._select_template_choice()
                    if template_key == "quit":
                        print("\nOnboarding paused. You can resume later with 'adaptive-cli onboard'.")
                        return False

                    self._apply_starter_choice(template_key)

            # Step 3: Record demo correction
            if step_idx == 2 and not skip_demo:
                if self.has_demo_signal():
                    print("\nACTION: Demo correction already recorded. Reusing previous signal.")
                else:
                    print("\n" + "─" * 70)
                    print("ACTION: Recording demo correction signal...")
                    demo_signal_id = self._record_and_track_demo_signal()
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

            action = self._prompt_step_action(step_idx)

            if action == "skip":
                print("\n⏭️  Skipping to end of tutorial...")
                self.state.state["current_step"] = len(self.STEPS) - 1
                self.state._save_state()
            elif action == "back":
                self.state.state["current_step"] = step_idx - 1
                self.state._save_state()
                print("\n⬅️  Going back to previous step...")
            elif action == "quit":
                print("\nOnboarding paused. Resume anytime with 'adaptive-cli onboard'.")
                return False
            else:
                self.state.advance_step()

        self.mark_complete()
        print("\n✅ Onboarding complete! Welcome to the Adaptive Preference Engine!")
        print("   Type 'adaptive-cli pref list' to see your learned preferences.\n")
        return True

    def _create_demo_preference(self) -> str:
        """Create demo preferences for tutorial and return the preferred variant ID."""
        selector = Preference(
            id=generate_id("pref"),
            path="communication.output_format",
            parent_id=None,
            name="output_format",
            type="selector",
            value="bullets",
            confidence=0.7,
            description="Preferred output format for communication",
            auto_detected=False
        )
        bullets = Preference(
            id=generate_id("pref"),
            path="communication.output_format.bullets",
            parent_id=selector.id,
            name="bullets",
            type="variant",
            value="bullets",
            confidence=0.5,
            description="Prefer bullet points for communication outputs",
            auto_detected=False
        )
        tables = Preference(
            id=generate_id("pref"),
            path="communication.output_format.tables",
            parent_id=selector.id,
            name="tables",
            type="variant",
            value="tables",
            confidence=0.5,
            description="Prefer tables for communication outputs",
            auto_detected=False
        )

        self.storage.preferences.save_preference(selector)
        self.storage.preferences.save_preference(bullets)
        self.storage.preferences.save_preference(tables)
        self.state.set_demo_preference_ids([selector.id, bullets.id, tables.id])
        self.state.set_demo_preference(bullets.id)
        return bullets.id

    def _record_demo_correction(self) -> str:
        """Record demo correction signal"""
        bullets_pref_id = self._ensure_demo_bundle()
        bullets_pref = self.storage.preferences.get_preference(bullets_pref_id)
        tables_pref = next(
            (pref for pref in self._get_demo_preferences() if pref.path == "communication.output_format.tables"),
            None,
        )

        if bullets_pref is None or tables_pref is None:
            raise RuntimeError("Demo preferences are not initialized correctly.")

        signal = self.processor.process_correction(
            task="tutorial_demo",
            context_tags=["communication", "tutorial"],
            agent_proposed=tables_pref.id,
            user_corrected_to=bullets_pref.id,
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
