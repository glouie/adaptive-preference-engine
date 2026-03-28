"""
user_control_panel.py - User interface for preference visibility and control
Addresses Lisa Thompson (Product Design) critical gap: "No user control/transparency"
"""

import sys
from pathlib import Path
from typing import Dict, List
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from storage import PreferenceStorageManager


class PreferenceControlPanel:
    """User-facing interface to see and control learned preferences"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def show_all_preferences(self) -> Dict:
        """
        Display all learned preferences in human-readable format.
        
        Output: Organized by category with confidence scores and details.
        """
        
        preferences = self.storage.preferences.get_all_preferences()
        
        # Organize by path hierarchy
        organized = {}
        
        for pref in preferences:
            # Parse path (e.g., "communication.output_format.bullets")
            parts = pref.path.split(".")
            
            # Create hierarchy
            if parts[0] not in organized:
                organized[parts[0]] = {}
            
            if len(parts) > 1:
                if parts[1] not in organized[parts[0]]:
                    organized[parts[0]][parts[1]] = []
                
                organized[parts[0]][parts[1]].append(pref)
            else:
                if "root" not in organized[parts[0]]:
                    organized[parts[0]]["root"] = []
                organized[parts[0]]["root"].append(pref)
        
        return {
            "total_preferences": len(preferences),
            "organized": organized,
            "preferences": preferences
        }
    
    def display_preferences_formatted(self) -> str:
        """Format preferences for CLI display"""
        
        data = self.show_all_preferences()
        
        output = f"""
╔════════════════════════════════════════════════════════════════╗
║               YOUR LEARNED PREFERENCES                         ║
║                                                                ║
║  Total preferences learned: {data['total_preferences']}
╚════════════════════════════════════════════════════════════════╝
        """.strip()
        
        # Display by category
        for category, subcategories in sorted(data["organized"].items()):
            output += f"\n\n📁 {category.upper()}"
            output += "\n" + "─" * 60
            
            for subcat, prefs in sorted(subcategories.items()):
                if subcat != "root":
                    output += f"\n  {subcat}:"
                
                for pref in prefs:
                    confidence_pct = int(pref.confidence * 100)
                    bar = "█" * (confidence_pct // 10) + "░" * (10 - confidence_pct // 10)
                    
                    solidification = self._calculate_solidification(pref)
                    
                    output += f"""
    • {pref.name}
      Confidence: {confidence_pct}% {bar}
      {solidification}
      Used: {pref.learning.use_count if pref.learning else 0} times
                    """.strip() + "\n"
        
        return output
    
    def show_preference_details(self, pref_id: str) -> Dict:
        """Show detailed information about a specific preference"""
        
        pref = self.storage.preferences.get_preference(pref_id)
        
        if not pref:
            return {"error": f"Preference not found: {pref_id}"}
        
        learning = pref.learning or {}
        
        # Get related associations
        associations = self.storage.associations.get_all_associations()
        related_assocs = [
            a for a in associations
            if a.from_id == pref_id or a.to_id == pref_id
        ]
        
        return {
            "preference": {
                "id": pref.id,
                "name": pref.name,
                "path": pref.path,
                "confidence": pref.confidence,
                "type": pref.type
            },
            "learning_stats": {
                "use_count": learning.get("use_count", 0),
                "satisfaction_rate": learning.get("satisfaction_rate", 0),
                "trend": learning.get("trend", "unknown"),
                "velocity": learning.get("velocity", 0)
            },
            "related": {
                "forward_associations": len([a for a in related_assocs if a.from_id == pref_id]),
                "backward_associations": len([a for a in related_assocs if a.to_id == pref_id])
            }
        }
    
    def display_preference_detail_formatted(self, pref_id: str) -> str:
        """Format preference details for display"""
        
        details = self.show_preference_details(pref_id)
        
        if "error" in details:
            return f"❌ {details['error']}"
        
        pref = details["preference"]
        learning = details["learning_stats"]
        
        confidence_pct = int(pref["confidence"] * 100)
        bar = "█" * (confidence_pct // 10) + "░" * (10 - confidence_pct // 10)
        
        satisfaction_pct = int(learning["satisfaction_rate"] * 100)
        sat_bar = "█" * (satisfaction_pct // 10) + "░" * (10 - satisfaction_pct // 10)
        
        output = f"""
╔════════════════════════════════════════════════════════════════╗
║  PREFERENCE DETAILS: {pref['name'].upper()}
╚════════════════════════════════════════════════════════════════╝

Path: {pref['path']}
Type: {pref['type']}

📊 CONFIDENCE SCORE
  {confidence_pct}% {bar}
  This is how sure I am about this preference

📈 LEARNING STATS
  Uses: {learning['use_count']} times
  Satisfaction: {satisfaction_pct}% {sat_bar}
  Trend: {learning['trend'].replace('_', ' ').title()}
  Velocity: {learning['velocity']:+.2%} per week

🔗 RELATIONSHIPS
  Used together with: {details['related']['forward_associations']} other preferences
  Others use this with: {details['related']['backward_associations']} preferences

