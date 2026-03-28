"""
trend_predictor.py - Forecasts preference strength evolution and trends
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))

from models import Association, generate_id
from storage import PreferenceStorageManager


class VelocityCalculator:
    """Calculates preference strength velocity (rate of change)"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
    
    def calculate_weekly_velocity(self, assoc_id: str) -> Dict:
        """
        Calculate weekly velocity for an association.
        
        Returns velocity metrics:
        - velocity: % change per week
        - trend: direction (increasing/decreasing/stable)
        - acceleration: is velocity itself increasing?
        """
        
        assoc = self.storage.associations.get_association(assoc_id)
        if not assoc:
            return {}
        
        # Get weekly usage history
        weekly_usage_forward = assoc.learning_forward.weekly_usage
        weekly_usage_backward = assoc.learning_backward.weekly_usage
        
        if not weekly_usage_forward:
            return {
                "velocity": 0.0,
                "trend": "insufficient_data",
                "acceleration": 0.0,
                "confidence": 0.0
            }
        
        # Calculate deltas (week-to-week changes)
        deltas_forward = []
        for i in range(1, len(weekly_usage_forward)):
            if weekly_usage_forward[i-1] > 0:
                delta = (weekly_usage_forward[i] - weekly_usage_forward[i-1]) / weekly_usage_forward[i-1]
                deltas_forward.append(delta)
        
        if not deltas_forward:
            return {
                "velocity": 0.0,
                "trend": "stable",
                "acceleration": 0.0,
                "confidence": 0.3
            }
        
        # Calculate average velocity
        avg_velocity = sum(deltas_forward) / len(deltas_forward)
        
        # Detect trend
        trend = self._detect_trend(avg_velocity)
        
        # Calculate acceleration (change in velocity)
        acceleration = 0.0
        if len(deltas_forward) >= 2:
            recent_avg = sum(deltas_forward[-2:]) / 2
            earlier_avg = sum(deltas_forward[:2]) / 2
            acceleration = recent_avg - earlier_avg
        
        # Confidence based on data points
        confidence = min(len(deltas_forward) / 8, 1.0)  # Saturate at 8 weeks
        
        return {
            "velocity": avg_velocity,
            "trend": trend,
            "acceleration": acceleration,
            "confidence": confidence,
            "data_points": len(deltas_forward),
            "weekly_history": weekly_usage_forward[-8:]  # Last 8 weeks
        }
    
    def _detect_trend(self, velocity: float) -> str:
        """Detect trend direction"""
        
        if velocity > 0.20:
            return "strongly_increasing"
        elif velocity > 0.10:
            return "increasing"
        elif velocity < -0.20:
            return "strongly_decreasing"
        elif velocity < -0.10:
            return "decreasing"
        else:
            return "stable"


