#!/usr/bin/env python3
"""
cli.py - Command-line interface for adaptive preference engine
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path so `scripts` package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import (
    Preference, Association, AssociationLearning, ContextStack,
    Signal, generate_id
)
from scripts.storage import PreferenceStorageManager
from scripts.preference_loader import PreferenceLoader
from scripts.signal_processor import SignalProcessor, StrengthCalculator
from scripts.significance_consolidation_bridge import get_integrated_engine
from scripts.onboarding import OnboardingSystem, check_first_run_and_onboard


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
        print(f"✅ Created preference: {pref.name}")
        print(f"   ID: {pref.id}")
        print(f"   Path: {pref.path}")
        print(f"   Type: {pref.type}")
    
    def cmd_show_preference(self, args):
        """Display a preference and its metadata"""
        pref = self.storage.preferences.get_preference(args.pref_id)
        
        if not pref:
            print(f"❌ Preference not found: {args.pref_id}")
            return
        
        print(f"\n📋 Preference: {pref.name}")
        print(f"   ID: {pref.id}")
        print(f"   Path: {pref.path}")
        print(f"   Type: {pref.type}")
        print(f"   Value: {pref.value}")
        print(f"   Confidence: {pref.confidence:.2%}")
        print(f"   Use Count: {pref.learning.use_count}")
        print(f"   Satisfaction: {pref.learning.satisfaction_rate:.2%}")
        print(f"   Auto-Detected: {pref.auto_detected}")
        
        # Show associations
        assocs = self.storage.associations.get_associations_for_preference(args.pref_id)
        if assocs:
            print(f"\n   📎 Associations ({len(assocs)}):")
            for assoc in assocs:
                if assoc.from_id == args.pref_id:
                    strength = assoc.strength_forward
                    direction = "→"
                    target = assoc.to_id
                else:
                    strength = assoc.strength_backward
                    direction = "←"
                    target = assoc.from_id
                
                print(f"      {direction} {target} (strength: {strength:.2%})")
    
    def cmd_list_preferences(self, args):
        """List all preferences"""
        prefs = self.storage.preferences.get_all_preferences()
        
        if not prefs:
            print("No preferences found.")
            return
        
        # Filter by path if specified
        if args.path:
            prefs = [p for p in prefs if p.path.startswith(args.path)]
        
        print(f"\n📊 Preferences ({len(prefs)} total)")
        print("─" * 80)
        
        for pref in sorted(prefs, key=lambda p: p.path):
            status = "✓" if pref.confidence > 0.7 else "○"
            print(f"{status} {pref.path}")
            print(f"   Value: {pref.value} | Confidence: {pref.confidence:.0%} | Uses: {pref.learning.use_count}")
    
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
        print(f"✅ Created association: {args.from_id} ↔ {args.to_id}")
        print(f"   Strength (→): {args.strength_forward}")
        print(f"   Strength (←): {args.strength_backward}")
    
    def cmd_show_associations(self, args):
        """Show associations for a preference"""
        assocs = self.storage.associations.get_associations_for_preference(args.pref_id)
        
        if not assocs:
            print(f"No associations for: {args.pref_id}")
            return
        
        print(f"\n🔗 Associations for: {args.pref_id}")
        print("─" * 80)
        
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
        print(f"✅ Created context: {ctx.name}")
        print(f"   ID: {ctx.id}")
        print(f"   Scope: {ctx.scope}")
    
    def cmd_set_context_preference(self, args):
        """Set a preference value in a context"""
        ctx = self.storage.contexts.get_context(args.context_id)
        
        if not ctx:
            print(f"❌ Context not found: {args.context_id}")
            return
        
        ctx.preferences[args.pref_id] = {
            "value": args.value,
            "confidence": args.confidence or 0.8,
            "source": "manual"
        }
        
        self.storage.contexts.save_context(ctx)
        print(f"✅ Set {args.pref_id} = {args.value} in context {ctx.name}")
    
    def cmd_show_context(self, args):
        """Show context details"""
        ctx = self.storage.contexts.get_context(args.context_id)
        
        if not ctx:
            print(f"❌ Context not found: {args.context_id}")
            return
        
        print(f"\n📍 Context: {ctx.name}")
        print(f"   ID: {ctx.id}")
        print(f"   Scope: {ctx.scope}")
        print(f"   Level: {ctx.stack_level}")
        print(f"   Active: {ctx.active}")
        print(f"\n   Preferences ({len(ctx.preferences)}):")
        
        for pref_id, pref_data in ctx.preferences.items():
            conf = pref_data.get("confidence", 0)
            value = pref_data.get("value")
            print(f"      {pref_id} = {value} (confidence: {conf:.0%})")
    
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
        
        print(f"✅ Recorded correction signal")
        print(f"   Task: {args.task}")
        print(f"   Proposed: {args.proposed} → Corrected: {args.corrected}")
        print(f"   Emotion: {signal.emotional_tone}")
        print(f"   Associations updated: {len(signal.associations_affected)}")
    
    def cmd_signal_feedback(self, args):
        """Process a feedback signal"""
        signal = self.processor.process_feedback(
            task=args.task,
            context_tags=args.context,
            preferences_used=args.preferences,
            user_response=args.response,
            satisfaction_level=args.satisfaction
        )
        
        print(f"✅ Recorded feedback signal")
        print(f"   Task: {args.task}")
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
        
        print(f"\n📥 Loaded Preferences for context: {', '.join(args.context)}")
        print("─" * 80)
        
        if loaded["primary"]:
            print(f"\n✨ Primary: {loaded['primary']['path']}")
            print(f"   Value: {loaded['primary']['value']}")
            print(f"   Confidence: {loaded['primary']['confidence']:.0%}")
        
        if loaded["associated"]:
            print(f"\n📎 Associated ({len(loaded['associated'])}):")
            for assoc in loaded["associated"]:
                depth_indent = "  " * assoc["depth"]
                print(f"{depth_indent}→ {assoc['path']}")
                print(f"{depth_indent}  Confidence: {assoc['confidence']:.0%} | Strength: {assoc['association_strength']:.0%} | Trend: {assoc['trend']}")
    
    def cmd_agent_context(self, args):
        """Generate context JSON for agent"""
        loaded = self.loader.load_for_context(
            context_tags=args.context,
            primary_pref_id=args.primary,
            stack_contexts=args.stack
        )
        
        agent_json = self.loader.load_for_agent(
            context_tags=args.context,
            primary_pref_id=args.primary,
            stack_contexts=args.stack
        )
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(agent_json)
            print(f"✅ Wrote agent context to {args.output}")
        else:
            print(agent_json)
    
    # ---- Maintenance ----
    
    def cmd_recalculate_strengths(self, args):
        """Recalculate all association strengths"""
        results = self.strength_calc.recalculate_all()
        
        print(f"✅ Recalculated {results['updated']} / {results['total']} associations")
        if args.details and results['details']:
            print("\n   Details:")
            for detail in results['details'][:10]:  # Show first 10
                print(f"   {detail['assoc_id']}")
                print(f"      → {detail['forward']['old']:.2%} → {detail['forward']['new']:.2%}")
                print(f"      ← {detail['backward']['old']:.2%} → {detail['backward']['new']:.2%}")
    
    def cmd_apply_decay(self, args):
        """Apply time decay to associations"""
        results = self.strength_calc.apply_time_decay()
        
        print(f"✅ Applied time decay to {results['decayed']} associations")
        if results['decayed'] > 0 and args.details:
            print("\n   Details (first 5):")
            for detail in results['details'][:5]:
                print(f"   {detail['assoc_id']}")
                print(f"      Days unused: {detail['days_since_decay']}")
                print(f"      Decay: {detail['decay_multiplier']:.2%}")
    
    def cmd_show_stats(self, args):
        """Show storage statistics"""
        info = self.storage.get_storage_info()
        
        print(f"\n📊 Storage Statistics")
        print(f"   Base Dir: {info['base_dir']}")
        print(f"   Preferences: {info['preferences_count']}")
        print(f"   Associations: {info['associations_count']}")
        print(f"   Contexts: {info['contexts_count']}")
        print(f"   Signals: {info['signals_count']}")
    
    # ---- Consolidation ----

    def cmd_consolidate_daily(self, args):
        """Run daily consolidation cycle"""
        result = self.consolidation.run_daily_consolidation()

        print(f"\n🧠 Daily Consolidation Complete")
        print("─" * 80)
        print(result["consolidation_details"])

        if result["preferences_promoted"]:
            print(f"\n✨ Promoted Preferences ({len(result['preferences_promoted'])}):")
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
            print(f"\n⚠️  Demoted Preferences ({len(result['preferences_demoted'])}):")
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
        self.storage.reset(confirm=True)

    # ---- Onboarding ----

    def cmd_onboard(self, args):
        """Run onboarding tutorial"""
        onboarding = OnboardingSystem(str(self.storage.base_dir))

        if args.reset:
            # Reset onboarding marker to restart tutorial
            complete_file = Path(self.storage.base_dir) / "onboarding_complete"
            if complete_file.exists():
                complete_file.unlink()
            print("✓ Onboarding reset. Tutorial will run on next command.")
        else:
            # Run tutorial
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
        description="Adaptive Preference Engine - Phase 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run onboarding tutorial (first time only)
  adaptive-cli onboard

  # View weekly learning summary
  adaptive-cli digest weekly

  # Create a preference
  adaptive-cli pref create --name bullets --path communication.output_format.bullets \\
    --type variant --parent comm_format

  # Create an association
  adaptive-cli assoc create --from comm_bullets --to coding_datastructure \\
    --strength-forward 0.95 --strength-backward 0.70

  # Load preferences for context
  adaptive-cli load --context communication structure

  # Record a correction
  adaptive-cli signal correction --task api_design --proposed comm_bullets \\
    --corrected comm_table --message "Perfect, that's what I needed!"

  # Generate agent context
  adaptive-cli agent-context --context python fastapi --output context.json
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Preference commands
    pref_parser = subparsers.add_parser("pref", help="Manage preferences")
    pref_sub = pref_parser.add_subparsers(dest="subcommand")
    
    create_pref = pref_sub.add_parser("create", help="Create preference")
    create_pref.add_argument("--name", required=True)
    create_pref.add_argument("--path", required=True)
    create_pref.add_argument("--type", required=True, choices=["selector", "variant", "property"])
    create_pref.add_argument("--parent", default=None)
    create_pref.add_argument("--value", default=None)
    create_pref.add_argument("--description", default=None)
    
    show_pref = pref_sub.add_parser("show", help="Show preference")
    show_pref.add_argument("pref_id")
    
    list_pref = pref_sub.add_parser("list", help="List preferences")
    list_pref.add_argument("--path", default=None, help="Filter by path prefix")
    
    # Association commands
    assoc_parser = subparsers.add_parser("assoc", help="Manage associations")
    assoc_sub = assoc_parser.add_subparsers(dest="subcommand")
    
    create_assoc = assoc_sub.add_parser("create", help="Create association")
    create_assoc.add_argument("--from-id", required=True, dest="from_id")
    create_assoc.add_argument("--to-id", required=True, dest="to_id")
    create_assoc.add_argument("--strength-forward", type=float, default=0.5)
    create_assoc.add_argument("--strength-backward", type=float, default=0.5)
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
    corr.add_argument("--context", nargs="+", required=True)
    corr.add_argument("--proposed", required=True)
    corr.add_argument("--corrected", required=True)
    corr.add_argument("--message", default=None)
    
    feedback = signal_sub.add_parser("feedback", help="Record feedback")
    feedback.add_argument("--task", required=True)
    feedback.add_argument("--context", nargs="+", required=True)
    feedback.add_argument("--preferences", nargs="+", required=True)
    feedback.add_argument("--response", required=True)
    feedback.add_argument("--satisfaction", type=float, default=None)
    
    # Loading commands
    load_parser = subparsers.add_parser("load", help="Load preferences")
    load_parser.add_argument("--context", nargs="+", required=True)
    load_parser.add_argument("--primary", default=None)
    load_parser.add_argument("--stack", nargs="+", default=None)
    
    # Agent context
    agent_parser = subparsers.add_parser("agent-context", help="Generate agent context")
    agent_parser.add_argument("--context", nargs="+", required=True)
    agent_parser.add_argument("--primary", default=None)
    agent_parser.add_argument("--stack", nargs="+", default=None)
    agent_parser.add_argument("--output", default=None)
    
    # Maintenance commands
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    
    recalc_parser = subparsers.add_parser("recalculate", help="Recalculate strengths")
    recalc_parser.add_argument("--details", action="store_true")
    
    decay_parser = subparsers.add_parser("decay", help="Apply time decay")
    decay_parser.add_argument("--details", action="store_true")

    consolidate_parser = subparsers.add_parser("consolidate", help="Run consolidation cycle")
    consolidate_sub = consolidate_parser.add_subparsers(dest="subcommand")

    daily_consol = consolidate_sub.add_parser("daily", help="Run daily consolidation")

    report_consol = consolidate_sub.add_parser("report", help="Show consolidation report")

    reset_parser = subparsers.add_parser("reset", help="Reset all preferences")

    # Onboarding commands
    onboard_parser = subparsers.add_parser("onboard", help="Run onboarding tutorial")
    onboard_parser.add_argument("--reset", action="store_true", help="Reset onboarding to restart tutorial")

    digest_parser = subparsers.add_parser("digest", help="Show learning digest")
    digest_sub = digest_parser.add_subparsers(dest="subcommand")
    weekly_digest = digest_sub.add_parser("weekly", help="Show weekly learning digest")
    
    args = parser.parse_args()

    # Check for first-run and trigger onboarding if needed
    # Only skip if explicitly requested via --skip-onboarding flag or if running onboard command
    skip_onboarding = getattr(args, 'skip_onboarding', False) or args.command == "onboard"
    check_first_run_and_onboard(skip_onboarding=skip_onboarding)

    cli = AdaptivePreferenceCLI()

    # Route commands
    try:
        if args.command == "pref":
            if args.subcommand == "create":
                cli.cmd_create_preference(args)
            elif args.subcommand == "show":
                cli.cmd_show_preference(args)
            elif args.subcommand == "list":
                cli.cmd_list_preferences(args)
        
        elif args.command == "assoc":
            if args.subcommand == "create":
                cli.cmd_create_association(args)
            elif args.subcommand == "show":
                cli.cmd_show_associations(args)
        
        elif args.command == "context":
            if args.subcommand == "create":
                cli.cmd_create_context(args)
            elif args.subcommand == "set-pref":
                cli.cmd_set_context_preference(args)
            elif args.subcommand == "show":
                cli.cmd_show_context(args)
        
        elif args.command == "signal":
            if args.subcommand == "correction":
                cli.cmd_signal_correction(args)
            elif args.subcommand == "feedback":
                cli.cmd_signal_feedback(args)
        
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
            if args.subcommand == "weekly":
                cli.cmd_digest_weekly(args)
            else:
                digest_parser.print_help()

        else:
            parser.print_help()
    
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
