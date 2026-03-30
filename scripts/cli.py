#!/usr/bin/env python3
"""
cli.py - Command-line interface for adaptive preference engine
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path so `scripts` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import (
    Preference, Association, ContextStack, generate_id
)
from scripts.storage import PreferenceStorageManager
from scripts.preference_loader import PreferenceLoader
from scripts.signal_processor import SignalProcessor, StrengthCalculator
from scripts.significance_consolidation_bridge import get_integrated_engine
from scripts.onboarding import OnboardingSystem, check_first_run_and_onboard
from scripts.cli_utils import (
    header, separator, success, error, warn,
    term_width, BOLD, DIM, CYAN, GREEN, YELLOW, RED, RESET
)


class AdaptivePreferenceCLI:
    """CLI interface for preference engine"""

    def __init__(self, base_dir: str = None):
        if base_dir is None:
            base_dir = Path.home() / ".adaptive-cli"

        self.storage = PreferenceStorageManager(str(base_dir))
        self.loader = PreferenceLoader(self.storage)
        self.processor = SignalProcessor(self.storage)
        self.strength_calc = StrengthCalculator(self.storage)
        self.consolidation = get_integrated_engine(str(base_dir))

    # ---- Preference Management ----

    def cmd_create_preference(self, args):
        """Create a new preference"""
        parts = args.path.split(".")
        if len(parts) < 2:
            print(error("--path must use dot notation with at least 2 parts, e.g. communication.output_format"))
            return

        pref = Preference(
            id=generate_id("pref"),
            path=args.path,
            parent_id=args.parent,
            name=args.name,
            type=args.type,
            value=args.value,
            confidence=0.5,
            description=args.description or "",
            auto_detected=False
        )

        self.storage.preferences.save_preference(pref)
        print(success(f"Created preference: {pref.name}"))
        print(f"   ID: {BOLD}{pref.id}{RESET}")
        print(f"   Path: {pref.path}")
        print(f"   Type: {pref.type}")

    def cmd_show_preference(self, args):
        """Display a preference and its metadata"""
        pref = self.storage.preferences.get_preference(args.pref_id)

        if not pref:
            print(error(f"Preference not found: {args.pref_id}"))
            return

        print(header(f"Preference: {pref.name}"))
        print(f"  ID:          {DIM}{pref.id}{RESET}")
        print(f"  Path:        {pref.path}")
        print(f"  Type:        {pref.type}")
        print(f"  Value:       {BOLD}{pref.value}{RESET}")
        conf_color = GREEN if pref.confidence > 0.7 else YELLOW
        print(f"  Confidence:  {conf_color}{pref.confidence:.2%}{RESET}")
        print(f"  Use Count:   {pref.learning.use_count}")
        print(f"  Satisfaction:{pref.learning.satisfaction_rate:.2%}")
        print(f"  Auto-Detected: {pref.auto_detected}")

        assocs = self.storage.associations.get_associations_for_preference(args.pref_id)
        if assocs:
            print(f"\n  {CYAN}Associations ({len(assocs)}):{RESET}")
            for assoc in assocs:
                if assoc.from_id == args.pref_id:
                    strength = assoc.strength_forward
                    direction = "→"
                    target = assoc.to_id
                else:
                    strength = assoc.strength_backward
                    direction = "←"
                    target = assoc.from_id
                print(f"    {direction} {target} (strength: {strength:.2%})")

    def cmd_list_preferences(self, args):
        """List all preferences"""
        prefs = self.storage.preferences.get_all_preferences()

        if not prefs:
            print("No preferences found. Record a correction to start learning:")
            print(f"  {DIM}adaptive-cli signal correction --task X --proposed A --corrected B --message \"...\"  {RESET}")
            return

        if args.path:
            prefs = [p for p in prefs if p.path.startswith(args.path)]

        print(header(f"Preferences ({len(prefs)} total)"))

        for pref in sorted(prefs, key=lambda p: p.path):
            status_color = GREEN if pref.confidence > 0.7 else YELLOW
            status = "✓" if pref.confidence > 0.7 else "○"
            print(f"{status_color}{status}{RESET} {BOLD}{pref.path}{RESET}")
            print(f"   Value: {pref.value} | Confidence: {pref.confidence:.0%} | Uses: {pref.learning.use_count}")

    def cmd_delete_preference(self, args):
        """Delete a preference by ID"""
        pref = self.storage.preferences.get_preference(args.pref_id)
        if not pref:
            print(error(f"Preference not found: {args.pref_id}"))
            return
        confirm = input(f"Delete '{pref.path}'? (y/n): ")
        if confirm.lower() != 'y':
            print("Cancelled.")
            return
        self.storage.delete_preference(args.pref_id)
        print(success(f"Deleted preference: {pref.path}"))

    def cmd_update_preference(self, args):
        """Update an existing preference"""
        pref = self.storage.preferences.get_preference(args.pref_id)
        if not pref:
            print(error(f"Preference not found: {args.pref_id}"))
            return
        if args.value is not None:
            pref.value = args.value
        if args.description is not None:
            pref.description = args.description
        if args.confidence is not None:
            if not 0.0 <= args.confidence <= 1.0:
                print(error("--confidence must be between 0.0 and 1.0"))
                return
            pref.confidence = args.confidence
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)
        print(success(f"Updated preference: {pref.path}"))
        print(f"   Value: {pref.value} | Confidence: {pref.confidence:.0%}")

    # ---- Association Management ----

    def cmd_create_association(self, args):
        """Create an association between two preferences"""
        assoc = Association(
            id=generate_id("assoc"),
            from_id=args.from_id,
            to_id=args.to_id,
            strength_forward=args.strength_forward,
            strength_backward=args.strength_backward,
            description=args.description or "",
            context_tags=args.tags or []
        )

        self.storage.associations.save_association(assoc)
        print(success(f"Created association: {args.from_id} ↔ {args.to_id}"))
        print(f"   Forward strength:  {args.strength_forward:.0%}")
        print(f"   Backward strength: {args.strength_backward:.0%}")

    def cmd_show_associations(self, args):
        """Show associations for a preference"""
        assocs = self.storage.associations.get_associations_for_preference(args.pref_id)

        if not assocs:
            print(f"No associations for: {args.pref_id}")
            return

        print(header(f"Associations for: {args.pref_id}"))

        for assoc in assocs:
            if assoc.from_id == args.pref_id:
                print(f"→ {assoc.to_id}")
                print(f"  Strength: {assoc.strength_forward:.2%} | Uses: {assoc.learning_forward.use_count} | Satisfaction: {assoc.learning_forward.satisfaction_rate:.0%}")
            else:
                print(f"← {assoc.from_id}")
                print(f"  Strength: {assoc.strength_backward:.2%} | Uses: {assoc.learning_backward.use_count} | Satisfaction: {assoc.learning_backward.satisfaction_rate:.0%}")

    # ---- Context Management ----

    def cmd_create_context(self, args):
        """Create a context stack"""
        ctx = ContextStack(
            id=generate_id("ctx"),
            name=args.name,
            scope=args.scope,
            stack_level={"base": 0, "project": 1, "conversation": 2}[args.scope],
            preferences={}
        )

        self.storage.contexts.save_context(ctx)
        print(success(f"Created context: {ctx.name}"))
        print(f"   ID: {BOLD}{ctx.id}{RESET}")
        print(f"   Scope: {ctx.scope}")

    def cmd_set_context_preference(self, args):
        """Set a preference value in a context"""
        ctx = self.storage.contexts.get_context(args.context_id)

        if not ctx:
            print(error(f"Context not found: {args.context_id}"))
            return

        ctx.preferences[args.pref_id] = {
            "value": args.value,
            "confidence": args.confidence or 0.8,
            "source": "manual"
        }

        self.storage.contexts.save_context(ctx)
        print(success(f"Set {args.pref_id} = {args.value} in context '{ctx.name}'"))

    def cmd_show_context(self, args):
        """Show context details"""
        ctx = self.storage.contexts.get_context(args.context_id)

        if not ctx:
            print(error(f"Context not found: {args.context_id}"))
            return

        print(header(f"Context: {ctx.name}"))
        print(f"  ID:    {DIM}{ctx.id}{RESET}")
        print(f"  Scope: {ctx.scope}")
        print(f"  Level: {ctx.stack_level}")
        print(f"  Active: {ctx.active}")
        print(f"\n  Preferences ({len(ctx.preferences)}):")

        for pref_id, pref_data in ctx.preferences.items():
            conf = pref_data.get("confidence", 0)
            value = pref_data.get("value")
            print(f"    {pref_id} = {BOLD}{value}{RESET} (confidence: {conf:.0%})")

    # ---- Learning / Signal Processing ----

    def cmd_signal_correction(self, args):
        """Process a correction signal"""
        signal = self.processor.process_correction(
            task=args.task,
            context_tags=args.context,
            agent_proposed=args.proposed,
            user_corrected_to=args.corrected,
            user_message=args.message or ""
        )

        print(success(f"Correction recorded: {args.proposed} → {args.corrected}"))
        print(f"   Task: {args.task} | Context: {', '.join(args.context)}")
        print(f"   Emotion: {signal.emotional_tone}")

        if signal.preferences_affected:
            print(f"\n{CYAN}What I learned:{RESET}")
            for pref_change in signal.preferences_affected:
                pref_id = pref_change.get('preference_id') or pref_change.get('id', '')
                pref = self.storage.preferences.get_preference(pref_id) if pref_id else None
                if pref:
                    print(f"   {pref.path}: confidence now {pref.confidence:.0%} ({pref.learning.use_count} uses)")
        elif signal.associations_affected:
            print(f"   Associations updated: {len(signal.associations_affected)}")
        else:
            print(f"   {DIM}Learning stored. Confidence grows with repeated corrections.{RESET}")

    def cmd_signal_feedback(self, args):
        """Process a feedback signal"""
        signal = self.processor.process_feedback(
            task=args.task,
            context_tags=args.context,
            preferences_used=args.preferences,
            user_response=args.response,
            satisfaction_level=args.satisfaction
        )

        print(success("Feedback recorded"))
        print(f"   Task: {args.task} | Context: {', '.join(args.context)}")
        print(f"   Preferences: {', '.join(args.preferences)}")
        print(f"   Emotion: {signal.emotional_tone}")

    # ---- Loading / Display ----

    def cmd_load_preferences(self, args):
        """Load preferences for given context"""
        loaded = self.loader.load_for_context(
            context_tags=args.context,
            primary_pref_id=args.primary,
            stack_contexts=args.stack
        )

        print(header(f"Loaded Preferences — context: {', '.join(args.context)}"))

        if loaded["primary"]:
            print(f"\n{GREEN}✨ Primary:{RESET} {loaded['primary']['path']}")
            print(f"   Value: {loaded['primary']['value']}")
            print(f"   Confidence: {loaded['primary']['confidence']:.0%}")

        if loaded["associated"]:
            print(f"\n{CYAN}Associated ({len(loaded['associated'])}):{RESET}")
            for assoc in loaded["associated"]:
                depth_indent = "  " * assoc["depth"]
                print(f"{depth_indent}→ {assoc['path']}")
                print(f"{depth_indent}  Confidence: {assoc['confidence']:.0%} | Strength: {assoc['association_strength']:.0%} | Trend: {assoc['trend']}")

    def cmd_agent_context(self, args):
        """Generate context JSON for agent"""
        agent_json = self.loader.load_for_agent(
            context_tags=args.context,
            primary_pref_id=args.primary,
            stack_contexts=args.stack
        )

        if args.output:
            with open(args.output, 'w') as f:
                f.write(agent_json)
            print(success(f"Wrote agent context to {args.output}"))
        else:
            print(agent_json)

    # ---- Maintenance ----

    def cmd_recalculate_strengths(self, args):
        """Recalculate all association strengths"""
        results = self.strength_calc.recalculate_all()

        print(success(f"Recalculated {results['updated']} / {results['total']} associations"))
        if args.details and results['details']:
            print(f"\n{CYAN}Details:{RESET}")
            for detail in results['details'][:10]:
                print(f"   {detail['assoc_id']}")
                print(f"      → {detail['forward']['old']:.2%} → {detail['forward']['new']:.2%}")
                print(f"      ← {detail['backward']['old']:.2%} → {detail['backward']['new']:.2%}")

    def cmd_apply_decay(self, args):
        """Apply time decay to associations"""
        results = self.strength_calc.apply_time_decay()

        print(success(f"Applied time decay to {results['decayed']} associations"))
        if results['decayed'] > 0 and args.details:
            print(f"\n{CYAN}Details (first 5):{RESET}")
            for detail in results['details'][:5]:
                print(f"   {detail['assoc_id']}")
                print(f"      Days unused: {detail['days_since_decay']}")
                print(f"      Decay: {detail['decay_multiplier']:.2%}")

    def cmd_show_stats(self, args):
        """Show storage statistics"""
        info = self.storage.get_storage_info()

        print(header("Storage Statistics"))
        print(f"  {DIM}Location:{RESET}  {info['base_dir']}")
        print(separator())
        print(f"  Preferences:  {BOLD}{info['preferences_count']}{RESET}")
        print(f"  Associations: {BOLD}{info['associations_count']}{RESET}")
        print(f"  Contexts:     {BOLD}{info['contexts_count']}{RESET}")
        print(f"  Signals:      {BOLD}{info['signals_count']}{RESET}")

    # ---- Consolidation ----

    def cmd_consolidate_daily(self, args):
        """Run daily consolidation cycle"""
        result = self.consolidation.run_daily_consolidation()

        print(header("Daily Consolidation Complete"))
        print(result["consolidation_details"])

        if result["preferences_promoted"]:
            print(f"\n{GREEN}✨ Promoted ({len(result['preferences_promoted'])}):{RESET}")
            for pref_id in result["preferences_promoted"]:
                pref = self.storage.preferences.get_preference(pref_id)
                if pref:
                    change = result["stage_changes"].get(pref_id, {})
                    new_conf = result["confidence_updates"].get(pref_id, pref.confidence)
                    print(
                        f"   {pref.path:40s} "
                        f"{change.get('from', '?'):12s} → {change.get('to', '?'):12s} "
                        f"(confidence: {new_conf:.0%})"
                    )

        if result["preferences_demoted"]:
            print(f"\n{YELLOW}⚠️  Demoted ({len(result['preferences_demoted'])}):{RESET}")
            for pref_id in result["preferences_demoted"]:
                pref = self.storage.preferences.get_preference(pref_id)
                if pref:
                    new_conf = result["confidence_updates"].get(pref_id, pref.confidence)
                    print(f"   {pref.path:40s} (confidence: {new_conf:.0%})")

    def cmd_consolidation_report(self, args):
        """Show consolidation report"""
        report = self.consolidation.get_consolidation_report()
        print(report)

    def cmd_reset(self, args):
        """Reset all preferences"""
        response = input(warn("Clear all preferences? This will back up old data. (y/n): "))
        if response.lower() != 'y':
            print("Cancelled.")
            return
        self.storage.reset()

    # ---- Onboarding ----

    def cmd_onboard(self, args):
        """Run onboarding tutorial"""
        onboarding = OnboardingSystem(str(self.storage.base_dir))

        if args.reset:
            complete_file = Path(self.storage.base_dir) / "onboarding_complete"
            if complete_file.exists():
                complete_file.unlink()
            print(success("Onboarding reset. Run 'adaptive-cli onboard' to restart."))
        else:
            if not onboarding.is_first_run():
                print("✓ You've already completed onboarding!")
                print("  Run 'adaptive-cli onboard --reset' to restart the tutorial.")
                return
            onboarding.run_tutorial(skip_demo=False)

    def cmd_digest_weekly(self, args):
        """Show weekly learning digest"""
        onboarding = OnboardingSystem(str(self.storage.base_dir))
        digest = onboarding.generate_weekly_digest()
        print(digest)


def main():
    parser = argparse.ArgumentParser(
        description="Adaptive Preference Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Most useful commands:
  adaptive-cli onboard                        # Interactive setup (~2 min)
  adaptive-cli pref list                      # See all learned preferences
  adaptive-cli signal correction --task X --proposed A --corrected B
  adaptive-cli stats                          # Engine statistics
  adaptive-cli digest                         # Weekly learning summary

All commands:
  pref    create / show / list / update / delete
  assoc   create / show
  context create / set-pref / show
  signal  correction / feedback
  load, agent-context, stats, recalculate, decay, consolidate, reset, onboard, digest
        """
    )

    parser.add_argument("--skip-onboarding", action="store_true", dest="skip_onboarding",
                        help="Skip first-run onboarding tutorial")

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Preference commands
    pref_parser = subparsers.add_parser("pref", help="Manage preferences")
    pref_sub = pref_parser.add_subparsers(dest="subcommand")

    create_pref = pref_sub.add_parser("create", help="Create preference")
    create_pref.add_argument("--name", required=True)
    create_pref.add_argument("--path", required=True, metavar="DOMAIN.CATEGORY.NAME",
                              help="Dotted path, e.g. communication.output_format.bullets")
    create_pref.add_argument("--type", required=True, choices=["selector", "variant", "property"])
    create_pref.add_argument("--parent", default=None)
    create_pref.add_argument("--value", default=None)
    create_pref.add_argument("--description", default=None)

    show_pref = pref_sub.add_parser("show", help="Show preference details")
    show_pref.add_argument("pref_id")

    list_pref = pref_sub.add_parser("list", help="List all preferences")
    list_pref.add_argument("--path", default=None, help="Filter by path prefix")

    delete_pref = pref_sub.add_parser("delete", help="Delete a preference by ID")
    delete_pref.add_argument("pref_id", help="Preference ID to delete")

    update_pref = pref_sub.add_parser("update", help="Update an existing preference")
    update_pref.add_argument("pref_id", help="Preference ID to update")
    update_pref.add_argument("--value", default=None, help="New value")
    update_pref.add_argument("--description", default=None, help="New description")
    update_pref.add_argument("--confidence", type=float, default=None, help="New confidence (0.0–1.0)")

    # Association commands
    assoc_parser = subparsers.add_parser("assoc", help="Manage associations")
    assoc_sub = assoc_parser.add_subparsers(dest="subcommand")

    def strength_float(value):
        f = float(value)
        if not 0.0 <= f <= 1.0:
            raise argparse.ArgumentTypeError(f"Strength must be 0.0–1.0, got {f}")
        return f

    create_assoc = assoc_sub.add_parser("create", help="Create association")
    create_assoc.add_argument("--from-id", required=True, dest="from_id")
    create_assoc.add_argument("--to-id", required=True, dest="to_id")
    create_assoc.add_argument("--strength-forward", type=strength_float, default=0.5)
    create_assoc.add_argument("--strength-backward", type=strength_float, default=0.5)
    create_assoc.add_argument("--description", default=None)
    create_assoc.add_argument("--tags", nargs="+", default=None)

    show_assoc = assoc_sub.add_parser("show", help="Show associations")
    show_assoc.add_argument("pref_id")

    # Context commands
    ctx_parser = subparsers.add_parser("context", help="Manage contexts")
    ctx_sub = ctx_parser.add_subparsers(dest="subcommand")

    create_ctx = ctx_sub.add_parser("create", help="Create context")
    create_ctx.add_argument("--name", required=True)
    create_ctx.add_argument("--scope", required=True, choices=["base", "project", "conversation"])

    set_ctx_pref = ctx_sub.add_parser("set-pref", help="Set preference in context")
    set_ctx_pref.add_argument("context_id")
    set_ctx_pref.add_argument("pref_id")
    set_ctx_pref.add_argument("value")
    set_ctx_pref.add_argument("--confidence", type=float, default=0.8)

    show_ctx = ctx_sub.add_parser("show", help="Show context")
    show_ctx.add_argument("context_id")

    # Signal commands
    signal_parser = subparsers.add_parser("signal", help="Record signals")
    signal_sub = signal_parser.add_subparsers(dest="subcommand")

    corr = signal_sub.add_parser("correction", help="Record correction")
    corr.add_argument("--task", required=True)
    corr.add_argument("--context", nargs="+", default=["general"])
    corr.add_argument("--proposed", required=True)
    corr.add_argument("--corrected", required=True)
    corr.add_argument("--message", default=None)

    feedback = signal_sub.add_parser("feedback", help="Record feedback")
    feedback.add_argument("--task", required=True)
    feedback.add_argument("--context", nargs="+", default=["general"])
    feedback.add_argument("--preferences", nargs="+", required=True)
    feedback.add_argument("--response", required=True)
    feedback.add_argument("--satisfaction", type=float, default=None)

    # Loading commands
    load_parser = subparsers.add_parser("load", help="Load preferences")
    load_parser.add_argument("--context", nargs="+", required=True)
    load_parser.add_argument("--primary", default=None)
    load_parser.add_argument("--stack", nargs="+", default=None)

    # Agent context
    agent_parser = subparsers.add_parser("agent-context", help="Generate agent context JSON")
    agent_parser.add_argument("--context", nargs="+", required=True)
    agent_parser.add_argument("--primary", default=None)
    agent_parser.add_argument("--stack", nargs="+", default=None)
    agent_parser.add_argument("--output", default=None)

    # Maintenance
    subparsers.add_parser("stats", help="Show statistics")

    recalc_parser = subparsers.add_parser("recalculate", help="Recalculate strengths")
    recalc_parser.add_argument("--details", action="store_true")

    decay_parser = subparsers.add_parser("decay", help="Apply time decay")
    decay_parser.add_argument("--details", action="store_true")

    consolidate_parser = subparsers.add_parser("consolidate", help="Run consolidation cycle")
    consolidate_sub = consolidate_parser.add_subparsers(dest="subcommand")
    consolidate_sub.add_parser("daily", help="Run daily consolidation")
    consolidate_sub.add_parser("report", help="Show consolidation report")

    subparsers.add_parser("reset", help="Reset all preferences")

    # Onboarding
    onboard_parser = subparsers.add_parser("onboard", help="Run onboarding tutorial")
    onboard_parser.add_argument("--reset", action="store_true", help="Reset and restart tutorial")

    digest_parser = subparsers.add_parser("digest", help="Show learning digest")
    digest_sub = digest_parser.add_subparsers(dest="subcommand")
    digest_sub.add_parser("weekly", help="Show weekly learning digest")

    args = parser.parse_args()

    # First-run onboarding intercept
    skip_onboarding = args.skip_onboarding or args.command == "onboard"
    check_first_run_and_onboard(skip_onboarding=skip_onboarding)

    cli = AdaptivePreferenceCLI()

    try:
        if args.command == "pref":
            if args.subcommand == "create":
                cli.cmd_create_preference(args)
            elif args.subcommand == "show":
                cli.cmd_show_preference(args)
            elif args.subcommand == "list":
                cli.cmd_list_preferences(args)
            elif args.subcommand == "delete":
                cli.cmd_delete_preference(args)
            elif args.subcommand == "update":
                cli.cmd_update_preference(args)
            else:
                pref_parser.print_help()

        elif args.command == "assoc":
            if args.subcommand == "create":
                cli.cmd_create_association(args)
            elif args.subcommand == "show":
                cli.cmd_show_associations(args)
            else:
                assoc_parser.print_help()

        elif args.command == "context":
            if args.subcommand == "create":
                cli.cmd_create_context(args)
            elif args.subcommand == "set-pref":
                cli.cmd_set_context_preference(args)
            elif args.subcommand == "show":
                cli.cmd_show_context(args)
            else:
                ctx_parser.print_help()

        elif args.command == "signal":
            if args.subcommand == "correction":
                cli.cmd_signal_correction(args)
            elif args.subcommand == "feedback":
                cli.cmd_signal_feedback(args)
            else:
                signal_parser.print_help()

        elif args.command == "load":
            cli.cmd_load_preferences(args)

        elif args.command == "agent-context":
            cli.cmd_agent_context(args)

        elif args.command == "stats":
            cli.cmd_show_stats(args)

        elif args.command == "recalculate":
            cli.cmd_recalculate_strengths(args)

        elif args.command == "decay":
            cli.cmd_apply_decay(args)

        elif args.command == "consolidate":
            if args.subcommand == "daily":
                cli.cmd_consolidate_daily(args)
            elif args.subcommand == "report":
                cli.cmd_consolidation_report(args)
            else:
                consolidate_parser.print_help()

        elif args.command == "reset":
            cli.cmd_reset(args)

        elif args.command == "onboard":
            cli.cmd_onboard(args)

        elif args.command == "digest":
            if args.subcommand == "weekly" or args.subcommand is None:
                cli.cmd_digest_weekly(args)
            else:
                digest_parser.print_help()

        else:
            parser.print_help()

    except Exception as e:
        print(error(f"Error: {e}"))
        sys.exit(1)


if __name__ == "__main__":
    main()