class TrendForecaster:
    """Forecasts preference strength evolution"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.velocity_calc = VelocityCalculator(storage_manager)
    
    def forecast_strength(self,
                         assoc_id: str,
                         weeks_ahead: int = 4) -> Dict:
        """
        Forecast association strength N weeks ahead.
        Uses linear extrapolation with trend adjustment.
        """
        
        assoc = self.storage.associations.get_association(assoc_id)
        if not assoc:
            return {}
        
        # Get velocity
        velocity_metrics = self.velocity_calc.calculate_weekly_velocity(assoc_id)
        
        if velocity_metrics.get("trend") == "insufficient_data":
            return {
                "assoc_id": assoc_id,
                "status": "insufficient_data",
                "reason": "Not enough historical data"
            }
        
        velocity = velocity_metrics["velocity"]
        trend = velocity_metrics["trend"]
        
        # Apply trend multiplier
        trend_multiplier = {
            "strongly_increasing": 1.2,
            "increasing": 1.05,
            "stable": 1.0,
            "decreasing": 0.85,
            "strongly_decreasing": 0.7
        }.get(trend, 1.0)
        
        adjusted_velocity = velocity * trend_multiplier
        
        # Forecast strengths
        current_forward = assoc.strength_forward
        current_backward = assoc.strength_backward
        
        forecast_forward = min(current_forward + (adjusted_velocity * weeks_ahead), 1.0)
        forecast_backward = min(current_backward + (adjusted_velocity * weeks_ahead), 1.0)
        
        # Calculate ETA to solidification (0.90 confidence)
        target_strength = 0.90
        
        eta_weeks_forward = (target_strength - current_forward) / max(adjusted_velocity, 0.01)
        eta_weeks_backward = (target_strength - current_backward) / max(adjusted_velocity, 0.01)
        
        # Only return positive ETAs
        eta_forward = eta_weeks_forward if eta_weeks_forward > 0 else None
        eta_backward = eta_weeks_backward if eta_weeks_backward > 0 else None
        
        now = datetime.now()
        eta_forward_date = (now + timedelta(weeks=eta_forward)).isoformat() if eta_forward else None
        eta_backward_date = (now + timedelta(weeks=eta_backward)).isoformat() if eta_backward else None
        
        return {
            "id": generate_id("forecast"),
            "assoc_id": assoc_id,
            "current_strength_forward": current_forward,
            "current_strength_backward": current_backward,
            "velocity": velocity,
            "trend": trend,
            "acceleration": velocity_metrics["acceleration"],
            "forecast": {
                "weeks_ahead": weeks_ahead,
                "projected_strength_forward": forecast_forward,
                "projected_strength_backward": forecast_backward,
                "confidence": velocity_metrics["confidence"]
            },
            "eta_solidification": {
                "forward": {
                    "weeks": round(eta_forward, 1) if eta_forward else None,
                    "eta_date": eta_forward_date,
                    "will_solidify": eta_forward is not None and eta_forward < 52
                },
                "backward": {
                    "weeks": round(eta_backward, 1) if eta_backward else None,
                    "eta_date": eta_backward_date,
                    "will_solidify": eta_backward is not None and eta_backward < 52
                }
            },
            "created": datetime.now().isoformat()
        }
    
    def forecast_all_associations(self) -> List[Dict]:
        """Forecast all associations"""
        
        associations = self.storage.associations.get_all_associations()
        forecasts = []
        
        for assoc in associations:
            forecast = self.forecast_strength(assoc.id)
            if forecast and forecast.get("status") != "insufficient_data":
                forecasts.append(forecast)
        
        # Sort by highest velocity (most interesting trends)
        return sorted(
            forecasts,
            key=lambda x: abs(x.get("velocity", 0)),
            reverse=True
        )
    
    def get_strongest_trends(self, top_n: int = 10) -> List[Dict]:
        """Get the top N associations by trend strength"""
        
        forecasts = self.forecast_all_associations()
        
        # Score by: velocity + confidence
        for forecast in forecasts:
            forecast["trend_score"] = (
                abs(forecast.get("velocity", 0)) *
                forecast.get("forecast", {}).get("confidence", 0.5)
            )
        
        return sorted(
            forecasts,
            key=lambda x: x.get("trend_score", 0),
            reverse=True
        )[:top_n]
    
    def get_eta_summary(self) -> str:
        """Get human-readable ETA summary"""
        
        forecasts = self.forecast_all_associations()
        
        # Find associations close to solidification
        near_solidification = [
            f for f in forecasts
            if f.get("eta_solidification", {}).get("forward", {}).get("weeks") and
               f.get("eta_solidification", {}).get("forward", {}).get("weeks") < 4
        ]
        
        if not near_solidification:
            return "No associations near solidification."
        
        summary = "Associations approaching solidification (0.90 confidence):\n\n"
        
        for forecast in near_solidification[:5]:
            assoc_id = forecast["assoc_id"]
            weeks = forecast["eta_solidification"]["forward"]["weeks"]
            
            summary += f"• {assoc_id}\n"
            summary += f"  ETA: {weeks} weeks\n"
            summary += f"  Trend: {forecast['trend']}\n"
            summary += f"  Current: {forecast['current_strength_forward']:.0%}\n\n"
        
        return summary


class TrendMonitor:
    """Monitors trends over time"""
    
    def __init__(self, storage_manager: PreferenceStorageManager):
        self.storage = storage_manager
        self.forecaster = TrendForecaster(storage_manager)
    
    def check_trend_changes(self) -> List[Dict]:
        """
        Detect when trends have changed.
        (Requires storing previous forecasts - placeholder for now)
        """
        
        # This would compare current forecasts with previous ones
        # For now, just return current state
        return self.forecaster.get_strongest_trends(top_n=5)
    
    def alert_on_acceleration(self, threshold: float = 0.15) -> List[Dict]:
        """Alert when acceleration exceeds threshold"""
        
        forecasts = self.forecaster.forecast_all_associations()
        accelerating = []
        
        for forecast in forecasts:
            acceleration = forecast.get("acceleration", 0)
            if abs(acceleration) > threshold:
                forecast["alert_type"] = "high_acceleration"
                accelerating.append(forecast)
        
        return sorted(
            accelerating,
            key=lambda x: abs(x.get("acceleration", 0)),
            reverse=True
        )


if __name__ == "__main__":
    # Quick test
    storage = PreferenceStorageManager("/tmp/test_trends")
    
    # Create test association with history
    from models import Association, AssociationLearning
    
    # Create association with 8-week history
    learning_forward = AssociationLearning(
        use_count=40,
        satisfaction_rate=0.85,
        trend="increasing",
        velocity=0.12,
        weekly_usage=[5, 6, 7, 8, 9, 11, 13, 15]  # Growing trend
    )
    
    learning_backward = AssociationLearning(
        use_count=20,
        satisfaction_rate=0.75,
        trend="stable",
        velocity=0.0,
        weekly_usage=[2, 2, 3, 2, 3, 2, 3, 2]  # Stable
    )
    
    assoc = Association(
        id="test_assoc",
        from_id="pref_a",
        to_id="pref_b",
        strength_forward=0.75,
        strength_backward=0.60,
        learning_forward=learning_forward,
        learning_backward=learning_backward
    )
    
    storage.associations.save_association(assoc)
    
    # Forecast
    forecaster = TrendForecaster(storage)
    forecast = forecaster.forecast_strength("test_assoc", weeks_ahead=4)
    
    print("\n📈 Trend Forecast:\n")
    print(f"Current strength: {forecast['current_strength_forward']:.0%}")
    print(f"Trend: {forecast['trend']}")
    print(f"Velocity: {forecast['velocity']:.0%} per week")
    print(f"Acceleration: {forecast['acceleration']:.0%}")
    print(f"\nForecast (4 weeks ahead):")
    print(f"  Strength: {forecast['forecast']['projected_strength_forward']:.0%}")
    print(f"  Confidence: {forecast['forecast']['confidence']:.0%}")
    print(f"\nETA to solidification:")
    eta_info = forecast['eta_solidification']['forward']
    if eta_info['weeks']:
        print(f"  {eta_info['weeks']} weeks ({eta_info['eta_date'][:10]})")
    else:
        print(f"  Won't solidify at current rate")
