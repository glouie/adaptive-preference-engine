#!/usr/bin/env python3
"""
cli.py - Command-line interface for adaptive preference engine
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.behaviors import Behavior, parse_ape_header
from scripts.models import (
    Preference, Association, AssociationLearning, ContextStack,
    Signal, generate_id
)
from scripts.storage import PreferenceStorageManager
from scripts.preference_loader import PreferenceLoader
from adaptive_preference_engine.services.signals import SignalProcessor, StrengthCalculator
from adaptive_preference_engine.services.tiering import TieringEngine
from scripts.config import AdaptiveConfig
from scripts.sync import SyncRunner
from scripts.preference_templates import list_templates, get_template
from scripts.onboarding import OnboardingSystem
from scripts.cli_utils import success, error, warn

# Behavior system constants
_BEHAVIOR_PLATFORMS = ["any", "github", "gitlab", "bitbucket", "azure-devops", "gitea"]
_BEHAVIOR_HOOK_EVENTS = ["PostToolUse", "PreToolUse", "SessionStart", "Stop", "none"]
_BEHAVIOR_MATCHERS = ["Bash", "Write", "Edit", "Read", "Glob", "Grep", "other"]


class AdaptivePreferenceCLI:
    """CLI interface for preference engine"""
    
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = str(Path.home() / ".adaptive-cli")

        self.storage = PreferenceStorageManager(str(base_dir))
        self.loader = PreferenceLoader(self.storage)
        self.processor = SignalProcessor(self.storage)
        self.strength_calc = StrengthCalculator(self.storage)
        self.tiering = TieringEngine(self.storage)
    
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
    
    def cmd_update_preference(self, args):
        """Update an existing preference's value, description, or confidence."""
        pref = self.storage.preferences.get_preference(args.pref_id)

        if not pref:
            print(f"❌ Preference not found: {args.pref_id}")
            return

        if args.value is not None:
            pref.value = args.value
        if args.description is not None:
            pref.description = args.description
        if args.confidence is not None:
            pref.confidence = args.confidence

        from datetime import datetime as _dt
        pref.last_updated = _dt.now().isoformat()
        self.storage.preferences.save_preference(pref)
        print(f"✅ Updated preference: {pref.name}")

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

        # Check if the signal was routed as a confirmation of an existing pref
        was_routed = (
            signal.type == "feedback"
            and signal.preferences_affected
            and signal.preferences_affected[0].get("action") == "confirm_strengthen"
        )

        if was_routed:
            match_info = signal.preferences_affected[0]
            pref_id = match_info["pref_id"]
            matched_pref = self.storage.preferences.get_preference(pref_id)
            pref_path = matched_pref.path if matched_pref else pref_id
            print(f"🔗 Matched to existing preference (not a new signal)")
            print(f"   Preference: {pref_path}")
            print(f"   Match type: {match_info['match_type']} ({match_info['match_similarity']:.0%} similarity)")
            print(f"   Confidence: {match_info['new_confidence']:.0%} (strengthened)")
            print(f"   Task: {args.task}")
        else:
            print(f"✅ Recorded correction signal")
            print(f"   Task: {args.task}")
            print(f"   Proposed: {args.proposed} → Corrected: {args.corrected}")
            print(f"   Emotion: {signal.emotional_tone}")
            print(f"   Associations updated: {len(signal.associations_affected)}")

            # Show what the system learned from this correction
            corrected_pref = self.storage.preferences.get_preference(args.corrected)
            if corrected_pref:
                print(f"\nWhat I learned:")
                print(f"   You prefer: {corrected_pref.path}")
                print(f"   Confidence: {corrected_pref.confidence:.0%}")

        # Update last_signal_at and recalculate tier for affected prefs
        affected_ids = [p["pref_id"] for p in signal.preferences_affected]
        now = datetime.now().isoformat()
        for pref_id in affected_ids:
            pref = self.storage.preferences.get_preference(pref_id)
            if pref:
                pref.last_signal_at = now
                old_tier = getattr(pref, 'tier', 'hot')
                new_tier = self.tiering.classify(
                    pref.confidence,
                    pref.learning.use_count,
                    getattr(pref, 'pinned', False),
                    now
                )
                if new_tier != old_tier:
                    pref.tier = new_tier
                pref.last_updated = now
                self.storage.preferences.save_preference(pref)
    
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

        # Update last_signal_at and recalculate tier for affected prefs
        affected_ids = [p["pref_id"] for p in signal.preferences_affected]
        now = datetime.now().isoformat()
        for pref_id in affected_ids:
            pref = self.storage.preferences.get_preference(pref_id)
            if pref:
                pref.last_signal_at = now
                old_tier = getattr(pref, 'tier', 'hot')
                new_tier = self.tiering.classify(
                    pref.confidence,
                    pref.learning.use_count,
                    getattr(pref, 'pinned', False),
                    now
                )
                if new_tier != old_tier:
                    pref.tier = new_tier
                pref.last_updated = now
                self.storage.preferences.save_preference(pref)
    
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
        if args.auto_detect:
            from adaptive_preference_engine.services.context_detection import detect_context
            context_tags = detect_context()
            if not context_tags:
                context_tags = args.context or ["base"]

            hot_prefs = self.loader.load_all_by_tier("hot", context_tags)
            output = {
                "context_tags": context_tags,
                "hot_preferences": hot_prefs,
                "auto_detected": True,
                "note": "Only hot-tier preferences matching detected context"
            }
            agent_json = json.dumps(output, indent=2)
        else:
            if not args.context:
                print("Error: --context required when not using --auto-detect")
                return
            agent_json = self.loader.load_for_agent(
                context_tags=args.context,
                primary_pref_id=args.primary,
                stack_contexts=args.stack
            )
            context_tags = args.context

        if args.output:
            with open(args.output, 'w') as f:
                f.write(agent_json)
            print(f"✅ Wrote agent context to {args.output}")
        else:
            last_ctx_path = Path(self.storage.base_dir) / "last_context.txt"
            last_ctx_path.write_text(" ".join(context_tags), encoding="utf-8")
            print(agent_json)

    def cmd_registry(self, args):
        """Emit a compact session-start registry (~30 tokens).

        Lists all known preference paths and top-level context nodes so
        Claude knows what to ask for on demand — without loading full
        preference trees up front.
        """
        all_prefs = self.storage.preferences.get_all_preferences()

        context_nodes: set = set()
        pref_paths: set = set()
        for p in all_prefs:
            pref_paths.add(p.path)
            if p.path.startswith("context."):
                parts = p.path.split(".")
                if len(parts) > 1:
                    context_nodes.add(parts[1])

        context_nodes = sorted(context_nodes)
        pref_paths = sorted(pref_paths)

        registry = {
            "context_nodes": context_nodes,
            "preference_paths": pref_paths,
            "hint": (
                "Call `adaptive-cli agent-context --context <tag>` before any "
                "produce/summarize/explain task to load relevant preferences."
            ),
        }
        print(json.dumps(registry, indent=2))

    def cmd_load_pref(self, args):
        result = self.loader.load_single_pref(args.path)
        if result:
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps({"error": f"No preference at path: {args.path}"}))

    def cmd_load_more(self, args):
        results = self.loader.load_by_context_tag(args.context)
        print(json.dumps(results, indent=2))

    def cmd_inventory(self, args):
        tiers = [t.strip() for t in args.tier.split(",")]
        result = self.loader.get_inventory(tiers)
        print(json.dumps(result, indent=2))
    
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
        from scripts.config import APEConfig
        cfg = APEConfig.load(str(self.storage.base_dir))

        knowledge_entries = self.storage.knowledge.get_all_entries()
        knowledge_tokens = sum(e.token_estimate for e in knowledge_entries)
        pref_tokens = info["preferences_count"] * 20
        signal_tokens = info["signals_count"] * 10

        budget_prefs = cfg.get("token_budgets.preferences", 500)
        budget_knowledge = cfg.get("token_budgets.knowledge", 3000)
        budget_total = cfg.get("token_budgets.total", 5000)

        warnings = []
        if pref_tokens > budget_prefs:
            warnings.append(f"preferences ({pref_tokens}/{budget_prefs} tokens)")
        if knowledge_tokens > budget_knowledge:
            warnings.append(f"knowledge ({knowledge_tokens}/{budget_knowledge} tokens)")
        total_tokens = pref_tokens + knowledge_tokens + signal_tokens
        if total_tokens > budget_total:
            warnings.append(f"total ({total_tokens}/{budget_total} tokens)")

        if getattr(args, 'oneline', False):
            parts = f"{info['preferences_count']}p {info['associations_count']}a {info.get('behaviors_count', 0)}b {info['signals_count']}s {info.get('knowledge_count', 0)}k"
            if warnings:
                parts += " [prune]"
            print(parts)
            return

        print(f"\nStorage Statistics")
        print(f"   DB Path:      {info['db_path']}")
        print(f"   Preferences:  {info['preferences_count']} (~{pref_tokens} tokens)")
        print(f"   Associations: {info['associations_count']}")
        print(f"   Contexts:     {info['contexts_count']}")
        print(f"   Signals:      {info['signals_count']}")
        print(f"   Knowledge:    {info.get('knowledge_count', 0)} ({knowledge_tokens} tokens)")
        print(f"   Behaviors:    {info.get('behaviors_count', 0)}")

        if warnings:
            print()
            print("Budget Warnings:")
            for w in warnings:
                print(f"  [!] Over budget: {w}")
            print("  Run `adaptive-cli prune` to review stale entries.")
        else:
            old_cfg = AdaptiveConfig(str(self.storage.base_dir))
            if not old_cfg.sync_repo_path:
                print(f"\n   Tip: sync preferences across machines with 'adaptive-cli sync configure --repo-path <path>'")
    
    def cmd_reset(self, args):
        """Reset all preferences"""
        self.storage.reset()

    def cmd_sync_configure(self, args):
        """Set the sync repo path."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        repo = Path(args.repo_path).expanduser()
        if not repo.exists():
            print(f"❌ Path does not exist: {repo}")
            print("⚠️  Create the directory or clone your preferences repo first.")
            return
        cfg.sync_repo_path = str(repo)
        print(f"✅ Sync repo set to: {repo}")
        print(f"   Use 'adaptive-cli sync push' to upload preferences.")
        print(f"   Use 'adaptive-cli sync pull' to download on another machine.")

    def cmd_sync_push(self, args):
        """Export SQLite → JSONL and push to git remote."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        if not cfg.sync_repo_path:
            print("❌ No sync repo configured.")
            print("⚠️  Run: adaptive-cli sync configure --repo-path <path>")
            return
        runner = SyncRunner(self.storage, cfg.sync_repo_path)
        result = runner.push()
        if result["status"] == "up-to-date":
            print("⚠️  Nothing to push — preferences are already up to date.")
        else:
            c = result["counts"]
            if result["status"] == "pushed":
                print("✅ Preferences pushed to sync repo.")
            else:
                print("✅ Preferences exported and committed (no remote configured).")
            print(f"   {c['preferences']} preferences, {c['associations']} associations, "
                  f"{c['contexts']} contexts, {c['signals']} signals")
            if result.get("git_push_error"):
                print(f"⚠️  git push failed: {result['git_push_error']}")

    def cmd_sync_pull(self, args):
        """Pull from git remote and import JSONL → SQLite."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        if not cfg.sync_repo_path:
            print("❌ No sync repo configured.")
            print("⚠️  Run: adaptive-cli sync configure --repo-path <path>")
            return
        runner = SyncRunner(self.storage, cfg.sync_repo_path)
        result = runner.pull()
        c = result["counts"]
        if result.get("git_pull_error"):
            print(f"❌ git pull failed: {result['git_pull_error']}")
            print("⚠️  Importing from local (possibly stale) repo state.")
            print(f"   {c['preferences']} preferences, {c['associations']} associations, "
                  f"{c['contexts']} contexts, {c['signals']} signals imported from local state")
        else:
            print("✅ Preferences pulled from sync repo.")
            print(f"   {c['preferences']} preferences, {c['associations']} associations, "
                  f"{c['contexts']} contexts, {c['signals']} signals imported/updated")

    def cmd_sync_status(self, args):
        """Show sync repo git status."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        if not cfg.sync_repo_path:
            print("⚠️  No sync repo configured.")
            print("   Run: adaptive-cli sync configure --repo-path <path>")
            return
        runner = SyncRunner(self.storage, cfg.sync_repo_path)
        print("\n🔄 Sync Status")
        print(f"   Repo: {cfg.sync_repo_path}")

        # Show unpushed preference counts
        pending = runner.pending_counts()
        status = runner.status()
        if pending:
            print(f"\n⚠️  Unpushed changes (run 'adaptive-cli sync push'):")
            for table, count in pending.items():
                print(f"   {count} {table} not yet pushed")
        else:
            total_prefs = self.storage.get_storage_info()["preferences_count"]
            if total_prefs == 0:
                print("   No preferences to sync yet.")
            elif status.strip():
                print("⚠️  Local data is up to date, but changes are not yet committed to the sync repo.")
            else:
                print("✅ All preferences are pushed and synced.")

        # Show git repo status only when pending changes exist (dirty repo not already reported above)
        if pending and status.strip():
            print(f"\n⚠️  Uncommitted changes in repo:")
            print(status)

    def cmd_onboard(self, args):
        """Run interactive onboarding tutorial."""
        onboarding = OnboardingSystem(str(self.storage.base_dir))
        if args.reset:
            onboarding.reset_all_setup()
            print(success("Onboarding reset. Run 'adaptive-cli onboard' to restart."))
            return
        if not onboarding.is_first_run():
            while True:
                print("✓ You've already completed onboarding!")
                print("  1. Review current setup")
                print("  2. Modify setup")
                print("  3. Review tutorial again")
                print("  4. Start over from scratch")
                print("  5. Exit")
                choice = input("Select an option [5]: ").strip()
                if choice == "1":
                    onboarding.show_setup_summary()
                    continue
                if choice == "2":
                    onboarding.run_modify_setup()
                    return
                if choice == "3":
                    onboarding.state.state["current_step"] = 0
                    onboarding.state._save_state()
                    onboarding.run_tutorial(skip_demo=False)
                    return
                if choice == "4":
                    onboarding.reset_all_setup()
                    onboarding.run_tutorial(skip_demo=False)
                    return
                print("Exiting onboarding.")
                break
            return
        onboarding.run_tutorial(skip_demo=False)

    def cmd_template_list(self, args):
        """List available preference templates."""
        templates = list_templates()
        print(f"\n📋 Available Templates ({len(templates)})\n")
        for t in templates:
            print(f"  {t['key']}")
            print(f"    {t['name']} — {t['description']}")
            print(f"    {t['count']} preferences")
            print()
        print("Apply a template: adaptive-cli template apply <name>")

    def cmd_template_apply(self, args):
        """Apply a built-in preference template."""
        from scripts.models import Preference, generate_id
        from datetime import datetime as _dt
        try:
            tmpl = get_template(args.template_name)
        except KeyError as e:
            print(f"❌ {e}")
            return
        created = _dt.now().isoformat()
        existing_paths = {p.path for p in self.storage.preferences.get_all_preferences()}
        count = 0
        skipped = 0
        for p in tmpl["preferences"]:
            if p["path"] in existing_paths:
                skipped += 1
                continue
            pref = Preference(
                id=generate_id("pref"),
                path=p["path"],
                parent_id=None,
                name=p["name"],
                type=p["type"],
                value=p.get("value"),
                confidence=0.7,
                description=p.get("description", ""),
                created=created,
                last_updated=created,
                auto_detected=False,
            )
            self.storage.preferences.save_preference(pref)
            count += 1
        if count == 0 and skipped > 0:
            print(f"⚠️  All preferences in this template already exist. Nothing was applied.")
        elif skipped > 0:
            print(f"✅ Applied template '{tmpl['name']}': {count} preferences created, {skipped} skipped (already exists).")
        else:
            print(f"✅ Applied template '{tmpl['name']}': {count} preferences created.")
        if count > 0:
            print("   Run 'adaptive-cli pref list' to see them.")

    # ---- Behavior Management ----

    # ---- Behavior helpers ----

    @staticmethod
    def _slugify(name: str) -> str:
        """Lowercase, replace non-alphanumeric with hyphens, strip edge hyphens."""
        return re.sub(r"[^a-z0-9\-]", "-", name.lower()).strip("-")

    @staticmethod
    def _behavior_menu(label: str, choices: list, default: str) -> str:
        """Prompt user to pick from a numbered menu; Enter accepts default."""
        print(f"\n{label}")
        for i, c in enumerate(choices, 1):
            marker = " ← default" if c == default else ""
            print(f"  {i}. {c}{marker}")
        while True:
            raw = input(f"  Select [{choices.index(default) + 1 if default in choices else ''}]: ").strip()
            if not raw:
                return default
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(choices):
                    return choices[idx]
            except ValueError:
                if raw in choices:
                    return raw
            print(f"  Enter a number 1–{len(choices)}.")

    @staticmethod
    def _behavior_ask(label: str, default: Optional[str] = None, required: bool = False) -> Optional[str]:
        """Prompt user for a string value; Enter accepts default or skips optional fields."""
        hint = (
            f" [{default}]" if default is not None
            else (" (required)" if required else " (optional, Enter to skip)")
        )
        while True:
            raw = input(f"{label}{hint}: ").strip()
            if raw:
                return raw
            if default is not None:
                return default
            if not required:
                return None
            print("  This field is required.")

    @staticmethod
    def _behavior_from_fields(fields: dict) -> "Behavior":
        """Construct a Behavior from a fields dict (wizard or flag path)."""
        return Behavior(
            id=generate_id("beh"),
            name=fields["name"],
            version=fields["version"],
            description=fields["description"],
            platform=fields["platform"],
            enabled=fields.get("enabled", True),
            hook_event=fields["hook_event"],
            hook_matcher=fields["hook_matcher"],
            artifact_path=fields["artifact_path"],
            verify_script=fields["verify_script"],
            setup_script=fields["setup_script"],
            pref_deps=fields["pref_deps"],
        )

    def _run_behavior_wizard(self) -> Optional[dict]:
        """Interactive wizard to collect all behavior fields.

        Returns a dict of fields, or None if the user aborted.
        Requires an interactive terminal — exits with an error if stdin is not a TTY.
        """
        if not sys.stdin.isatty():
            print("❌ The behavior wizard requires an interactive terminal.")
            print("   Use flags instead:  adaptive-cli behavior add --name <n> [--flags...]")
            print("   Or non-interactively: adaptive-cli behavior install <path>")
            return None

        print("\n🤖 Behavior Wizard")
        print("─" * 60)
        print("Answer each question. Enter accepts the default shown in [brackets].\n")

        name_raw = self._behavior_ask("Name", required=True)
        name = self._slugify(name_raw)
        if name != name_raw:
            print(f"  → slug: {name}")

        description = self._behavior_ask("Description")
        version = self._behavior_ask("Version", default="1.0.0")

        platform = self._behavior_menu("Platform (which VCS does this target?)", _BEHAVIOR_PLATFORMS, "any")

        hook_event_raw = self._behavior_menu("Hook event (when should this trigger?)", _BEHAVIOR_HOOK_EVENTS, "PostToolUse")
        hook_event = hook_event_raw if hook_event_raw != "none" else None

        hook_matcher = None
        if hook_event in ("PostToolUse", "PreToolUse"):
            matcher_raw = self._behavior_menu("Hook matcher (which tool triggers this?)", _BEHAVIOR_MATCHERS, "Bash")
            if matcher_raw == "other":
                hook_matcher = self._behavior_ask("  Custom matcher name", required=True)
            else:
                hook_matcher = matcher_raw

        default_artifact = str(Path.home() / ".adaptive-cli" / "behaviors" / f"{name}.sh")
        artifact_path = self._behavior_ask("Artifact path", default=default_artifact)
        if artifact_path:
            artifact_path = str(Path(artifact_path).expanduser())

        verify_parts = []
        if artifact_path:
            verify_parts.append(f"test -f {artifact_path}")
        tools_raw = self._behavior_ask("Required tools (comma-separated, e.g. 'gh,jq')")
        if tools_raw:
            for tool in [t.strip() for t in tools_raw.split(",") if t.strip()]:
                verify_parts.append(f"command -v {tool} >/dev/null 2>&1")
        auto_verify = " && ".join(verify_parts) if verify_parts else None

        verify_script = self._behavior_ask("Verify script", default=auto_verify)
        setup_script = self._behavior_ask("Setup script (run once on install)")

        pref_deps_raw = self._behavior_ask("Preference deps (comma-separated preference paths)")
        pref_deps = [p.strip() for p in pref_deps_raw.split(",") if p.strip()] if pref_deps_raw else []

        print("\n" + "─" * 60)
        print("📋 Summary")
        print(f"  Name:        {name}")
        print(f"  Version:     {version}")
        print(f"  Platform:    {platform}")
        print(f"  Description: {description or '—'}")
        hook_str = f"{hook_event}/{hook_matcher}" if hook_event and hook_matcher else (hook_event or "none")
        print(f"  Hook:        {hook_str}")
        print(f"  Artifact:    {artifact_path or '—'}")
        print(f"  Verify:      {verify_script or '—'}")
        print(f"  Setup:       {setup_script or '—'}")
        if pref_deps:
            print(f"  Pref deps:   {', '.join(pref_deps)}")

        confirm = input("\nRegister this behavior? [Y/n]: ").strip().lower()
        if confirm in ("n", "no"):
            print("Aborted.")
            return None

        return {
            "name": name,
            "version": version,
            "description": description or "",
            "platform": platform,
            "hook_event": hook_event,
            "hook_matcher": hook_matcher,
            "artifact_path": artifact_path,
            "verify_script": verify_script,
            "setup_script": setup_script,
            "pref_deps": pref_deps,
        }

    def _register_from_file(self, path: str, force: bool = False, non_interactive: bool = False) -> bool:
        """Parse APE header from file and register or update the behavior in DB.

        Returns True on success, False on abort or error.
        When not interactive (non_interactive=True or stdin is not a TTY) and a
        version change is detected, requires force=True to proceed.
        """
        is_tty = sys.stdin.isatty() and not non_interactive

        try:
            fields = parse_ape_header(path)
        except (ValueError, FileNotFoundError) as e:
            print(f"❌ {e}")
            return False

        # Store path as-given (expanduser but not resolve — preserves portability)
        fields["artifact_path"] = str(Path(path).expanduser())

        existing = self.storage.behaviors.get_behavior_by_name(fields["name"])

        if existing:
            if existing.artifact_path and existing.artifact_path != fields["artifact_path"]:
                print(f"⚠️  Warning: artifact path is changing.")
                print(f"   Was: {existing.artifact_path}")
                print(f"   Now: {fields['artifact_path']}")

            changed = []
            for k in ("version", "description", "platform", "hook_event", "hook_matcher",
                      "enabled", "verify_script", "setup_script", "artifact_path"):
                old = getattr(existing, k)
                new = fields.get(k)
                if old != new:
                    changed.append((k, old, new))
            # pref_deps is a list — compare as sets to avoid order-dependent false positives
            if set(existing.pref_deps) != set(fields["pref_deps"]):
                changed.append(("pref_deps", existing.pref_deps, fields["pref_deps"]))

            if not changed and not force:
                print(f"ℹ️  {fields['name']} v{fields['version']} is already up to date.")
                return True

            print(f"🔄 Updating behavior: {fields['name']}")
            if changed:
                print("   Changed fields:")
                for k, old, new in changed:
                    print(f"     {k}: {old!r} → {new!r}")

            version_changed = any(k == "version" for k, _, _ in changed)
            if version_changed and not force:
                if not is_tty:
                    print(f"❌ Version change detected but not running interactively.")
                    print(f"   Use --force to apply without confirmation.")
                    return False
                confirm = input(f"  Apply update? [Y/n]: ").strip().lower()
                if confirm in ("n", "no"):
                    print("Aborted.")
                    return False

            for k, _, new in changed:
                setattr(existing, k, new)
            existing.last_updated = datetime.now().isoformat()
            self.storage.behaviors.save_behavior(existing)
            print(f"✅ Updated: {existing.name}  v{existing.version}")
        else:
            b = self._behavior_from_fields(fields)
            self.storage.behaviors.save_behavior(b)
            print(f"✅ Registered: {b.name}  v{b.version}")

        if fields.get("setup_script"):
            print(f"   Run 'adaptive-cli behavior setup {fields['name']}' to run setup.")
        return True

    def cmd_behavior_list(self, args):
        """List all installed behaviors."""
        behaviors = self.storage.behaviors.get_all_behaviors()
        if not behaviors:
            print("No behaviors installed.")
            return
        print(f"\n🤖 Behaviors ({len(behaviors)} total)")
        print("─" * 80)
        for b in behaviors:
            status = "✓" if b.enabled else "○"
            hook = f" [{b.hook_event}/{b.hook_matcher}]" if b.hook_event else ""
            print(f"{status} {b.name}  v{b.version}  ({b.platform}){hook}")
            if b.description:
                print(f"   {b.description}")

    def cmd_behavior_show(self, args):
        """Show full details of a named behavior."""
        b = self.storage.behaviors.get_behavior_by_name(args.name)
        if not b:
            print(f"❌ Behavior not found: {args.name}")
            return
        print(f"\n🤖 Behavior: {b.name}")
        print(f"   ID: {b.id}")
        print(f"   Version: {b.version}")
        print(f"   Platform: {b.platform}")
        print(f"   Enabled: {b.enabled}")
        print(f"   Hook: {b.hook_event}/{b.hook_matcher}" if b.hook_event else "   Hook: none")
        if b.artifact_path:
            print(f"   Artifact: {b.artifact_path}")
        if b.description:
            print(f"   Description: {b.description}")
        if b.behavior_deps:
            print(f"   Behavior deps: {', '.join(b.behavior_deps)}")
        if b.pref_deps:
            print(f"   Pref deps: {', '.join(b.pref_deps)}")
        print(f"   Installed: {b.installed_at[:10]}")

    def cmd_behavior_add(self, args):
        # Wizard fires only when invoked with bare 'behavior add' (no flags at all).
        # If any flag is provided without --name, give an actionable error.
        has_any_flag = any([
            args.version is not None,
            args.description,
            args.platform is not None,
            args.hook_event,
            args.hook_matcher,
            args.artifact_path,
            args.verify_script,
            args.setup_script,
            args.pref_dep,
        ])

        if not args.name and has_any_flag:
            print("❌ --name is required when using flags.")
            print("   Run 'adaptive-cli behavior add' with no arguments to use the interactive wizard.")
            return

        if not args.name:
            fields = self._run_behavior_wizard()
            if not fields:
                return
        else:
            fields = {
                "name": self._slugify(args.name),
                "version": args.version or "1.0.0",
                "description": args.description or "",
                "platform": args.platform or "any",
                "hook_event": args.hook_event,
                "hook_matcher": args.hook_matcher,
                "artifact_path": str(Path(args.artifact_path).expanduser()) if args.artifact_path else None,
                "verify_script": args.verify_script,
                "setup_script": args.setup_script,
                "pref_deps": args.pref_dep or [],
            }
            if fields["name"] != args.name:
                print(f"  → name slug: {fields['name']}")

        existing = self.storage.behaviors.get_behavior_by_name(fields["name"])
        if existing:
            print(f"❌ Behavior already exists: {fields['name']}")
            print(f"   To update it, edit its artifact file and run:")
            print(f"   adaptive-cli behavior install <path>")
            print(f"   Or use: adaptive-cli behavior update {fields['name']}")
            return

        b = self._behavior_from_fields(fields)
        self.storage.behaviors.save_behavior(b)
        print(f"✅ Registered behavior: {b.name}  v{b.version}")
        if b.setup_script:
            print(f"   Run 'adaptive-cli behavior setup {b.name}' to run setup.")

    def cmd_behavior_create(self, args):
        import os, subprocess
        if not sys.stdin.isatty():
            print("❌ 'behavior create' requires an interactive terminal.")
            print("   Write the artifact file manually, then run:")
            print("   adaptive-cli behavior install <path>")
            return

        print("\n🤖 Behavior Creator")
        print("─" * 60)
        print("This wizard scaffolds a new behavior script with the APE header.")
        print("After creation, edit the script to add your logic, then install it.\n")

        name_raw = self._behavior_ask("Name", required=True)
        name = self._slugify(name_raw)
        if name != name_raw:
            print(f"  → slug: {name}")

        description = self._behavior_ask("Description")
        version = self._behavior_ask("Version", default="1.0.0")
        platform = self._behavior_menu("Platform", _BEHAVIOR_PLATFORMS, "any")
        hook_event_raw = self._behavior_menu("Hook event", _BEHAVIOR_HOOK_EVENTS, "PostToolUse")
        hook_event = hook_event_raw if hook_event_raw != "none" else None
        hook_matcher = None
        if hook_event in ("PostToolUse", "PreToolUse"):
            matcher_raw = self._behavior_menu("Hook matcher", _BEHAVIOR_MATCHERS, "Bash")
            hook_matcher = (
                self._behavior_ask("  Custom matcher", required=True)
                if matcher_raw == "other" else matcher_raw
            )

        default_artifact = str(Path.home() / ".adaptive-cli" / "behaviors" / f"{name}.sh")
        artifact_path_raw = self._behavior_ask("Artifact path", default=default_artifact)
        artifact_path = Path(artifact_path_raw).expanduser() if artifact_path_raw else Path(default_artifact).expanduser()

        verify_parts = [f"test -f {artifact_path}"]
        tools_raw = self._behavior_ask("Required tools (comma-separated, e.g. 'gh,jq')")
        if tools_raw:
            for tool in [t.strip() for t in tools_raw.split(",") if t.strip()]:
                verify_parts.append(f"command -v {tool} >/dev/null 2>&1")
        auto_verify = self._behavior_ask("Verify script", default=" && ".join(verify_parts))
        setup_script = self._behavior_ask("Setup script (run once on install)")
        pref_deps_raw = self._behavior_ask("Preference deps (comma-separated)")
        pref_deps = [p.strip() for p in pref_deps_raw.split(",") if p.strip()] if pref_deps_raw else []

        # Check existence before writing
        if artifact_path.exists() and not getattr(args, "force", False):
            print(f"\n❌ File already exists: {artifact_path}")
            print(f"   Use --force to overwrite, or install an existing APE-annotated file:")
            print(f"   adaptive-cli behavior install {artifact_path}")
            return

        # Write scaffold
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        hook_event_val = hook_event or "none"
        hook_matcher_val = hook_matcher or "none"
        lines = [
            "#!/bin/bash",
            f"# APE-BEHAVIOR: {name}",
            f"# APE-VERSION: {version}",
            f"# APE-PLATFORM: {platform}",
            f"# APE-HOOK-EVENT: {hook_event_val}",
            f"# APE-HOOK-MATCHER: {hook_matcher_val}",
            "# APE-STATUS: enabled",
            f"# APE-DESCRIPTION: {description or ''}",
        ]
        if auto_verify:
            lines.append(f"# APE-VERIFY: {auto_verify}")
        if setup_script:
            lines.append(f"# APE-SETUP: {setup_script}")
        for pd in pref_deps:
            lines.append(f"# APE-PREF-DEP: {pd}")
        lines += [
            "#",
            "# ── Versioning convention (MAJOR.MINOR.PATCH) ───────────────────────",
            "# MAJOR: breaking contract change (hook event, stdin format, what it modifies)",
            "# MINOR: new capability, backward-compatible",
            "# PATCH: bug fixes, behavior edits, internal tweaks",
            "#",
            "# ── Implementation ──────────────────────────────────────────────────",
            "# stdin (JSON) available on PostToolUse/PreToolUse hooks.",
            "# Exit 0 = silent success.",
            "# Exit 2 + JSON {hookSpecificOutput:{hookEventName:...,additionalContext:...}}",
            "#   = wake Claude with context.",
            "",
        ]
        artifact_path.write_text("\n".join(lines), encoding="utf-8")
        artifact_path.chmod(0o755)

        print(f"\n✅ Scaffold created: {artifact_path}")
        print(f"\nNext steps:")
        print(f"  1. Edit the script to add your logic")
        print(f"  2. Install it: adaptive-cli behavior install {artifact_path}")

        editor = os.environ.get("EDITOR")
        if editor:
            open_it = input(f"\nOpen in {editor} now? [Y/n]: ").strip().lower()
            if open_it not in ("n", "no"):
                result = subprocess.run([editor, str(artifact_path)])
                if result.returncode == 0:
                    install_it = input(f"\nInstall now? [Y/n]: ").strip().lower()
                    if install_it not in ("n", "no"):
                        self._register_from_file(str(artifact_path), force=False)

    # ---- Tier Management ----

    def cmd_tier_list(self, args):
        """List all preferences grouped by tier"""
        all_prefs = self.storage.preferences.get_all_preferences()
        if not all_prefs:
            print("No preferences found.")
            return

        by_tier = {"hot": [], "warm": [], "cold": []}
        for pref in all_prefs:
            tier = getattr(pref, 'tier', 'hot')
            by_tier[tier].append(pref)

        print(f"\n🔥 Preference Tiers")
        print("─" * 80)

        for tier_name in ["hot", "warm", "cold"]:
            prefs = by_tier[tier_name]
            print(f"\n{tier_name.capitalize()} ({len(prefs)}):")
            if not prefs:
                print("   (none)")
            else:
                for pref in sorted(prefs, key=lambda p: p.confidence, reverse=True):
                    pinned_flag = " (pinned)" if getattr(pref, 'pinned', False) else ""
                    print(f"  * {pref.path} ({pref.confidence:.0%}{pinned_flag})")

    def cmd_tier_recalculate(self, args):
        """Recalculate tiers for all preferences"""
        results = self.tiering.recalculate()
        print(f"✅ Recalculated tiers")
        print(f"   Promoted: {len(results['promoted'])}")
        print(f"   Demoted: {len(results['demoted'])}")
        print(f"   Unchanged: {len(results['unchanged'])}")

    def cmd_tier_backfill(self, args):
        """Backfill tier classification for existing preferences"""
        results = self.tiering.backfill()
        print(f"✅ Backfilled tiers")
        print(f"   Promoted: {len(results['promoted'])}")
        print(f"   Demoted: {len(results['demoted'])}")
        print(f"   Unchanged: {len(results['unchanged'])}")

    def cmd_tier_pin(self, args):
        """Pin a preference to hot tier"""
        prefs = self.storage.preferences.get_preferences_by_path(args.path)
        if not prefs:
            print(f"❌ No preference found at path: {args.path}")
            return
        pref = prefs[0]
        if self.tiering.pin(pref.id):
            print(f"✅ Pinned to hot: {pref.path}")
        else:
            print(f"⚠️  Already pinned: {pref.path}")

    def cmd_tier_unpin(self, args):
        """Unpin a preference"""
        prefs = self.storage.preferences.get_preferences_by_path(args.path)
        if not prefs:
            print(f"❌ No preference found at path: {args.path}")
            return
        pref = prefs[0]
        if self.tiering.unpin(pref.id):
            print(f"✅ Unpinned: {pref.path}")
        else:
            print(f"⚠️  Not pinned: {pref.path}")

    def cmd_tier_summary(self, args):
        """Show tier distribution summary"""
        summary = self.tiering.get_tier_summary()
        total = sum(summary.values())
        print(f"\n📊 Tier Summary ({total} preferences)")
        print("─" * 80)
        for tier in ["hot", "warm", "cold"]:
            count = summary[tier]
            pct = (count / total * 100) if total > 0 else 0
            print(f"  {tier.capitalize()}: {count} ({pct:.0f}%)")

    def cmd_behavior_install(self, args):
        """Install a behavior from an APE-annotated artifact file."""
        self._register_from_file(args.path, force=args.force, non_interactive=args.non_interactive)

    def cmd_behavior_update(self, args):
        """Re-read a behavior's artifact and update its DB record."""
        b = self.storage.behaviors.get_behavior_by_name(args.name)
        if not b:
            print(f"❌ Behavior not found: {args.name}")
            print(f"   List installed behaviors: adaptive-cli behavior list")
            return
        if not b.artifact_path:
            print(f"❌ Behavior '{args.name}' has no artifact_path on record.")
            print(f"   Use: adaptive-cli behavior install <path>")
            return
        p = Path(b.artifact_path).expanduser()
        if not p.exists():
            print(f"❌ Artifact file not found: {p}")
            print(f"   The file may have moved. Use: adaptive-cli behavior install <new-path>")
            return
        self._register_from_file(str(p), force=args.force, non_interactive=args.non_interactive)

    def cmd_behavior_toggle(self, args):
        """Enable or disable a behavior."""
        b = self.storage.behaviors.get_behavior_by_name(args.name)
        if not b:
            print(f"❌ Behavior not found: {args.name}")
            return
        b.enabled = args.enable
        # Only scalar field changed — skip junction table rewrite
        self.storage.behaviors.save_behavior(b, update_deps=False)
        state = "enabled" if args.enable else "disabled"
        print(f"✅ Behavior {b.name} {state}.")

    def cmd_behavior_remove(self, args):
        """Remove a behavior from the DB."""
        b = self.storage.behaviors.get_behavior_by_name(args.name)
        if not b:
            print(f"❌ Behavior not found: {args.name}")
            return
        self.storage.behaviors.delete_behavior(b.id)
        print(f"✅ Removed behavior: {b.name}")
        if b.artifact_path:
            print(f"   Artifact at: {b.artifact_path}")
            print(f"   Delete manually if no longer needed.")

    def cmd_behavior_verify(self, args):
        """Run verify_script for each enabled behavior (or the named one)."""
        import subprocess
        import shlex
        if args.name:
            b = self.storage.behaviors.get_behavior_by_name(args.name)
            if not b:
                print(f"❌ Behavior not found: {args.name}")
                return
            behaviors = [b]
        else:
            behaviors = self.storage.behaviors.get_enabled_behaviors()
        if not behaviors:
            print("No behaviors to verify.")
            return
        all_ok = True
        for b in behaviors:
            # Baseline: artifact path must exist if set
            if b.artifact_path:
                p = Path(b.artifact_path).expanduser()
                if not p.exists():
                    print(f"  ✗ {b.name}: artifact file missing: {p}")
                    all_ok = False
                    continue
            if not b.verify_script:
                print(f"  ○ {b.name}: no verify script (artifact present)")
                continue
            result = subprocess.run(shlex.split(b.verify_script), shell=False, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✓ {b.name}: ok")
            else:
                print(f"  ✗ {b.name}: FAILED")
                if result.stdout.strip():
                    print(f"    stdout: {result.stdout.strip()[:200]}")
                if result.stderr.strip():
                    print(f"    stderr: {result.stderr.strip()[:200]}")
                all_ok = False
        if not all_ok:
            import sys; sys.exit(1)

    # ---- Buddy Management ----

    def cmd_buddy_install(self, args):
        """Copy the ape-buddy agent definition to ~/.claude/agents/ and ~/.adaptive-cli/agents/."""
        import shutil
        agent_src = Path(__file__).parent.parent / "agents" / "ape-buddy.md"
        if not agent_src.exists():
            print(f"❌ Agent file not found: {agent_src}")
            print("   Re-clone the APE repo or run: git pull")
            return

        local_agents = Path(self.storage.base_dir) / "agents"
        claude_agents = Path.home() / ".claude" / "agents"
        local_agents.mkdir(parents=True, exist_ok=True)
        claude_agents.mkdir(parents=True, exist_ok=True)

        shutil.copy2(agent_src, local_agents / "ape-buddy.md")
        shutil.copy2(agent_src, claude_agents / "ape-buddy.md")
        print(f"✅ Installed: ~/.claude/agents/ape-buddy.md")
        print(f"   Enable with: adaptive-cli buddy enable")

    def cmd_buddy_enable(self, args):
        """Enable the buddy — APE operations will be delegated to the ape-buddy agent."""
        installed = (Path.home() / ".claude" / "agents" / "ape-buddy.md").exists()
        if not installed:
            print("⚠️  ape-buddy is not installed yet.")
            print("   Run: adaptive-cli buddy install")
            return
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        cfg.buddy_enabled = True
        print("✅ APE buddy enabled — active from next session start.")

    def cmd_buddy_disable(self, args):
        """Disable the buddy — APE operations revert to direct CLI calls."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        cfg.buddy_enabled = False
        print("✅ APE buddy disabled.")

    def cmd_buddy_status(self, args):
        """Show buddy install and enable state."""
        cfg = AdaptiveConfig(str(self.storage.base_dir))
        installed = (Path.home() / ".claude" / "agents" / "ape-buddy.md").exists()
        state = "enabled" if cfg.buddy_enabled else "disabled"
        print(f"Buddy: {state}")
        print(f"Installed: {'yes  (~/.claude/agents/ape-buddy.md)' if installed else 'no'}")
        if not installed:
            print("  Run: adaptive-cli buddy install")
        elif not cfg.buddy_enabled:
            print("  Run: adaptive-cli buddy enable")

    # ---- Knowledge Management ----

    def cmd_knowledge_add(self, args):
        import socket
        from adaptive_preference_engine.knowledge import KnowledgeEntry

        # Validate expires_when_tag if provided
        if args.expires_when_tag:
            from scripts.tag_validation import validate_tag
            if not validate_tag(args.expires_when_tag):
                print(f"ERROR: Invalid tag '{args.expires_when_tag}'. "
                      "Tags must match [a-zA-Z0-9][a-zA-Z0-9.-]* "
                      "(no underscores or percent signs).", file=sys.stderr)
                return

        entry = KnowledgeEntry(
            id=generate_id("know"),
            partition=args.partition,
            category=args.category,
            title=args.title,
            tags=args.tags,
            content=args.content,
            confidence=args.confidence,
            source="explicit",
            machine_origin=socket.gethostname(),
            decay_exempt=args.decay_exempt,
            token_estimate=len(args.content) // 4,
            expires_at=getattr(args, 'expires_at', None),
            expires_when=getattr(args, 'expires_when', None),
            expires_when_tag=getattr(args, 'expires_when_tag', None),
        )
        self.storage.knowledge.save_entry(entry)
        print(f"Added: [{entry.partition}] {entry.title} ({entry.id})")

        # Trigger compaction check
        try:
            from scripts.compaction import CompactionEngine
            engine = CompactionEngine(self.storage)
            compacted = engine.check_and_compact()
            for p in compacted:
                print(f"  Compacted: {p}")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning(f"Compaction check failed: {exc}")

    def cmd_knowledge_search(self, args):
        all_entries = self.storage.knowledge.get_all_entries()
        query = args.query.lower()
        results = [e for e in all_entries
                   if query in e.title.lower()
                   or query in e.content.lower()
                   or any(query in t.lower() for t in e.tags)]
        if args.partition:
            results = [r for r in results if r.partition == args.partition]
        if args.category:
            results = [r for r in results if r.category == args.category]
        if not results:
            print(f"No results for '{args.query}'")
            return
        print(f"Search: \"{args.query}\" ({len(results)} results)")
        print("-" * 60)
        for i, r in enumerate(results, 1):
            tags_str = ", ".join(r.tags) if r.tags else ""
            print(f"  {i}. [{r.partition}] {r.title}")
            print(f"     Tags: {tags_str} | {r.token_estimate} tokens | Confidence: {r.confidence}")

    def cmd_knowledge_show(self, args):
        entry = self.storage.knowledge.get_entry(args.identifier)
        if not entry:
            all_entries = self.storage.knowledge.get_all_entries(include_archived=True)
            matches = [e for e in all_entries if args.identifier.lower() in e.title.lower()]
            entry = matches[0] if matches else None
        if not entry:
            print(f"Not found: {args.identifier}")
            return
        self.storage.knowledge.record_access(entry.id)
        entry = self.storage.knowledge.get_entry(entry.id)
        tags_str = ", ".join(entry.tags)
        print(f"-- {entry.title} " + "-" * max(0, 50 - len(entry.title)))
        print(f"  ID:         {entry.id}")
        print(f"  Partition:  {entry.partition}")
        print(f"  Category:   {entry.category}")
        print(f"  Confidence: {entry.confidence}")
        print(f"  Source:     {entry.source}")
        print(f"  Created:    {entry.created_at[:10]}")
        print(f"  Last used:  {entry.last_used[:10]} (accessed {entry.access_count} times)")
        print(f"  Tags:       {tags_str}")
        if entry.machine_origin:
            print(f"  Machine:    {entry.machine_origin}")
        print(f"  Tokens:     {entry.token_estimate}")
        print(f"  Archived:   {entry.archived}")
        if entry.ref_path:
            print(f"  Ref Path:   {entry.ref_path}")
            try:
                from scripts.compaction import CompactionEngine
                engine = CompactionEngine(self.storage)
                full = engine.read_ref_content(entry)
                if full:
                    print("-" * 60)
                    print(f"\n  --- Full content (loaded from {entry.ref_path}) ---\n")
                    print(full)
                else:
                    print("-" * 60)
                    print()
                    print(f"  WARNING: Ref file not found at {entry.ref_path}")
                    print(f"\n  --- Fallback to inline content ---\n")
                    print(entry.content)
            except Exception:
                print("-" * 60)
                print()
                print(entry.content)
        else:
            print("-" * 60)
            print()
            print(entry.content)

    def cmd_knowledge_list(self, args):
        include_archived = getattr(args, "include_archived", False)
        entries = self.storage.knowledge.get_all_entries(include_archived=include_archived)
        if args.partition:
            entries = [e for e in entries if e.partition == args.partition]
        if args.category:
            entries = [e for e in entries if e.category == args.category]
        if not entries:
            print("No knowledge entries found.")
            return
        by_partition = {}
        for e in entries:
            by_partition.setdefault(e.partition, []).append(e)
        total_tokens = sum(e.token_estimate for e in entries)
        print(f"Knowledge Store: {len(entries)} entries ({total_tokens} tokens)")
        print("-" * 60)
        for partition in sorted(by_partition.keys()):
            items = by_partition[partition]
            ptokens = sum(e.token_estimate for e in items)
            print(f"  {partition}/  ({len(items)} entries, {ptokens} tokens)")
            for e in items:
                flag = " [archived]" if e.archived else ""
                ref_flag = " [ref]" if e.ref_path else ""
                print(f"    - {e.title} ({e.token_estimate}t, {e.category}){flag}{ref_flag}")

    def cmd_knowledge_archive(self, args):
        entry = self.storage.knowledge.get_entry(args.identifier)
        if not entry:
            all_entries = self.storage.knowledge.get_all_entries()
            matches = [e for e in all_entries if args.identifier.lower() in e.title.lower()]
            entry = matches[0] if matches else None
        if not entry:
            print(f"Not found: {args.identifier}")
            return
        self.storage.knowledge.archive_entry(entry.id)
        print(f"Archived: [{entry.partition}] {entry.title}")

    def cmd_knowledge_restore(self, args):
        self.storage.knowledge.unarchive_entry(args.entry_id)
        print(f"Restored: {args.entry_id}")

    def cmd_knowledge_prune(self, args):
        from scripts.config import APEConfig
        cfg = APEConfig.load(str(self.storage.base_dir))
        entries = self.storage.knowledge.get_all_entries()
        now = datetime.now()
        candidates = []
        for e in entries:
            if e.decay_exempt:
                continue
            threshold_days = cfg.get(f"pruning.{e.category}", 180)
            try:
                last = datetime.fromisoformat(e.last_used)
                age_days = (now - last).days
            except (ValueError, TypeError):
                age_days = 0
            if age_days > threshold_days:
                candidates.append((e, age_days, threshold_days))
        if not candidates:
            print("No stale entries found.")
            return
        total_tokens = sum(e.token_estimate for e, _, _ in candidates)
        print(f"Prune Candidates ({len(candidates)} entries, {total_tokens} tokens):")
        print("-" * 60)
        for i, (e, age, thresh) in enumerate(candidates, 1):
            print(f"  {i}. [{e.partition}] {e.title} (unused {age}d, threshold {int(thresh)}d)")
        if args.dry_run:
            print("\n(dry run - no changes made)")
            return
        for e, _, _ in candidates:
            self.storage.knowledge.archive_entry(e.id)
        print(f"Archived {len(candidates)} entries.")

    def cmd_behavior_setup(self, args):
        """Run setup_script for each behavior (or the named one)."""
        import subprocess
        import shlex
        if args.name:
            b = self.storage.behaviors.get_behavior_by_name(args.name)
            if not b:
                print(f"❌ Behavior not found: {args.name}")
                return
            behaviors = [b]
        else:
            behaviors = self.storage.behaviors.get_all_behaviors()
        if not behaviors:
            print("No behaviors to set up.")
            return
        for b in behaviors:
            if not b.setup_script:
                print(f"  ○ {b.name}: no setup script")
                continue
            print(f"  ⚙ {b.name}: setup script: {b.setup_script}")
            confirm = input("    Run this script? [y/N] ").strip().lower()
            if confirm != "y":
                print(f"  ○ {b.name}: skipped")
                continue
            print(f"  ⚙ {b.name}: running setup...")
            result = subprocess.run(shlex.split(b.setup_script), shell=False, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✓ {b.name}: setup complete")
            else:
                print(f"  ✗ {b.name}: setup FAILED (exit {result.returncode})")
                if result.stderr.strip():
                    print(f"    {result.stderr.strip()[:300]}")


def main():
    parser = argparse.ArgumentParser(
        description="Adaptive Preference Engine - Phase 1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
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

  # Set up cross-machine sync
  adaptive-cli sync configure --repo-path ~/repos/my-prefs-repo

  # Push preferences to sync repo
  adaptive-cli sync push

  # Pull preferences on another machine
  adaptive-cli sync pull

  # Browse and apply built-in preference templates
  adaptive-cli template list
  adaptive-cli template apply python-developer
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

    update_pref = pref_sub.add_parser("update", help="Update a preference")
    update_pref.add_argument("pref_id", help="Preference ID to update")
    update_pref.add_argument("--value", default=None, help="New value")
    update_pref.add_argument("--description", default=None, help="New description")
    update_pref.add_argument("--confidence", type=float, default=None, help="New confidence (0.0-1.0)")

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
    agent_parser.add_argument("--context", nargs="+", default=None)
    agent_parser.add_argument("--primary", default=None)
    agent_parser.add_argument("--stack", nargs="+", default=None)
    agent_parser.add_argument("--output", default=None)
    agent_parser.add_argument("--auto-detect", action="store_true", help="Auto-detect context from cwd")

    # Registry (compact session-start payload)
    subparsers.add_parser("registry", help="Emit compact preference registry for session start")

    # Demand loading commands
    load_pref_parser = subparsers.add_parser("load-pref", help="Load a single preference by path")
    load_pref_parser.add_argument("--path", required=True, help="Preference path")

    load_more_parser = subparsers.add_parser("load-more", help="Load preferences matching a context tag")
    load_more_parser.add_argument("--context", required=True, help="Context tag to match")

    inventory_parser = subparsers.add_parser("inventory", help="Show available warm/cold preferences")
    inventory_parser.add_argument("--tier", default="warm,cold", help="Comma-separated tiers to show")
    
    # Maintenance commands
    stats_parser = subparsers.add_parser("stats", help="Show statistics")
    stats_parser.add_argument("--oneline", action="store_true", help="Compact single-line output for statusline")

    recalc_parser = subparsers.add_parser("recalculate", help="Recalculate strengths")
    recalc_parser.add_argument("--details", action="store_true")
    
    decay_parser = subparsers.add_parser("decay", help="Apply time decay")
    decay_parser.add_argument("--details", action="store_true")
    
    reset_parser = subparsers.add_parser("reset", help="Reset all preferences")

    # sync
    sync_parser = subparsers.add_parser("sync", help="Sync preferences with a git repo")
    sync_sub = sync_parser.add_subparsers(dest="sync_subcommand")

    sync_cfg = sync_sub.add_parser("configure", help="Set the sync repo path")
    sync_cfg.add_argument("--repo-path", required=True,
                          help="Path to the git repo directory containing JSONL exports")

    sync_sub.add_parser("push", help="Export to JSONL and push to remote")
    sync_sub.add_parser("pull", help="Pull from remote and import into local SQLite")
    sync_sub.add_parser("status", help="Show sync repo git status")

    # onboard
    onboard_parser = subparsers.add_parser("onboard", help="Interactive setup tutorial")
    onboard_parser.add_argument("--reset", action="store_true", help="Reset and restart tutorial")

    # template
    template_parser = subparsers.add_parser("template", help="Apply built-in preference templates")
    template_sub = template_parser.add_subparsers(dest="template_subcommand")
    template_sub.add_parser("list", help="List available templates")
    template_apply = template_sub.add_parser("apply", help="Apply a template by name")
    template_apply.add_argument("template_name", help="Template name (see: adaptive-cli template list)")

    # behavior
    behavior_parser = subparsers.add_parser(
        "behavior",
        help="Manage automation behaviors",
        description=(
            "Behaviors are named, versioned automation units — scripts that run on hooks,\n"
            "respond to CI events, or automate repetitive workflows.\n\n"
            "Subcommand quick reference:\n"
            "  add       Interactive wizard (no args) or flag-based registration\n"
            "  create    Scaffold a new behavior script with APE header, then edit it\n"
            "  install   Register from an existing APE-annotated script file\n"
            "  update    Re-read a behavior's script and sync its DB record\n"
            "  list      Show all installed behaviors\n"
            "  show      Show full details of one behavior\n"
            "  toggle    Enable or disable without removing\n"
            "  verify    Run verify scripts and check artifact existence\n"
            "  setup     Run one-time setup scripts\n"
            "  remove    Remove a behavior from the DB\n\n"
            "Typical workflow:\n"
            "  1. adaptive-cli behavior create        (scaffold + edit)\n"
            "  2. adaptive-cli behavior install <path> (register)\n"
            "  3. adaptive-cli behavior verify         (confirm healthy)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    behavior_sub = behavior_parser.add_subparsers(dest="behavior_subcommand")

    behavior_sub.add_parser(
        "list",
        help="List all installed behaviors",
        description="Show all installed behaviors with their status, version, platform, and hook binding.",
    )

    beh_show = behavior_sub.add_parser(
        "show",
        help="Show full details of one behavior",
        description="Display all fields of a behavior including dependencies, artifact path, and scripts.",
    )
    beh_show.add_argument("name", help="Behavior name")

    beh_add = behavior_sub.add_parser(
        "add",
        help="Define and register a behavior (wizard or flags)",
        description=(
            "Register a behavior in the APE database.\n\n"
            "Run with NO arguments to launch the interactive wizard — it walks you\n"
            "through every field with prompts and smart defaults.\n\n"
            "Run with --name and optional flags to skip the wizard entirely.\n"
            "If you supply any flags without --name, the command fails with a hint.\n\n"
            "Use 'behavior add' when:\n"
            "  - You want a guided setup\n"
            "  - The behavior script already exists and you just want to catalog it\n"
            "  - You're registering a behavior without a file (e.g. a conceptual preference)\n\n"
            "Use 'behavior install <path>' instead when the script has APE headers —\n"
            "it reads all fields from the file automatically.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior add                     # launch wizard\n"
            "  adaptive-cli behavior add --name pr-monitor --platform github --hook-event PostToolUse --hook-matcher Bash"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_add.add_argument("--name", default=None, help="Behavior name (slug: lowercase, hyphens)")
    beh_add.add_argument("--version", default=None, help="Version string (default: 1.0.0)")
    beh_add.add_argument("--description", default=None, help="Human-readable description")
    beh_add.add_argument("--platform", default=None,
                         choices=["any", "github", "gitlab", "bitbucket", "azure-devops", "gitea"],
                         help="Target VCS platform (default: any)")
    beh_add.add_argument("--hook-event", default=None, dest="hook_event",
                         help="Claude Code hook event: PostToolUse, PreToolUse, SessionStart, Stop")
    beh_add.add_argument("--hook-matcher", default=None, dest="hook_matcher",
                         help="Tool name to match in hook event (e.g. Bash, Write)")
    beh_add.add_argument("--artifact-path", default=None, dest="artifact_path",
                         help="Path to the script file that implements this behavior")
    beh_add.add_argument("--verify-script", default=None, dest="verify_script",
                         help="Shell command to verify prerequisites (e.g. 'command -v gh >/dev/null 2>&1')")
    beh_add.add_argument("--setup-script", default=None, dest="setup_script",
                         help="Shell command to run once on install")
    beh_add.add_argument("--pref-dep", action="append", default=None, dest="pref_dep",
                         help="Preference path this behavior depends on (repeatable)")

    beh_create = behavior_sub.add_parser(
        "create",
        help="Scaffold a new behavior script with APE header",
        description=(
            "Interactive wizard that scaffolds a new behavior script at the path you\n"
            "specify (default: ~/.adaptive-cli/behaviors/<name>.sh).\n\n"
            "The script is pre-populated with APE header comments that describe the\n"
            "behavior's metadata. Edit the script to add your implementation, then\n"
            "install it with 'behavior install <path>'.\n\n"
            "Use 'behavior create' when:\n"
            "  - You want to write a new behavior from scratch\n"
            "  - You want the APE header format pre-filled for you\n\n"
            "Use 'behavior add' instead if the script already exists or you don't\n"
            "need a file (you're just cataloging a preference, not a script).\n\n"
            "This command does NOT register the behavior in the DB. Run\n"
            "'behavior install <path>' after editing to do that.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior create\n"
            "  adaptive-cli behavior create --force   # overwrite existing scaffold"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_create.add_argument("--force", action="store_true",
                            help="Overwrite an existing artifact file at the target path")

    beh_install = behavior_sub.add_parser(
        "install",
        help="Register a behavior from an APE-annotated script file",
        description=(
            "Parse the APE-* header comments in a script file and register or\n"
            "update the behavior in the APE database.\n\n"
            "The script must contain at minimum:\n"
            "  # APE-BEHAVIOR: <name>\n"
            "  # APE-VERSION: <version>\n\n"
            "These can appear anywhere in the comment block (lines starting with '#').\n"
            "See 'behavior create' for the full header format.\n\n"
            "Use 'behavior install' when:\n"
            "  - You wrote or received a behavior script with APE headers\n"
            "  - You ran 'behavior create' and finished editing the script\n"
            "  - You moved a script from another machine and want to re-register it\n\n"
            "Use 'behavior update <name>' instead if the behavior is already registered\n"
            "and you just want to sync after editing.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior install ~/.claude/pr-monitor.sh\n"
            "  adaptive-cli behavior install ./my-behavior.sh --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_install.add_argument("path", help="Path to the APE-annotated script file")
    beh_install.add_argument("--force", action="store_true",
                             help="Apply update without version-change confirmation prompt")
    beh_install.add_argument("--non-interactive", action="store_true", dest="non_interactive",
                             help="Fail instead of prompting if confirmation is needed (for scripts/CI)")

    beh_update = behavior_sub.add_parser(
        "update",
        help="Re-read a behavior's artifact file and sync its DB record",
        description=(
            "Re-reads the APE header from the behavior's registered artifact file\n"
            "and updates the DB record to match.\n\n"
            "Use 'behavior update' when:\n"
            "  - You edited a behavior script directly and want to sync the DB\n"
            "  - You know the behavior name but don't remember the file path\n\n"
            "Use 'behavior install <path>' instead if the file moved or you have\n"
            "the path handy.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior update pr-monitor\n"
            "  adaptive-cli behavior update pr-monitor --force"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_update.add_argument("name", help="Behavior name")
    beh_update.add_argument("--force", action="store_true",
                            help="Apply update without version-change confirmation")
    beh_update.add_argument("--non-interactive", action="store_true", dest="non_interactive",
                            help="Fail instead of prompting (for scripts/CI)")

    beh_toggle = behavior_sub.add_parser(
        "toggle",
        help="Enable or disable a behavior without removing it",
        description=(
            "Toggle the enabled flag on a behavior. Disabled behaviors are excluded\n"
            "from 'behavior verify', 'behavior setup', and hook dispatchers.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior toggle pr-monitor --enable\n"
            "  adaptive-cli behavior toggle pr-monitor --disable"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_toggle.add_argument("name", help="Behavior name")
    toggle_group = beh_toggle.add_mutually_exclusive_group(required=True)
    toggle_group.add_argument("--enable", dest="enable", action="store_true", help="Enable the behavior")
    toggle_group.add_argument("--disable", dest="enable", action="store_false", help="Disable the behavior")

    beh_remove = behavior_sub.add_parser(
        "remove",
        help="Remove a behavior from the database",
        description=(
            "Removes a behavior's DB record. Does NOT delete the artifact file.\n"
            "The artifact path is printed so you can clean it up manually if needed.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior remove pr-monitor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_remove.add_argument("name", help="Behavior name")

    beh_verify = behavior_sub.add_parser(
        "verify",
        help="Check that behavior artifacts exist and prerequisites are met",
        description=(
            "For each enabled behavior (or the named one), runs the verify_script\n"
            "and checks that the artifact file exists.\n\n"
            "Exit code 0 = all pass. Exit code 1 = one or more failures.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior verify             # verify all enabled behaviors\n"
            "  adaptive-cli behavior verify --name pr-monitor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_verify.add_argument("--name", default=None, help="Verify only this behavior")

    beh_setup = behavior_sub.add_parser(
        "setup",
        help="Run one-time setup scripts for behaviors",
        description=(
            "Runs the setup_script for each behavior (or the named one) that has one.\n"
            "Intended for first-time installation: installing system dependencies,\n"
            "configuring credentials, etc.\n\n"
            "Examples:\n"
            "  adaptive-cli behavior setup              # run setup for all behaviors\n"
            "  adaptive-cli behavior setup --name pr-monitor"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    beh_setup.add_argument("--name", default=None, help="Set up only this behavior")

    # Knowledge commands
    knowledge_parser = subparsers.add_parser("knowledge", help="Manage knowledge entries")
    knowledge_sub = knowledge_parser.add_subparsers(dest="knowledge_subcommand")

    know_add = knowledge_sub.add_parser("add", help="Add a knowledge entry")
    know_add.add_argument("--title", required=True, help="Entry title")
    know_add.add_argument("--partition", required=True, help="Partition path (e.g. projects/monitor-cinc)")
    know_add.add_argument("--category", required=True,
                          choices=["preference", "pattern", "decision", "convention", "context"])
    know_add.add_argument("--content", required=True, help="Markdown content")
    know_add.add_argument("--tags", nargs="+", default=[], help="Tags for discovery")
    know_add.add_argument("--confidence", type=float, default=1.0)
    know_add.add_argument("--decay-exempt", action="store_true", dest="decay_exempt")
    know_add.add_argument("--expires-at", help="ISO date for calendar-based expiry (YYYY-MM-DD)")
    know_add.add_argument("--expires-when", help="Human-readable expiry trigger description")
    know_add.add_argument("--expires-when-tag", help="Signal tag to watch for event-based expiry")
    know_add.add_argument("--confidential", action="store_true", help="Route to confidential store")

    know_search = knowledge_sub.add_parser("search", help="Search knowledge entries")
    know_search.add_argument("query", help="Search query (matches title, content, tags)")
    know_search.add_argument("--partition", default=None, help="Filter by partition")
    know_search.add_argument("--category", default=None, help="Filter by category")

    know_show = knowledge_sub.add_parser("show", help="Show a knowledge entry")
    know_show.add_argument("identifier", help="Entry ID or title substring")

    know_list = knowledge_sub.add_parser("list", help="List knowledge entries")
    know_list.add_argument("--partition", default=None, help="Filter by partition")
    know_list.add_argument("--category", default=None, help="Filter by category")
    know_list.add_argument("--include-archived", action="store_true", dest="include_archived")

    know_archive = knowledge_sub.add_parser("archive", help="Archive a knowledge entry")
    know_archive.add_argument("identifier", help="Entry ID or title substring")

    know_restore = knowledge_sub.add_parser("restore", help="Restore an archived entry")
    know_restore.add_argument("entry_id", help="Entry ID")

    # Top-level prune
    prune_parser = subparsers.add_parser("prune", help="Find and archive stale knowledge entries")
    prune_parser.add_argument("--dry-run", action="store_true", dest="dry_run")

    # tier
    tier_parser = subparsers.add_parser("tier", help="Manage preference tiers")
    tier_sub = tier_parser.add_subparsers(dest="tier_subcommand")

    tier_sub.add_parser("list", help="List preferences grouped by tier")
    tier_sub.add_parser("recalculate", help="Recalculate all preference tiers")
    tier_sub.add_parser("backfill", help="Backfill tier classification for existing preferences")
    tier_sub.add_parser("summary", help="Show tier distribution summary")

    tier_pin = tier_sub.add_parser("pin", help="Pin a preference to hot tier")
    tier_pin.add_argument("path", help="Preference path (e.g. tools.adaptive_cli.direct_path)")

    tier_unpin = tier_sub.add_parser("unpin", help="Unpin a preference")
    tier_unpin.add_argument("path", help="Preference path")

    # buddy
    buddy_parser = subparsers.add_parser(
        "buddy",
        help="Manage the APE Buddy agent",
        description=(
            "The APE Buddy is a specialist agent that handles all preference\n"
            "bookkeeping in its own context window, keeping the main agent clean.\n\n"
            "Subcommands:\n"
            "  install   Copy ape-buddy.md to ~/.claude/agents/ (and local managed copy)\n"
            "  enable    Delegate APE operations to the buddy agent\n"
            "  disable   Revert to direct adaptive-cli calls in the main context\n"
            "  status    Show install and enable state\n\n"
            "New machine setup:\n"
            "  adaptive-cli sync pull   # restores prefs + buddy agent in one step\n"
            "  adaptive-cli buddy enable"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    buddy_sub = buddy_parser.add_subparsers(dest="buddy_subcommand")
    buddy_sub.add_parser("install", help="Install ape-buddy to ~/.claude/agents/")
    buddy_sub.add_parser("enable", help="Enable buddy delegation")
    buddy_sub.add_parser("disable", help="Disable buddy delegation")
    buddy_sub.add_parser("status", help="Show buddy state")

    parser.add_argument(
        "--base-dir",
        default=None,
        help="Override base directory for storage (default: ~/.adaptive-cli)"
    )

    args = parser.parse_args()

    cli = AdaptivePreferenceCLI(base_dir=args.base_dir)
    
    # Route commands
    try:
        if args.command == "pref":
            if args.subcommand == "create":
                cli.cmd_create_preference(args)
            elif args.subcommand == "show":
                cli.cmd_show_preference(args)
            elif args.subcommand == "list":
                cli.cmd_list_preferences(args)
            elif args.subcommand == "update":
                cli.cmd_update_preference(args)

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

        elif args.command == "registry":
            cli.cmd_registry(args)
        
        elif args.command == "stats":
            cli.cmd_show_stats(args)
        
        elif args.command == "recalculate":
            cli.cmd_recalculate_strengths(args)
        
        elif args.command == "decay":
            cli.cmd_apply_decay(args)
        
        elif args.command == "reset":
            cli.cmd_reset(args)

        elif args.command == "sync":
            if args.sync_subcommand == "configure":
                cli.cmd_sync_configure(args)
            elif args.sync_subcommand == "push":
                cli.cmd_sync_push(args)
            elif args.sync_subcommand == "pull":
                cli.cmd_sync_pull(args)
            elif args.sync_subcommand == "status":
                cli.cmd_sync_status(args)
            else:
                sync_parser.print_help()

        elif args.command == "onboard":
            cli.cmd_onboard(args)

        elif args.command == "template":
            if args.template_subcommand == "list":
                cli.cmd_template_list(args)
            elif args.template_subcommand == "apply":
                cli.cmd_template_apply(args)
            else:
                template_parser.print_help()

        elif args.command == "buddy":
            if args.buddy_subcommand == "install":
                cli.cmd_buddy_install(args)
            elif args.buddy_subcommand == "enable":
                cli.cmd_buddy_enable(args)
            elif args.buddy_subcommand == "disable":
                cli.cmd_buddy_disable(args)
            elif args.buddy_subcommand == "status":
                cli.cmd_buddy_status(args)
            else:
                buddy_parser.print_help()

        elif args.command == "behavior":
            if args.behavior_subcommand == "list":
                cli.cmd_behavior_list(args)
            elif args.behavior_subcommand == "show":
                cli.cmd_behavior_show(args)
            elif args.behavior_subcommand == "add":
                cli.cmd_behavior_add(args)
            elif args.behavior_subcommand == "create":
                cli.cmd_behavior_create(args)
            elif args.behavior_subcommand == "install":
                cli.cmd_behavior_install(args)
            elif args.behavior_subcommand == "update":
                cli.cmd_behavior_update(args)
            elif args.behavior_subcommand == "toggle":
                cli.cmd_behavior_toggle(args)
            elif args.behavior_subcommand == "remove":
                cli.cmd_behavior_remove(args)
            elif args.behavior_subcommand == "verify":
                cli.cmd_behavior_verify(args)
            elif args.behavior_subcommand == "setup":
                cli.cmd_behavior_setup(args)
            else:
                behavior_parser.print_help()

        elif args.command == "knowledge":
            if args.knowledge_subcommand == "add":
                cli.cmd_knowledge_add(args)
            elif args.knowledge_subcommand == "search":
                cli.cmd_knowledge_search(args)
            elif args.knowledge_subcommand == "show":
                cli.cmd_knowledge_show(args)
            elif args.knowledge_subcommand == "list":
                cli.cmd_knowledge_list(args)
            elif args.knowledge_subcommand == "archive":
                cli.cmd_knowledge_archive(args)
            elif args.knowledge_subcommand == "restore":
                cli.cmd_knowledge_restore(args)
            else:
                knowledge_parser.print_help()

        elif args.command == "prune":
            cli.cmd_knowledge_prune(args)

        elif args.command == "tier":
            if args.tier_subcommand == "list":
                cli.cmd_tier_list(args)
            elif args.tier_subcommand == "recalculate":
                cli.cmd_tier_recalculate(args)
            elif args.tier_subcommand == "backfill":
                cli.cmd_tier_backfill(args)
            elif args.tier_subcommand == "pin":
                cli.cmd_tier_pin(args)
            elif args.tier_subcommand == "unpin":
                cli.cmd_tier_unpin(args)
            elif args.tier_subcommand == "summary":
                cli.cmd_tier_summary(args)
            else:
                tier_parser.print_help()

        elif args.command == "load-pref":
            cli.cmd_load_pref(args)

        elif args.command == "load-more":
            cli.cmd_load_more(args)

        elif args.command == "inventory":
            cli.cmd_inventory(args)

        else:
            parser.print_help()

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
