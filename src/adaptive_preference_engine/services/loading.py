"""
preference_loader.py - Load preferences with associations using Option C strategy
(Follow association chains with diminishing confidence, stop at threshold)
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path
from adaptive_preference_engine.models import Association, ContextStack
from adaptive_preference_engine.storage import PreferenceStorageManager
import json


class PreferenceLoader:
    """Load preferences for a given context, following association chains"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.confidence_threshold = 0.45  # Stop loading when effective confidence drops below this
        self.max_hops = 20                # Hard cap — guards against cycles in deeply connected graphs
    
    def load_for_context(self, 
                        context_tags: List[str],
                        primary_pref_id: Optional[str] = None,
                        stack_contexts: Optional[List[str]] = None,
                        include_trees: bool = True,
                        associated_limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Main loading algorithm.
        
        Args:
            context_tags: Task/situation context (e.g., ["api_design", "python"])
            primary_pref_id: Explicitly set primary preference (auto-infer if None)
            stack_contexts: List of active context IDs to load (base, project, conversation)
        
        Returns:
            {
              "primary": {...},
              "associated": [...],
              "context_stack": [...],
              "strength_metadata": {...}
            }
        """
        
        loaded = {
            "primary": None,
            "associated": [],
            "context_stack": [],
            "strength_metadata": {
                "confidence_threshold": self.confidence_threshold,
                "max_hops": self.max_hops,
                "loaded_at": datetime.now().isoformat()
            }
        }
        
        # STEP 1: Stack contexts
        if stack_contexts is None:
            stack_contexts = ["base"]  # Default: load base preferences
        
        context_stack = []
        for ctx_id in stack_contexts:
            ctx = self.storage.contexts.get_context(ctx_id)
            if ctx:
                context_stack.append(ctx)
        
        loaded["context_stack"] = [ctx.to_dict() for ctx in context_stack]
        
        # Merge preferences from all contexts (later overrides earlier)
        merged_prefs = self._merge_context_preferences(context_stack)
        
        # STEP 2: Determine primary preference
        if primary_pref_id is None:
            primary_pref_id = self._infer_primary_preference(context_tags, merged_prefs)
        
        if not primary_pref_id:
            return loaded  # No primary preference found
        
        # Load primary preference
        primary_pref = self.storage.preferences.get_preference(primary_pref_id)
        if primary_pref:
            loaded["primary"] = {
                "id": primary_pref_id,
                "path": primary_pref.path,
                "value": primary_pref.value,
                "confidence": primary_pref.confidence,
            }
            if include_trees:
                loaded["primary"]["preferences"] = self._load_preference_tree(primary_pref_id)
        
        # STEP 3: Follow associations with diminishing confidence
        visited = {primary_pref_id}
        to_explore = [(primary_pref_id, 0, 1.0)]  # (pref_id, hops, confidence)

        while to_explore:
            current_id, current_hops, current_confidence = to_explore.pop(0)

            # Stop conditions
            if current_hops >= self.max_hops:
                continue
            if current_confidence < self.confidence_threshold:
                continue
            
            # Find associations involving this preference
            associations = self.storage.associations.get_associations_for_preference(current_id)
            
            # Sort by directional strength (strongest first)
            sorted_assocs = sorted(
                associations,
                key=lambda a: a.get_strength_for_direction(current_id),
                reverse=True
            )
            
            for assoc in sorted_assocs:
                # Determine next preference ID
                if assoc.from_id == current_id:
                    next_id = assoc.to_id
                    direction_strength = assoc.strength_forward
                else:
                    next_id = assoc.from_id
                    direction_strength = assoc.strength_backward
                
                # Skip if already visited
                if next_id in visited:
                    continue
                
                # Calculate confidence for next level
                next_confidence = current_confidence * direction_strength
                
                # Only proceed if confidence is above threshold
                if next_confidence >= self.confidence_threshold:
                    next_pref = self.storage.preferences.get_preference(next_id)
                    
                    if next_pref:
                        associated_entry = {
                            "id": next_id,
                            "path": next_pref.path,
                            "value": next_pref.value,
                            "hops": current_hops + 1,
                            "confidence": round(next_confidence, 3),
                            "association_id": assoc.id,
                            "association_strength": round(direction_strength, 3),
                            "trend": assoc.learning_forward.trend if assoc.from_id == current_id else assoc.learning_backward.trend,
                            "description": assoc.description,
                        }
                        if include_trees:
                            associated_entry["preferences"] = self._load_preference_tree(next_id)
                        loaded["associated"].append(associated_entry)

                        visited.add(next_id)
                        to_explore.append((next_id, current_hops + 1, next_confidence))
        
        # Sort associated preferences by confidence (highest first)
        loaded["associated"] = sorted(
            loaded["associated"],
            key=lambda x: x["confidence"],
            reverse=True
        )

        if associated_limit is not None:
            loaded["associated"] = loaded["associated"][:associated_limit]
        
        return loaded
    
    def _merge_context_preferences(self, contexts: List[ContextStack]) -> Dict[str, Any]:
        """Merge preferences from context stack (later overrides earlier)"""
        merged = {}
        for context in sorted(contexts, key=lambda c: c.stack_level):
            merged.update(context.preferences)
        return merged
    
    def _infer_primary_preference(self, context_tags: List[str], merged_prefs: Dict) -> Optional[str]:
        """
        Infer primary preference from context tags and merged preferences.
        
        Strategy:
        1. Look for preference matching context tags
        2. If communication context, use output_format
        3. If coding context, use language/framework
        4. Default to first preference found
        """
        
        all_prefs = self.storage.preferences.get_all_preferences()
        tags_lower = [t.lower() for t in context_tags]

        # Single pass: exact context node > substring > selector fallback
        substring_match: Optional[str] = None
        selector_fallback: Optional[str] = None

        for pref in all_prefs:
            path_lower = pref.path.lower()

            if any(path_lower == f"context.{tag}" for tag in tags_lower):
                return pref.id  # highest priority — early exit

            if substring_match is None and any(tag in path_lower for tag in tags_lower):
                substring_match = pref.id

            if selector_fallback is None and pref.type == "selector":
                selector_fallback = pref.id

        return substring_match or selector_fallback

    def load_knowledge_for_context(
        self,
        context_tags: List[str],
        sync_repo_path: Optional[str] = None,
        max_tokens: int = 2000,
    ) -> List[Dict[str, Any]]:
        """Load knowledge entries matching context tags, reading ref files for compacted entries."""
        all_entries = self.storage.knowledge.get_all_entries()
        tags_lower = {t.lower() for t in context_tags}

        scored = []
        for entry in all_entries:
            partition_parts = set(entry.partition.lower().replace("/", " ").split())
            entry_tags = {t.lower() for t in entry.tags}
            partition_match = bool(partition_parts & tags_lower)
            tag_match = bool(entry_tags & tags_lower)

            if not (partition_match or tag_match):
                continue

            score = (
                (2 if partition_match else 0)
                + (1 if tag_match else 0)
                + entry.confidence * 0.5
                + min(entry.access_count, 10) * 0.05
            )
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        used_tokens = 0
        for score, entry in scored:
            if entry.ref_path and sync_repo_path:
                ref_file = Path(sync_repo_path) / entry.ref_path
                if ref_file.exists():
                    content = ref_file.read_text(encoding="utf-8")
                    source = "ref_file"
                else:
                    content = entry.content
                    source = "summary_only"
            else:
                content = entry.content
                source = "inline"

            est_tokens = len(content) // 4
            if used_tokens + est_tokens > max_tokens:
                break

            results.append({
                "title": entry.title,
                "partition": entry.partition,
                "content": content,
                "source": source,
            })
            used_tokens += est_tokens
            self.storage.knowledge.record_access(entry.id)

        return results

    def _load_preference_tree(self, pref_id: str) -> Dict[str, Any]:
        """
        Load the full preference tree starting from a preference.
        Includes all children/sub-preferences.
        """
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return {}
        
        tree = {
            "id": pref.id,
            "name": pref.name,
            "value": pref.value,
            "type": pref.type,
            "children": []
        }
        
        # Get all child preferences
        children = self.storage.preferences.get_preferences_for_parent(pref_id)
        for child in children:
            tree["children"].append(self._load_preference_tree(child.id))
        
        return tree
    
    def load_for_agent(self,
                      context_tags: List[str],
                      primary_pref_id: Optional[str] = None,
                      stack_contexts: Optional[List[str]] = None,
                      compact: bool = False,
                      associated_limit: int = 5,
                      tier_filter: Optional[List[str]] = None,
                      context_filter: bool = False) -> str:
        """
        Load preferences and format for agent consumption (JSON string).
        Includes strength metadata so agent understands confidence levels.
        """
        loaded = self.load_for_context(
            context_tags,
            primary_pref_id,
            stack_contexts,
            include_trees=not compact,
            associated_limit=associated_limit if compact else None,
        )

        if tier_filter or context_filter:
            from adaptive_preference_engine.services.context_detection import matches_context
            try:
                from scripts.config import APEConfig
                cfg = APEConfig.load(str(self.storage.base_dir))
                config_prefixes = cfg.get("universal_prefixes", None)
            except Exception:
                config_prefixes = None

            def should_include(pref_entry):
                pref_id = pref_entry.get("id")
                if pref_id:
                    pref_obj = self.storage.preferences.get_preference(pref_id)
                    if pref_obj:
                        if tier_filter and getattr(pref_obj, 'tier', 'hot') not in tier_filter:
                            return False
                        if context_filter and not matches_context(pref_obj.path, context_tags, config_prefixes):
                            return False
                return True

            loaded["associated"] = [a for a in loaded["associated"] if should_include(a)]

        # Format for agent
        agent_context = {
            "primary_preference": loaded["primary"],
            "associated_preferences": loaded["associated"],
            "confidence_threshold": loaded["strength_metadata"]["confidence_threshold"],
            "note": "Use primary first, fall back to associated based on confidence",
            "compact": compact,
        }

        # Load matching knowledge
        try:
            from scripts.config import AdaptiveConfig, APEConfig
            adaptive_cfg = AdaptiveConfig(str(self.storage.base_dir))
            sync_repo = adaptive_cfg.sync_repo_path
            ape_cfg = APEConfig.load(str(self.storage.base_dir))
            injection_budget = ape_cfg.get("token_budgets.context_injection", 2000)
            knowledge = self.load_knowledge_for_context(
                context_tags=context_tags,
                sync_repo_path=sync_repo,
                max_tokens=injection_budget,
            )
            agent_context["knowledge"] = knowledge
        except Exception:
            agent_context["knowledge"] = []

        return json.dumps(agent_context, indent=2)

    def load_all_by_tier(self, tier: str = "hot", context_tags: Optional[List[str]] = None) -> List[Dict]:
        """Load all preferences in a given tier, optionally filtered by context."""
        all_prefs = self.storage.preferences.get_all_preferences()

        try:
            from scripts.config import APEConfig
            cfg = APEConfig.load(str(self.storage.base_dir))
            config_prefixes = cfg.get("universal_prefixes", None)
        except Exception:
            config_prefixes = None

        results = []
        for pref in all_prefs:
            if getattr(pref, 'tier', 'hot') != tier:
                continue
            if context_tags:
                from adaptive_preference_engine.services.context_detection import matches_context
                if not matches_context(pref.path, context_tags, config_prefixes):
                    continue
            results.append({
                "id": pref.id,
                "path": pref.path,
                "value": pref.value,
                "confidence": pref.confidence,
                "tier": pref.tier,
                "pinned": getattr(pref, 'pinned', False),
            })
        return sorted(results, key=lambda x: x["confidence"], reverse=True)

    def load_single_pref(self, pref_path: str) -> Optional[Dict[str, Any]]:
        """Load a single preference by path, regardless of tier."""
        prefs = self.storage.preferences.get_preferences_by_path(pref_path)
        if not prefs:
            return None
        for p in prefs:
            if p.path == pref_path:
                return {
                    "id": p.id,
                    "path": p.path,
                    "value": p.value,
                    "confidence": p.confidence,
                    "tier": getattr(p, 'tier', 'hot'),
                    "pinned": getattr(p, 'pinned', False),
                    "note": "Loaded on demand",
                }
        return None

    def load_by_context_tag(self, tag: str) -> List[Dict[str, Any]]:
        """Load all preferences matching a context tag, regardless of tier."""
        from adaptive_preference_engine.services.context_detection import matches_context
        all_prefs = self.storage.preferences.get_all_preferences()
        results = []
        for pref in all_prefs:
            if matches_context(pref.path, [tag]):
                results.append({
                    "id": pref.id,
                    "path": pref.path,
                    "value": pref.value,
                    "confidence": pref.confidence,
                    "tier": getattr(pref, 'tier', 'hot'),
                    "pinned": getattr(pref, 'pinned', False),
                })
        return sorted(results, key=lambda x: x["confidence"], reverse=True)

    def get_inventory(self, tiers: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """Return preference paths grouped by tier (for agent to browse available prefs)."""
        if tiers is None:
            tiers = ["warm", "cold"]
        all_prefs = self.storage.preferences.get_all_preferences()
        inventory = {tier: [] for tier in tiers}
        for pref in all_prefs:
            tier = getattr(pref, 'tier', 'hot')
            if tier in inventory:
                inventory[tier].append(pref.path)
        for tier in inventory:
            inventory[tier].sort()
        total = sum(len(paths) for paths in inventory.values())
        return {"tiers": inventory, "total_available": total}


class AssociationFollower:
    """Helper for following association chains"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def get_associated_prefs(self, 
                            pref_id: str, 
                            direction: str = "both",
                            min_strength: float = 0.6) -> List[Dict[str, Any]]:
        """
        Get preferences associated with the given one.
        
        Args:
            pref_id: Source preference ID
            direction: "forward", "backward", or "both"
            min_strength: Only return associations above this strength
        
        Returns:
            List of associated preferences with metadata
        """
        associations = self.storage.associations.get_associations_for_preference(pref_id)
        
        results = []
        for assoc in associations:
            if assoc.from_id == pref_id:
                if direction in ["forward", "both"]:
                    if assoc.strength_forward >= min_strength:
                        results.append({
                            "pref_id": assoc.to_id,
                            "strength": assoc.strength_forward,
                            "direction": "forward",
                            "association_id": assoc.id,
                            "description": assoc.description
                        })
            
            if assoc.to_id == pref_id:
                if direction in ["backward", "both"]:
                    if assoc.strength_backward >= min_strength:
                        results.append({
                            "pref_id": assoc.from_id,
                            "strength": assoc.strength_backward,
                            "direction": "backward",
                            "association_id": assoc.id,
                            "description": assoc.description
                        })
        
        # Sort by strength
        return sorted(results, key=lambda x: x["strength"], reverse=True)


