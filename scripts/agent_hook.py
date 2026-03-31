"""
agent_hook.py - Integration hook for AI agents to access preferences
Provides preferences to agents and handles feedback/corrections
"""

import json
from typing import Dict, List, Optional, Any
from scripts.storage import PreferenceStorageManager
from adaptive_preference_engine.services.loading import PreferenceLoader
from adaptive_preference_engine.services.signals import SignalProcessor


class AgentPreferenceHook:
    """Integration point between agent and preference engine"""
    
    def __init__(self, base_dir: str = None):
        self.storage = PreferenceStorageManager(base_dir)
        self.loader = PreferenceLoader(self.storage)
        self.processor = SignalProcessor(self.storage)
    
    def get_preferences_for_context(self,
                                    context_tags: List[str],
                                    primary_pref_id: Optional[str] = None,
                                    stack_contexts: Optional[List[str]] = None) -> str:
        """
        Get preferences formatted for agent consumption.
        
        Returns JSON string that agent can parse.
        
        Args:
            context_tags: Context tags (e.g., ["python", "api_design"])
            primary_pref_id: Optional explicit primary preference
            stack_contexts: Optional list of context IDs to activate
        
        Returns:
            JSON string with preferences and metadata
        """
        
        return self.loader.load_for_agent(
            context_tags=context_tags,
            primary_pref_id=primary_pref_id,
            stack_contexts=stack_contexts
        )
    
    def report_correction(self,
                         task: str,
                         context_tags: List[str],
                         agent_proposed: str,
                         user_corrected_to: str,
                         user_message: str = "") -> Dict[str, Any]:
        """
        Report a correction (agent proposed X, user wanted Y).
        
        This is the KEY learning signal.
        
        Returns:
            Signal details for confirmation
        """
        
        signal = self.processor.process_correction(
            task=task,
            context_tags=context_tags,
            agent_proposed=agent_proposed,
            user_corrected_to=user_corrected_to,
            user_message=user_message
        )
        
        return {
            "status": "recorded",
            "signal_id": signal.id,
            "associations_updated": len(signal.associations_affected),
            "preferences_updated": len(signal.preferences_affected)
        }
    
    def report_feedback(self,
                       task: str,
                       context_tags: List[str],
                       preferences_used: List[str],
                       user_response: str,
                       satisfaction_level: Optional[float] = None) -> Dict[str, Any]:
        """
        Report user feedback on output.
        
        Args:
            task: Task name
            context_tags: Context tags
            preferences_used: Which preferences were used in output
            user_response: User's response/feedback
            satisfaction_level: Optional explicit satisfaction (0-1)
        
        Returns:
            Signal details
        """
        
        signal = self.processor.process_feedback(
            task=task,
            context_tags=context_tags,
            preferences_used=preferences_used,
            user_response=user_response,
            satisfaction_level=satisfaction_level
        )
        
        return {
            "status": "recorded",
            "signal_id": signal.id,
            "emotional_tone": signal.emotional_tone,
            "preferences_updated": len(signal.preferences_affected)
        }
    
    def suggest_preferences(self,
                           context_tags: List[str]) -> Dict[str, Any]:
        """
        Suggest preferences for a context.
        Useful for agents to discover applicable preferences.
        
        Returns dict with suggestions
        """
        
        loaded = self.loader.load_for_context(
            context_tags=context_tags,
            stack_contexts=["base"]  # Use base as default
        )
        
        suggestions = {
            "context": context_tags,
            "primary": loaded["primary"],
            "recommended": loaded["associated"][:3] if loaded["associated"] else [],  # Top 3
            "total_associated": len(loaded["associated"])
        }
        
        return suggestions