💡 INTERPRETATION
  This preference is {'emerging' if confidence_pct < 50 else 'growing' if confidence_pct < 75 else 'solid' if confidence_pct < 90 else 'locked in'}.
  {'You use it consistently.' if learning['trend'] == 'stable' else 'Growing in importance.' if 'increasing' in learning['trend'] else 'You might be changing this.'}
        """.strip()
        
        return output
    
    def _calculate_solidification(self, pref) -> str:
        """Calculate solidification status of a preference"""
        
        use_count = pref.learning.use_count if pref.learning else 0
        confidence = pref.confidence
        
        if confidence >= 0.9:
            return "🔒 SOLID (you know what you want)"
        elif confidence >= 0.7:
            return "📈 Growing (becoming clearer)"
        elif confidence >= 0.5:
            return "🎯 Emerging (pattern detected)"
        else:
            return "❓ Exploring (still learning)"
    
    def edit_preference(self, pref_id: str, new_value: any) -> Dict:
        """Allow user to manually override a preference"""
        
        pref = self.storage.preferences.get_preference(pref_id)
        
        if not pref:
            return {"error": f"Preference not found: {pref_id}"}
        
        old_value = pref.value
        pref.value = new_value
        
        self.storage.preferences.save_preference(pref)
        
        return {
            "success": True,
            "preference": pref.name,
            "old_value": old_value,
            "new_value": new_value,
            "message": f"✓ Updated {pref.name} from {old_value} to {new_value}"
        }
    
    def delete_preference(self, pref_id: str) -> Dict:
        """Allow user to delete a preference"""
        
        pref = self.storage.preferences.get_preference(pref_id)
        
        if not pref:
            return {"error": f"Preference not found: {pref_id}"}
        
        pref_name = pref.name
        
        # Archive instead of delete (preserve history)
        pref.archived = True
        self.storage.preferences.save_preference(pref)
        
        return {
            "success": True,
            "preference": pref_name,
            "message": f"✓ Archived {pref_name}. You can restore it later if needed."
        }
    
    def export_preferences(self, format: str = "json") -> str:
        """Export all preferences in user-requested format"""
        
        preferences = self.storage.preferences.get_all_preferences()
        
        if format == "json":
            import json
            export_data = {
                "exported_at": datetime.now().isoformat(),
                "total_preferences": len(preferences),
                "preferences": [
                    {
                        "name": p.name,
                        "path": p.path,
                        "confidence": p.confidence,
                        "type": p.type,
                        "uses": p.learning.use_count if p.learning else 0,
                        "satisfaction": p.learning.satisfaction_rate if p.learning else 0
                    }
                    for p in preferences
                ]
            }
            return json.dumps(export_data, indent=2)
        
        elif format == "csv":
            import csv
            from io import StringIO
            
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["Name", "Path", "Confidence", "Uses", "Satisfaction"])
            
            for p in preferences:
                writer.writerow([
                    p.name,
                    p.path,
                    f"{p.confidence:.2f}",
                    p.learning.use_count if p.learning else 0,
                    f"{p.learning.satisfaction_rate:.0%}" if p.learning else "0%"
                ])
            
            return output.getvalue()


class LearningAdjustmentPanel:
    """Panel to adjust how aggressively system learns"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.learning_mode = "normal"  # exploring, normal, committed
    
    def set_learning_mode(self, mode: str) -> Dict:
        """
        Set how fast system learns.
        
        - exploring: Slow learning (user is trying things)
        - normal: Regular learning
        - committed: Fast learning (user is decided)
        """
        
        if mode not in ["exploring", "normal", "committed"]:
            return {"error": f"Unknown mode: {mode}"}
        
        self.learning_mode = mode
        
        messages = {
            "exploring": "📍 Exploring mode: I'll learn slowly while you try different things",
            "normal": "🎯 Normal mode: I'll learn at a steady pace",
            "committed": "🔒 Committed mode: I'll quickly lock in your preferences"
        }
        
        return {
            "success": True,
            "mode": mode,
            "message": messages[mode]
        }
    
    def get_learning_mode(self) -> str:
        return self.learning_mode


if __name__ == "__main__":
    # Test control panel
    from models import Preference
    
    storage = PreferenceStorageManager("/tmp/test_control_panel")
    
    # Create test preferences
    prefs = [
        Preference(
            id="pref_tables",
            path="communication.output_format.tables",
            parent_id=None,
            name="tables",
            type="variant",
            confidence=0.85
        ),
        Preference(
            id="pref_bullets",
            path="communication.output_format.bullets",
            parent_id=None,
            name="bullets",
            type="variant",
            confidence=0.45
        )
    ]
    
    for pref in prefs:
        storage.preferences.save_preference(pref)
    
    # Test control panel
    panel = PreferenceControlPanel(storage)
    
    print("\n" + panel.display_preferences_formatted())
    
    print("\n" + panel.display_preference_detail_formatted("pref_tables"))
    
    print("\n✓ User control panel working!")