if __name__ == "__main__":
    # Quick test
    from adaptive_preference_engine.models import Preference, Association, ContextStack, generate_id
    
    # Create temporary storage
    storage = PreferenceStorageManager("/tmp/test_loader")
    
    # Create test preferences
    output_format = Preference(
        id="comm_format",
        path="communication.output_format",
        parent_id=None,
        name="output_format",
        type="selector",
        confidence=1.0
    )
    
    bullets = Preference(
        id="comm_bullets",
        path="communication.output_format.bullets",
        parent_id="comm_format",
        name="bullets",
        type="variant",
        value="active",
        confidence=0.85
    )
    
    datastructure = Preference(
        id="coding_datastructure",
        path="coding.data_structure_clarity",
        parent_id=None,
        name="data_structure_clarity",
        type="selector",
        confidence=0.75
    )
    
    # Save preferences
    storage.preferences.save_preference(output_format)
    storage.preferences.save_preference(bullets)
    storage.preferences.save_preference(datastructure)
    
    # Create association
    assoc = Association(
        id="assoc_bullets_datastructure",
        from_id="comm_bullets",
        to_id="coding_datastructure",
        strength_forward=0.90,
        strength_backward=0.65
    )
    storage.associations.save_association(assoc)
    
    # Create base context
    ctx = ContextStack(
        id="ctx_base",
        name="Base Preferences",
        scope="base",
        stack_level=0,
        preferences={
            "comm_format": {"value": "bullets", "confidence": 0.85, "source": "learned"}
        }
    )
    storage.contexts.save_context(ctx)
    
    # Load preferences
    loader = PreferenceLoader(storage)
    loaded = loader.load_for_context(
        context_tags=["communication", "structure"],
        stack_contexts=["ctx_base"]
    )
    
    print("\nLoaded preferences:")
    print(json.dumps(loaded, indent=2))
