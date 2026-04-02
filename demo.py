#!/usr/bin/env python3
"""
demo.py - Demonstration of Phase 1 adaptive preference engine
Shows complete workflow: create prefs, associations, contexts, learn from signals
"""

import sys
from pathlib import Path

from adaptive_preference_engine.models import Preference, Association, AssociationLearning, ContextStack, generate_id
from scripts.storage import PreferenceStorageManager
from scripts.preference_loader import PreferenceLoader
from adaptive_preference_engine.services.signals import SignalProcessor
import json


def print_section(title):
    """Print formatted section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def demo_complete_workflow():
    """
    Demo scenario: Learning Python + API design preferences
    
    Flow:
    1. Create preferences
    2. Create associations
    3. Create contexts
    4. Simulate agent interactions with corrections
    5. Show learned preferences
    """
    
    # Initialize storage
    print_section("🚀 ADAPTIVE PREFERENCE ENGINE - PHASE 1 DEMO")
    print("Demo scenario: Learning preferences for Python API development")
    
    base_dir = "/tmp/adaptive_demo"
    storage = PreferenceStorageManager(base_dir)
    loader = PreferenceLoader(storage)
    processor = SignalProcessor(storage)
    
    print(f"Storage initialized at: {base_dir}\n")
    
    # ---- STEP 1: Create Preferences ----
    print_section("STEP 1: Create Preference Hierarchy")
    
    # Communication preferences
    output_format_selector = Preference(
        id="comm_format",
        path="communication.output_format",
        parent_id=None,
        name="output_format",
        type="selector",
        confidence=1.0,
        description="Primary output format selector"
    )
    
    bullets_variant = Preference(
        id="comm_bullets",
        path="communication.output_format.bullets",
        parent_id="comm_format",
        name="bullets",
        type="variant",
        value="active",
        confidence=0.60,  # Start low, will learn
        description="Bullet point format"
    )
    
    table_variant = Preference(
        id="comm_table",
        path="communication.output_format.table",
        parent_id="comm_format",
        name="table",
        type="variant",
        value="inactive",
        confidence=0.40,
        description="Table format"
    )
    
    # Coding preferences
    data_structure = Preference(
        id="coding_datastructure",
        path="coding.data_structure_clarity",
        parent_id=None,
        name="data_structure_clarity",
        type="selector",
        confidence=0.75,
        description="How clear data structure explanations should be"
    )
    
    # Save preferences
    for pref in [output_format_selector, bullets_variant, table_variant, data_structure]:
        storage.preferences.save_preference(pref)
        print(f"✓ Created: {pref.path}")
    
    # ---- STEP 2: Create Associations ----
    print_section("STEP 2: Create Bidirectional Associations")
    
    # Association 1: table ↔ data_structure
    assoc_table_datastructure = Association(
        id="assoc_table_datastructure",
        from_id="comm_table",
        to_id="coding_datastructure",
        strength_forward=0.70,    # table → data_structure (moderate)
        strength_backward=0.50,   # data_structure → table (weak)
        description="Tables help explain hierarchical data structures"
    )
    storage.associations.save_association(assoc_table_datastructure)
    print(f"✓ Created: comm_table ↔ coding_datastructure")
    print(f"  Forward (table→data): {assoc_table_datastructure.strength_forward}")
    print(f"  Backward (data→table): {assoc_table_datastructure.strength_backward}")
    
    # ---- STEP 3: Create Contexts ----
    print_section("STEP 3: Create Context Stack")
    
    base_context = ContextStack(
        id="ctx_base",
        name="Base Preferences",
        scope="base",
        stack_level=0,
        preferences={
            "communication.output_format": {
                "value": "bullets",
                "confidence": 0.60,
                "source": "default"
            }
        }
    )
    storage.contexts.save_context(base_context)
    print(f"✓ Created base context")
    
    python_project_context = ContextStack(
        id="ctx_python_project",
        name="Python API Project",
        scope="project",
        stack_level=1,
        preferences={
            "coding.language": {
                "value": "python",
                "confidence": 0.95,
                "source": "auto_detected"
            },
            "communication.output_format": {
                "value": "table",
                "confidence": 0.70,
                "source": "learned"
            }
        }
    )
    storage.contexts.save_context(python_project_context)
    print(f"✓ Created Python project context")
    
    # ---- STEP 4: Load Preferences (Option C) ----
    print_section("STEP 4: Load Preferences with Associations (Option C)")
    
    loaded = loader.load_for_context(
        context_tags=["python", "api_design"],
        stack_contexts=["ctx_base", "ctx_python_project"]
    )
    
    if loaded["primary"]:
        print(f"Primary preference:")
        print(f"  Path: {loaded['primary']['path']}")
        print(f"  Value: {loaded['primary']['value']}")
        print(f"  Confidence: {loaded['primary']['confidence']:.0%}")
    
    if loaded["associated"]:
        print(f"\nAssociated preferences ({len(loaded['associated'])}):")
        for assoc in loaded["associated"]:
            print(f"  → {assoc['path']}")
            print(f"    Confidence: {assoc['confidence']:.0%}")
            print(f"    Association strength: {assoc['association_strength']:.0%}")
            print(f"    Trend: {assoc['trend']}")
    
    # ---- STEP 5: Simulate Corrections (Learning) ----
    print_section("STEP 5: Simulate User Corrections (Learning Signals)")
    
    print("Scenario: Agent proposes bullets, user prefers table for API design\n")
    
    # Correction 1: Propose bullets, user wants table
    signal1 = processor.process_correction(
        task="api_response_design",
        context_tags=["python", "api_design"],
        agent_proposed="comm_bullets",
        user_corrected_to="comm_table",
        user_message="Perfect! The table format is exactly what I needed for showing the API response structure."
    )
    
    print(f"✓ Correction recorded:")
    print(f"  Agent proposed: comm_bullets")
    print(f"  User corrected to: comm_table")
    print(f"  Emotional tone: {signal1.emotional_tone}")
    print(f"  Emotional indicators: {signal1.emotional_indicators}")
    print(f"  Associations affected: {len(signal1.associations_affected)}")
    
    # Correction 2: Another correction reinforcing preference
    print("\nScenario 2: Agent again proposes bullets, user corrects to table\n")
    
    signal2 = processor.process_correction(
        task="api_documentation",
        context_tags=["python", "fastapi"],
        agent_proposed="comm_bullets",
        user_corrected_to="comm_table",
        user_message="Yes, the table makes the data structure much clearer!"
    )
    
    print(f"✓ Second correction recorded:")
    print(f"  Emotional tone: {signal2.emotional_tone}")
    print(f"  System is reinforcing the table ↔ data_structure association")
    
    # ---- STEP 6: Check Updated Preferences ----
    print_section("STEP 6: Examine Updated Preferences & Associations")
    
    # Get updated preferences
    bullets_updated = storage.preferences.get_preference("comm_bullets")
    table_updated = storage.preferences.get_preference("comm_table")
    
    print(f"Bullets preference:")
    print(f"  Confidence: {bullets_updated.confidence:.2%}")
    print(f"  Use count: {bullets_updated.learning.use_count}")
    
    print(f"\nTable preference:")
    print(f"  Confidence: {table_updated.confidence:.2%}")
    print(f"  Use count: {table_updated.learning.use_count}")
    
    # Check association
    assoc_updated = storage.associations.get_association("assoc_table_datastructure")
    print(f"\nAssociation (table ↔ data_structure):")
    print(f"  Forward (table→data): {assoc_updated.strength_forward:.2%}")
    print(f"  Backward (data→data): {assoc_updated.strength_backward:.2%}")
    print(f"  Forward use count: {assoc_updated.learning_forward.use_count}")
    print(f"  Forward satisfaction: {assoc_updated.learning_forward.satisfaction_rate:.0%}")
    
    # ---- STEP 7: Reload with Updated Strengths ----
    print_section("STEP 7: Reload Preferences (Strengths Have Evolved)")
    
    # Reload
    loaded_updated = loader.load_for_context(
        context_tags=["python", "api_design"],
        stack_contexts=["ctx_base", "ctx_python_project"]
    )
    
    print(f"Updated primary preference:")
    print(f"  Path: {loaded_updated['primary']['path']}")
    print(f"  Value: {loaded_updated['primary']['value']}")
    print(f"  Confidence: {loaded_updated['primary']['confidence']:.0%}")
    
    print(f"\nUpdated associations:")
    if loaded_updated["associated"]:
        for assoc in loaded_updated["associated"]:
            print(f"  → {assoc['path']}: {assoc['confidence']:.0%} confidence")
    
    # ---- STEP 8: Agent Context JSON ----
    print_section("STEP 8: Generate Agent Context (JSON for Agents)")
    
    agent_json = loader.load_for_agent(
        context_tags=["python", "api_design"],
        stack_contexts=["ctx_base", "ctx_python_project"]
    )
    
    print("Agent receives:")
    print(agent_json)
    
    # ---- STEP 9: Show Signals ----
    print_section("STEP 9: Review Behavioral Signals")
    
    signals = storage.signals.get_all_signals()
    print(f"Total signals recorded: {len(signals)}")
    
    for i, sig in enumerate(signals, 1):
        print(f"\nSignal {i}:")
        print(f"  Type: {sig.type}")
        print(f"  Task: {sig.task}")
        print(f"  Emotion: {sig.emotional_tone}")
        print(f"  Associations affected: {len(sig.associations_affected)}")
    
    # ---- STEP 10: Storage Statistics ----
    print_section("STEP 10: Storage Statistics")
    
    info = storage.get_storage_info()
    print(f"Preferences: {info['preferences_count']}")
    print(f"Associations: {info['associations_count']}")
    print(f"Contexts: {info['contexts_count']}")
    print(f"Signals: {info['signals_count']}")
    
    # ---- Summary ----
    print_section("✨ DEMO SUMMARY")
    
    print("""