class AgentPreferenceMiddleware:
    """
    Middleware layer for injecting preferences into agent prompts/context.
    
    Usage:
        middleware = AgentPreferenceMiddleware()
        agent_prompt = middleware.inject_preferences(
            base_prompt="Help me design an API",
            context_tags=["python", "api_design"]
        )
        # Now agent receives preferences injected into prompt
    """
    
    def __init__(self, base_dir: str = None):
        self.hook = AgentPreferenceHook(base_dir)
    
    def inject_preferences(self,
                          base_prompt: str,
                          context_tags: List[str],
                          include_in_prompt: bool = True) -> str:
        """
        Inject preferences into agent prompt.
        
        Args:
            base_prompt: Original user prompt
            context_tags: Context tags
            include_in_prompt: Whether to include as prompt context or return separately
        
        Returns:
            Enhanced prompt with preferences
        """
        
        prefs_json = self.hook.get_preferences_for_context(
            context_tags=context_tags,
            stack_contexts=["base", "project", "conversation"]
        )
        
        prefs = json.loads(prefs_json)
        
        if include_in_prompt:
            # Inject preferences into prompt as context
            injection = self._format_preferences_for_prompt(prefs)
            
            enhanced_prompt = f"""{base_prompt}

---
🎯 ASSISTANT PREFERENCES (learned from user behavior):

{injection}

---

Use these preferences to tailor your response. Primary preference has highest priority.
If associated preferences apply, consider them based on confidence levels.
"""
            return enhanced_prompt
        else:
            # Return preferences separately
            return base_prompt  # Let caller handle separately
    
    def _format_preferences_for_prompt(self, prefs: Dict) -> str:
        """Format preferences for human-readable prompt injection"""
        
        lines = []
        
        if prefs.get("primary_preference"):
            primary = prefs["primary_preference"]
            lines.append(f"PRIMARY: {primary['path']}")
            lines.append(f"  Value: {primary['value']}")
            lines.append(f"  Confidence: {primary['confidence']:.0%}")
        
        if prefs.get("associated_preferences"):
            lines.append("\nRELATED (by relevance):")
            for assoc in prefs["associated_preferences"][:5]:  # Top 5
                lines.append(f"  • {assoc['path']}")
                lines.append(f"    Confidence: {assoc['confidence']:.0%} (Strength: {assoc['association_strength']:.0%})")
        
        return "\n".join(lines)


class AgentResponseProcessor:
    """
    Process agent responses to extract which preferences were used.
    
    Helps track which preferences actually influenced the output.
    """
    
    def __init__(self, base_dir: str = None):
        self.hook = AgentPreferenceHook(base_dir)
    
    def extract_used_preferences(self,
                                agent_response: str,
                                context_tags: List[str]) -> List[str]:
        """
        Attempt to extract which preferences influenced the response.
        
        Simple heuristic: look for preference values/names in response.
        
        Returns list of preference IDs likely used
        """
        
        # Load all preferences for context
        storage = self.hook.storage
        all_prefs = storage.preferences.get_all_preferences()
        
        used = []
        response_lower = agent_response.lower()
        
        for pref in all_prefs:
            # Look for preference values/names in response
            if pref.value and pref.value.lower() in response_lower:
                used.append(pref.id)
            elif pref.name and pref.name.lower() in response_lower:
                used.append(pref.id)
        
        return list(set(used))  # Remove duplicates


# Convenience functions for agent integration

def get_agent_preferences(context_tags: List[str]) -> str:
    """
    Quick function for agents to get preferences.
    
    Returns JSON string with preferences.
    
    Usage in agent code:
        from agent_hook import get_agent_preferences
        prefs = get_agent_preferences(["python", "api_design"])
        # Parse JSON and use in response generation
    """
    hook = AgentPreferenceHook()
    return hook.get_preferences_for_context(context_tags)


def report_agent_correction(task: str,
                           context_tags: List[str],
                           agent_proposed: str,
                           user_corrected_to: str,
                           user_message: str = "") -> Dict[str, Any]:
    """
    Quick function to report correction.
    
    Usage:
        report_agent_correction(
            task="api_design",
            context_tags=["python"],
            agent_proposed="communication.output_format.bullets",
            user_corrected_to="communication.output_format.table",
            user_message="Perfect, that's the format I wanted!"
        )
    """
    hook = AgentPreferenceHook()
    return hook.report_correction(
        task=task,
        context_tags=context_tags,
        agent_proposed=agent_proposed,
        user_corrected_to=user_corrected_to,
        user_message=user_message
    )


def inject_agent_preferences(prompt: str, context_tags: List[str]) -> str:
    """
    Quick function to inject preferences into prompt.
    
    Usage:
        enhanced_prompt = inject_agent_preferences(
            prompt="Help me design an API",
            context_tags=["python", "fastapi"]
        )
        # Send enhanced_prompt to agent
    """
    middleware = AgentPreferenceMiddleware()
    return middleware.inject_preferences(prompt, context_tags)


if __name__ == "__main__":
    # Test
    import sys
    sys.path.insert(0, "/home/claude/adaptive-preference-engine/scripts")
    
    hook = AgentPreferenceHook("/tmp/test_agent_hook")
    
    # Simulate getting preferences
    prefs = hook.get_preferences_for_context(
        context_tags=["python", "api_design"],
        stack_contexts=["base"]
    )
    
    print("Agent Preferences:")
    print(prefs)
    
    # Test middleware
    middleware = AgentPreferenceMiddleware("/tmp/test_agent_hook")
    enhanced = middleware.inject_preferences(
        "Help me build a Python API",
        context_tags=["python", "api_design"]
    )
    
    print("\nEnhanced prompt:")
    print(enhanced)
