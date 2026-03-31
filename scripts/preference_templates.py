"""
preference_templates.py - Preference templates for common user types
Addresses Lisa Thompson's gap: "No preference templates for common user types"
"""

from typing import List, Dict, Optional
from scripts.models import Preference, generate_id
from scripts.storage import PreferenceStorageManager


class PreferenceTemplateManager:
    """Manages preference templates for different user types"""

    # Template definitions
    TEMPLATES = {
        "DEVELOPER": {
            "name": "Developer",
            "description": "Prefers code blocks, concise explanations, technical depth, table output for APIs",
            "preferences": [
                {
                    "path": "communication.output_format.code_blocks",
                    "parent_id": "comm_format",
                    "name": "code_blocks",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Show code snippets in dedicated blocks with syntax highlighting"
                },
                {
                    "path": "communication.explanation_style.concise",
                    "parent_id": "comm_style",
                    "name": "concise",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Keep explanations brief and to the point"
                },
                {
                    "path": "communication.technical_depth.high",
                    "parent_id": "comm_depth",
                    "name": "high",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Include technical details, edge cases, and implementation specifics"
                },
                {
                    "path": "communication.output_format.tables",
                    "parent_id": "comm_format",
                    "name": "tables",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.8,
                    "description": "Use tables for API documentation and data structures"
                },
                {
                    "path": "communication.structure.examples",
                    "parent_id": "comm_struct",
                    "name": "examples",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Include practical code examples"
                }
            ]
        },
        "ANALYST": {
            "name": "Analyst",
            "description": "Prefers tables, data-heavy output, CSV format, detailed breakdowns",
            "preferences": [
                {
                    "path": "communication.output_format.tables",
                    "parent_id": "comm_format",
                    "name": "tables",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.95,
                    "description": "Present data in structured tables"
                },
                {
                    "path": "communication.output_format.csv",
                    "parent_id": "comm_format",
                    "name": "csv",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Provide exportable CSV format for data"
                },
                {
                    "path": "communication.data_density.high",
                    "parent_id": "comm_density",
                    "name": "high",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Include comprehensive data and metrics"
                },
                {
                    "path": "communication.breakdown_level.detailed",
                    "parent_id": "comm_breakdown",
                    "name": "detailed",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Provide granular breakdown of data"
                },
                {
                    "path": "communication.structure.statistics",
                    "parent_id": "comm_struct",
                    "name": "statistics",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Include statistical summaries and trends"
                }
            ]
        },
        "WRITER": {
            "name": "Writer",
            "description": "Prefers prose output, no bullets, long-form, emotional depth",
            "preferences": [
                {
                    "path": "communication.format_style.prose",
                    "parent_id": "format_style",
                    "name": "prose",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.95,
                    "description": "Use flowing prose paragraphs instead of lists"
                },
                {
                    "path": "communication.list_format.disabled",
                    "parent_id": "list_format",
                    "name": "disabled",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Avoid bullet points and numbered lists"
                },
                {
                    "path": "communication.length_preference.long",
                    "parent_id": "length",
                    "name": "long",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Provide comprehensive, long-form responses"
                },
                {
                    "path": "communication.emotional_tone.deep",
                    "parent_id": "tone",
                    "name": "deep",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.8,
                    "description": "Include emotional depth and nuance"
                },
                {
                    "path": "communication.narrative_style.storytelling",
                    "parent_id": "narrative",
                    "name": "storytelling",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.75,
                    "description": "Use narrative techniques and examples"
                }
            ]
        },
        "EXECUTIVE": {
            "name": "Executive",
            "description": "Prefers bullet summaries, brevity, high-level, no jargon",
            "preferences": [
                {
                    "path": "communication.output_format.bullets",
                    "parent_id": "comm_format",
                    "name": "bullets",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.95,
                    "description": "Use concise bullet points"
                },
                {
                    "path": "communication.length_preference.brief",
                    "parent_id": "length",
                    "name": "brief",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Keep responses as brief as possible"
                },
                {
                    "path": "communication.abstraction_level.high",
                    "parent_id": "abstraction",
                    "name": "high",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Focus on high-level overview, not details"
                },
                {
                    "path": "communication.jargon_avoidance.strict",
                    "parent_id": "jargon",
                    "name": "strict",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Avoid technical jargon and specialized terminology"
                },
                {
                    "path": "communication.structure.actionable",
                    "parent_id": "comm_struct",
                    "name": "actionable",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Focus on decisions and actions needed"
                }
            ]
        },
        "LEARNER": {
            "name": "Learner",
            "description": "Prefers step-by-step, explanations, examples, gentle tone",
            "preferences": [
                {
                    "path": "communication.structure.step_by_step",
                    "parent_id": "comm_struct",
                    "name": "step_by_step",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.95,
                    "description": "Break down concepts into step-by-step progression"
                },
                {
                    "path": "communication.explanation_depth.detailed",
                    "parent_id": "explain_depth",
                    "name": "detailed",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Provide thorough explanations of each concept"
                },
                {
                    "path": "communication.structure.examples",
                    "parent_id": "comm_struct",
                    "name": "examples",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.9,
                    "description": "Include practical examples throughout"
                },
                {
                    "path": "communication.tone.gentle",
                    "parent_id": "tone",
                    "name": "gentle",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.85,
                    "description": "Use supportive, encouraging tone"
                },
                {
                    "path": "communication.pacing.slow",
                    "parent_id": "pacing",
                    "name": "slow",
                    "type": "variant",
                    "value": "enabled",
                    "confidence": 0.8,
                    "description": "Introduce concepts gradually without rushing"
                }
            ]
        }
    }

    def __init__(self, storage: PreferenceStorageManager = None):
        """Initialize template manager with optional storage"""
        self.storage = storage

    def apply_template(self, template_name: str, storage: PreferenceStorageManager) -> List[str]:
        """
        Apply a template to the preference storage.
        Creates standard preferences from the template.

        Args:
            template_name: Name of template (e.g., "DEVELOPER")
            storage: PreferenceStorageManager instance

        Returns:
            List of created preference IDs
        """
        if template_name not in self.TEMPLATES:
            raise ValueError(f"Unknown template: {template_name}")

        template = self.TEMPLATES[template_name]
        created_ids: List[str] = []

        for pref_spec in template["preferences"]:
            # Generate unique ID for each created preference
            pref_id = generate_id("pref")

            # Create preference object
            pref = Preference(
                id=pref_id,
                path=pref_spec.get("path", ""),
                parent_id=pref_spec.get("parent_id"),
                name=pref_spec.get("name", ""),
                type=pref_spec.get("type", "variant"),
                value=pref_spec.get("value"),
                confidence=pref_spec.get("confidence", 0.5),
                description=pref_spec.get("description", ""),
                auto_detected=False
            )

            # Save preference
            storage.preferences.save_preference(pref)
            created_ids.append(pref_id)

        return created_ids

    def list_templates(self) -> List[Dict]:
        """
        Return list of available templates with metadata.

        Returns:
            List of dicts with name, description, preference_count
        """
        templates_list = []

        for template_key, template_data in self.TEMPLATES.items():
            templates_list.append({
                "key": template_key,
                "name": template_data["name"],
                "description": template_data["description"],
                "preference_count": len(template_data["preferences"])
            })

        return templates_list

    def detect_best_template(self, signals: List) -> str:
        """
        Heuristically suggest the best template based on signal patterns.

        Args:
            signals: List of Signal objects

        Returns:
            Template key (e.g., "DEVELOPER")
        """
        if not signals:
            return "LEARNER"  # Default to learner for new users

        # Count signal types and contexts
        context_counts = {}
        feedback_count = 0
        correction_count = 0

        for signal in signals:
            # Count context tags
            for tag in signal.context_tags:
                context_counts[tag] = context_counts.get(tag, 0) + 1

            # Count signal types
            if signal.type == "feedback":
                feedback_count += 1
            elif signal.type == "correction":
                correction_count += 1

        # Heuristic scoring
        scores = {
            "DEVELOPER": 0,
            "ANALYST": 0,
            "WRITER": 0,
            "EXECUTIVE": 0,
            "LEARNER": 0
        }

        # Check for coding/tech contexts
        if context_counts.get("code", 0) > context_counts.get("text", 0):
            scores["DEVELOPER"] += 10

        # Check for data contexts
        if "data" in context_counts or "analytics" in context_counts:
            scores["ANALYST"] += 10

        # Check for writing contexts
        if "writing" in context_counts or "content" in context_counts:
            scores["WRITER"] += 10

        # Check for business contexts
        if "business" in context_counts or "summary" in context_counts:
            scores["EXECUTIVE"] += 10

        # Learning signals suggest LEARNER
        if correction_count > feedback_count:
            scores["LEARNER"] += 10

        # Default to learner if no clear signal
        best_template = max(scores, key=scores.get)

        if scores[best_template] == 0:
            return "LEARNER"

        return best_template

    def get_template_preferences(self, template_name: str) -> List[Dict]:
        """
        Get preference specifications for a template without applying them.

        Args:
            template_name: Name of template (e.g., "DEVELOPER")

        Returns:
            List of preference specification dicts
        """
        if template_name not in self.TEMPLATES:
            raise ValueError(f"Unknown template: {template_name}")

        return self.TEMPLATES[template_name]["preferences"]


if __name__ == "__main__":
    # Quick test
    manager = PreferenceTemplateManager()

    # List templates
    print("Available Templates:")
    for template in manager.list_templates():
        print(f"  {template['key']}: {template['name']} ({template['preference_count']} prefs)")

    # Get developer template preferences
    print("\nDeveloper Template Preferences:")
    prefs = manager.get_template_preferences("DEVELOPER")
    for pref in prefs:
        print(f"  - {pref['name']}: {pref['description']}")

    # Test with storage
    storage = PreferenceStorageManager("/tmp/test_templates")
    created = manager.apply_template("DEVELOPER", storage)
    print(f"\nApplied Developer template: {len(created)} preferences created")

    # Verify preferences were saved
    all_prefs = storage.preferences.get_all_preferences()
    print(f"Total preferences in storage: {len(all_prefs)}")