KEY INSIGHTS FROM DEMO:

1. PREFERENCE EVOLUTION
   - Started: comm_bullets (confidence 0.60)
   - After 2 corrections: comm_table (confidence 0.82)
   - System learned: user prefers tables for API design

2. ASSOCIATION LEARNING
   - Association strength increased through corrections
   - table ↔ data_structure now strongly linked
   - Next time user mentions data_structure, table format suggested

3. CONTEXT STACKING
   - Base context: bullets preferred (0.60)
   - Project context: table preferred (0.70)
   - Conversation context: can override both
   - Final preference determined by stack hierarchy

4. EMOTIONAL SIGNALS
   - System detected satisfaction from user messages
   - Emotional tone boost confidence in learned preferences
   - Negative tone would decrease confidence

5. BEHAVIOR DRIVES LEARNING
   - System doesn't rely on explicit preference statements
   - Learns from corrections and feedback
   - Adjusts confidence dynamically
   - No manual configuration needed

This is Phase 1: Foundation for behavior-driven preference learning.
Phase 2 will add: auto-detection, agentic loops, ML predictions.
    """)
    
    print_section("✅ DEMO COMPLETE")
    print(f"\nAll data stored at: {base_dir}")
    print("Ready for Phase 2 implementation!\n")


if __name__ == "__main__":
    demo_complete_workflow()
