"""
preference_templates.py — Built-in preference templates.

A template is a named collection of preferences for a common context.
Apply with: adaptive-cli template apply <name>
"""
from datetime import datetime
from typing import Dict, List, Any

# Each template entry:
#   name: str
#   description: str
#   preferences: list of dicts matching Preference constructor kwargs
#     (id will be generated at apply time; created/last_updated auto-set)

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "python-developer": {
        "name": "Python Developer",
        "description": "Common preferences for Python development: type hints, docstrings, test style",
        "preferences": [
            {"path": "coding.style.type_hints", "name": "type_hints",
             "type": "variant", "value": "always",
             "description": "Always include type annotations on function signatures"},
            {"path": "coding.style.docstrings", "name": "docstrings",
             "type": "variant", "value": "google",
             "description": "Use Google-style docstrings"},
            {"path": "coding.testing.framework", "name": "test_framework",
             "type": "variant", "value": "pytest",
             "description": "Use pytest for all test files"},
            {"path": "coding.style.line_length", "name": "line_length",
             "type": "property", "value": "88",
             "description": "Max line length (Black default)"},
        ],
    },
    "technical-writer": {
        "name": "Technical Writer",
        "description": "Preferences for documentation and communication clarity",
        "preferences": [
            {"path": "communication.output_format.structure", "name": "structure",
             "type": "variant", "value": "headers",
             "description": "Use markdown headers to structure long responses"},
            {"path": "communication.output_format.code_examples", "name": "code_examples",
             "type": "variant", "value": "always",
             "description": "Always include code examples in technical explanations"},
            {"path": "communication.tone", "name": "tone",
             "type": "variant", "value": "precise",
             "description": "Prefer precise, unambiguous language over conversational"},
            {"path": "communication.output_format.length", "name": "response_length",
             "type": "variant", "value": "thorough",
             "description": "Err on the side of complete explanations"},
        ],
    },
    "code-reviewer": {
        "name": "Code Reviewer",
        "description": "Preferences for giving and receiving code review feedback",
        "preferences": [
            {"path": "coding.review.style", "name": "review_style",
             "type": "variant", "value": "inline",
             "description": "Prefer inline comments over summary reviews"},
            {"path": "coding.review.severity_labels", "name": "severity_labels",
             "type": "variant", "value": "always",
             "description": "Always label comments as nit/suggestion/required"},
            {"path": "coding.review.focus", "name": "review_focus",
             "type": "variant", "value": "correctness-first",
             "description": "Prioritize correctness and logic over style"},
        ],
    },
    "concise-communicator": {
        "name": "Concise Communicator",
        "description": "Preferences for brief, direct responses with minimal filler",
        "preferences": [
            {"path": "communication.output_format.length", "name": "response_length",
             "type": "variant", "value": "concise",
             "description": "Keep responses short and direct"},
            {"path": "communication.output_format.bullets", "name": "use_bullets",
             "type": "variant", "value": "sparingly",
             "description": "Use bullet lists only when genuinely list-like"},
            {"path": "communication.tone", "name": "tone",
             "type": "variant", "value": "direct",
             "description": "Skip preamble, lead with the answer"},
        ],
    },
}


def list_templates() -> List[Dict[str, Any]]:
    """Return all templates as a list with name, key, description, and preference count."""
    return [
        {
            "key": key,
            "name": t["name"],
            "description": t["description"],
            "count": len(t["preferences"]),
        }
        for key, t in TEMPLATES.items()
    ]


def get_template(key: str) -> Dict[str, Any]:
    """Return a template by key, or raise KeyError if not found."""
    if key not in TEMPLATES:
        available = ", ".join(TEMPLATES.keys())
        raise KeyError(f"Template '{key}' not found. Available: {available}")
    return TEMPLATES[key]


class PreferenceTemplateManager:
    """Compatibility class used by onboarding.py to list and apply templates."""

    def list_templates(self) -> List[Dict[str, Any]]:
        return list_templates()

    def apply_template(self, template_key: str, storage: Any) -> List[str]:
        """Apply a template to storage. Returns list of created preference IDs."""
        from scripts.models import Preference, generate_id
        tmpl = get_template(template_key)
        created = datetime.now().isoformat()
        ids = []
        existing_paths = {p.path for p in storage.preferences.get_all_preferences()}
        for p in tmpl["preferences"]:
            if p["path"] in existing_paths:
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
            storage.preferences.save_preference(pref)
            ids.append(pref.id)
        return ids
