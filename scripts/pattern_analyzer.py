"""
pattern_analyzer.py - Discovers preference clusters and affinity patterns
"""

import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple
from datetime import datetime
from collections import defaultdict
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.models import Signal, generate_id
from scripts.storage import PreferenceStorageManager


class AffinityCalculator:
    """Calculates preference affinity (how often used together)"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def calculate_all_affinities(self) -> Dict[Tuple[str, str], float]:
        """
        Calculate affinity for all preference pairs.
        Affinity = (co_occurrence_count / total_opportunities) × association_strength
        """
        
        signals = self.storage.signals.get_all_signals()
        preferences = self.storage.preferences.get_all_preferences()
        associations = self.storage.associations.get_all_associations()
        
        # Build preference set for quick lookup
        pref_ids = {p.id for p in preferences}
        
        # Count co-occurrences
        co_occurrences = defaultdict(int)
        total_signals = len(signals)
        
        for signal in signals:
            prefs_in_signal = set(signal.preferences_used)
            
            # Count pairs
            prefs_list = sorted(list(prefs_in_signal))
            for i in range(len(prefs_list)):
                for j in range(i+1, len(prefs_list)):
                    pref_a, pref_b = prefs_list[i], prefs_list[j]
                    # Always store in sorted order for consistency
                    pair = (min(pref_a, pref_b), max(pref_a, pref_b))
                    co_occurrences[pair] += 1
        
        # Calculate affinities
        affinities = {}
        
        for pair, co_count in co_occurrences.items():
            pref_a, pref_b = pair
            
            # Base: co-occurrence frequency
            co_occurrence_rate = co_count / max(total_signals, 1)
            
            # Get association strength if exists
            assoc_strength = 0.5  # Default
            assoc = next(
                (a for a in associations 
                 if (a.from_id == pref_a and a.to_id == pref_b) or
                    (a.from_id == pref_b and a.to_id == pref_a)),
                None
            )
            
            if assoc:
                # Use average of both directions
                assoc_strength = (assoc.strength_forward + assoc.strength_backward) / 2
            
            # Combined affinity
            affinity = co_occurrence_rate * assoc_strength
            affinities[pair] = affinity
        
        return affinities
    
    def get_affinities_for_preference(self, pref_id: str) -> Dict[str, float]:
        """Get all affinities for a single preference"""
        
        all_affinities = self.calculate_all_affinities()
        pref_affinities = {}
        
        for (pref_a, pref_b), affinity in all_affinities.items():
            if pref_a == pref_id:
                pref_affinities[pref_b] = affinity
            elif pref_b == pref_id:
                pref_affinities[pref_a] = affinity
        
        return pref_affinities


class ClusterAnalyzer:
    """Analyzes and identifies preference clusters"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.affinity_calc = AffinityCalculator(storage_manager)
        self.affinity_threshold = 0.60  # Min affinity to include in cluster
    
    def find_clusters(self) -> List[Dict]:
        """
        Find preference clusters using greedy clustering algorithm.
        Returns list of clusters with metadata.
        """
        
        preferences = self.storage.preferences.get_all_preferences()
        affinities = self.affinity_calc.calculate_all_affinities()
        
        # Build affinity matrix
        pref_ids = [p.id for p in preferences]
        affinity_matrix = defaultdict(dict)
        
        for (pref_a, pref_b), affinity in affinities.items():
            affinity_matrix[pref_a][pref_b] = affinity
            affinity_matrix[pref_b][pref_a] = affinity
        
        # Greedy clustering
        clusters = []
        assigned = set()
        
        # Start with strongest affinity pairs
        sorted_pairs = sorted(
            affinities.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for (pref_a, pref_b), strength in sorted_pairs:
            if pref_a in assigned or pref_b in assigned:
                continue
            
            if strength < self.affinity_threshold:
                break  # Rest are below threshold
            
            # Start new cluster
            cluster = {pref_a, pref_b}
            assigned.add(pref_a)
            assigned.add(pref_b)
            
            # Try to expand cluster
            changed = True
            while changed:
                changed = False
                candidates = []
                
                for pref in pref_ids:
                    if pref in cluster or pref in assigned:
                        continue
                    
                    # Calculate average affinity with cluster members
                    avg_affinity = 0
                    for member in cluster:
                        pair = (min(pref, member), max(pref, member))
                        if pair in affinities:
                            avg_affinity += affinities[pair]
                    
                    avg_affinity /= len(cluster)
                    
                    if avg_affinity >= self.affinity_threshold:
                        candidates.append((pref, avg_affinity))
                
                # Add best candidate
                if candidates:
                    best_pref, best_affinity = max(candidates, key=lambda x: x[1])
                    cluster.add(best_pref)
                    assigned.add(best_pref)
                    changed = True
            
            # Calculate cluster metrics
            if len(cluster) >= 2:  # Only clusters of 2+
                clusters.append(self._calculate_cluster_metrics(
                    cluster, affinity_matrix, affinity_matrix
                ))
        
        # Add singletons if they're highly connected
        for pref_id in pref_ids:
            if pref_id not in assigned:
                affinities_for_pref = self.affinity_calc.get_affinities_for_preference(pref_id)
                if affinities_for_pref:
                    top_affinity = max(affinities_for_pref.values())
                    if top_affinity >= self.affinity_threshold:
                        clusters.append({
                            "id": generate_id("cluster"),
                            "members": [pref_id],
                            "size": 1,
                            "intra_cluster_strength": top_affinity,
                            "co_occurrence_rate": 0.5,
                            "created": datetime.now().isoformat()
                        })
        
        return sorted(clusters, key=lambda x: x["intra_cluster_strength"], reverse=True)
    
    def _calculate_cluster_metrics(self, cluster: Set[str], affinity_matrix: Dict, 
                                   unused_param: Dict) -> Dict:
        """Calculate metrics for a cluster"""
        
        # Calculate intra-cluster strength (average affinity)
        strengths = []
        members_list = list(cluster)
        
        for i, pref_a in enumerate(members_list):
            for pref_b in members_list[i+1:]:
                pair = (min(pref_a, pref_b), max(pref_a, pref_b))
                if pref_b in affinity_matrix.get(pref_a, {}):
                    strengths.append(affinity_matrix[pref_a][pref_b])
        
        intra_strength = sum(strengths) / len(strengths) if strengths else 0.5
        
        # Co-occurrence rate: how often ALL members appear together
        signals = self.storage.signals.get_all_signals()
        co_occurrence_count = 0
        
        for signal in signals:
            prefs = set(signal.preferences_used)
            if cluster.issubset(prefs):
                co_occurrence_count += 1
        
        co_occurrence_rate = co_occurrence_count / max(len(signals), 1)
        
        return {
            "id": generate_id("cluster"),
            "members": sorted(list(cluster)),
            "size": len(cluster),
            "intra_cluster_strength": intra_strength,
            "co_occurrence_rate": co_occurrence_rate,
            "created": datetime.now().isoformat()
        }
    
    def get_cluster_for_preference(self, pref_id: str) -> Dict:
        """Get the cluster a preference belongs to"""
        
        clusters = self.find_clusters()
        
        for cluster in clusters:
            if pref_id in cluster["members"]:
                return cluster
        
        return None


class ClusterTrendAnalyzer:
    """Analyzes trends within and across clusters"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.analyzer = ClusterAnalyzer(storage_manager)
    
    def get_cluster_stability(self, cluster_id: str) -> float:
        """
        Calculate cluster stability (how consistent is membership over time).
        Returns 0.0 to 1.0.
        """
        
        # This would require temporal analysis of clusters
        # For now, return 0.8 (placeholder - would be calculated from historical data)
        return 0.8
    
    def predict_cluster_growth(self, cluster_id: str) -> Dict:
        """Predict if cluster is growing/shrinking"""
        
        clusters = self.analyzer.find_clusters()
        cluster = next((c for c in clusters if c["id"] == cluster_id), None)
        
        if not cluster:
            return {}
        
        # Simplified: just return current metrics
        # Full version would do temporal analysis
        return {
            "cluster_id": cluster_id,
            "current_size": cluster["size"],
            "current_strength": cluster["intra_cluster_strength"],
            "trend": "stable",  # Placeholder
            "predicted_change": 0.0
        }


class PatternManager:
    """High-level manager for pattern analysis"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.cluster_analyzer = ClusterAnalyzer(storage_manager)
        self.trend_analyzer = ClusterTrendAnalyzer(storage_manager)
    
    def analyze_all(self) -> Dict:
        """Run complete pattern analysis"""
        
        clusters = self.cluster_analyzer.find_clusters()
        
        return {
            "clusters_found": len(clusters),
            "clusters": clusters,
            "strongest_cluster": clusters[0] if clusters else None,
            "total_strength": sum(c["intra_cluster_strength"] for c in clusters) / max(len(clusters), 1),
            "analyzed_at": datetime.now().isoformat()
        }
    
    def get_clusters(self) -> List[Dict]:
        """Get all discovered clusters"""
        return self.cluster_analyzer.find_clusters()
    
    def get_cluster_summary(self) -> str:
        """Human-readable cluster summary"""
        
        clusters = self.get_clusters()
        
        if not clusters:
            return "No preference clusters discovered yet."
        
        summary = f"Found {len(clusters)} preference clusters:\n"
        
        for i, cluster in enumerate(clusters, 1):
            members = ", ".join(cluster["members"][:3])
            if len(cluster["members"]) > 3:
                members += f", ... +{len(cluster['members'])-3} more"
            
            summary += f"\n{i}. Strength: {cluster['intra_cluster_strength']:.0%}, Co-occurrence: {cluster['co_occurrence_rate']:.0%}\n"
            summary += f"   Members: {members}\n"
        
        return summary


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_clusters")
    
    # Create test preferences and associations
    from models import Preference, Association
    
    prefs = [
        Preference(id="pref_python", path="coding.language.python", parent_id=None, name="python", type="variant", confidence=0.9),
        Preference(id="pref_pytest", path="testing.framework.pytest", parent_id=None, name="pytest", type="variant", confidence=0.85),
        Preference(id="pref_tdd", path="workflow.testing.tdd", parent_id=None, name="tdd", type="variant", confidence=0.88),
        Preference(id="pref_table", path="communication.output_format.table", parent_id=None, name="table", type="variant", confidence=0.8),
    ]
    
    for pref in prefs:
        storage.preferences.save_preference(pref)
    
    # Create associations
    assocs = [
        Association(id="a1", from_id="pref_python", to_id="pref_pytest", strength_forward=0.9, strength_backward=0.8),
        Association(id="a2", from_id="pref_pytest", to_id="pref_tdd", strength_forward=0.85, strength_backward=0.8),
        Association(id="a3", from_id="pref_python", to_id="pref_tdd", strength_forward=0.88, strength_backward=0.85),
    ]
    
    for assoc in assocs:
        storage.associations.save_association(assoc)
    
    # Create signals showing co-occurrence
    from models import Signal
    for i in range(5):
        sig = Signal(
            id=generate_id("sig"),
            timestamp=datetime.now().isoformat(),
            type="usage",
            preferences_used=["pref_python", "pref_pytest", "pref_tdd"]
        )
        storage.signals.save_signal(sig)
    
    # Analyze
    manager = PatternManager(storage)
    analysis = manager.analyze_all()
    
    print("\n📊 Cluster Analysis:\n")
    print(manager.get_cluster_summary())
