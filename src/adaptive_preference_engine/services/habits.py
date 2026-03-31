"""
habit_tracker.py - Habit tracking and streak management for preference learning
Addresses Priya Sharma's gap: "No habit formation mechanics — streaks, achievements, reinforcement"
"""

import json
import os
import random
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class HabitTracker:
    """Tracks usage patterns, streaks, and achievements for preference contexts"""

    # Achievement thresholds
    ACHIEVEMENTS = {
        "First Step": {"type": "usage", "threshold": 1},
        "Getting Started": {"type": "streak", "threshold": 3},
        "Building Habit": {"type": "streak", "threshold": 7},
        "Committed": {"type": "streak", "threshold": 14},
        "Expert": {"type": "streak", "threshold": 30},
        "Power User": {"type": "total_usage", "threshold": 50}
    }

    def __init__(self, base_dir: str = None):
        """Initialize habit tracker with JSONL storage"""
        if base_dir is None:
            base_dir = os.path.expanduser("~/.adaptive-cli")

        self.base_dir = Path(base_dir)
        self.habits_dir = self.base_dir / "habits"
        self.habits_dir.mkdir(parents=True, exist_ok=True)

        self.usage_file = self.habits_dir / "usage.jsonl"
        self.achievements_file = self.habits_dir / "achievements.jsonl"

        # Track last reward time per context for fatigue prevention (in-memory)
        self._last_reward_time = {}

        # Track grace period usage per context (load from file)
        self._grace_used = self._load_grace_state()

    def record_usage(self, context: str, date: str = None) -> Optional[str]:
        """
        Record a usage event for a context on a given date.
        If date is None, uses today's date.

        Returns:
            Optional variable reward message if triggered (20% chance), None otherwise
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")

        # Read existing usage records
        usage_records = self._read_usage_records()

        # Check if we already have a record for this context on this date
        context_date_key = f"{context}_{date}"
        existing_index = None
        for i, record in enumerate(usage_records):
            if record.get("context") == context and record.get("date") == date:
                existing_index = i
                break

        # Create or update record
        usage_record = {
            "context": context,
            "date": date,
            "timestamp": datetime.now().isoformat(),
            "count": 1
        }

        if existing_index is not None:
            usage_records[existing_index] = usage_record
        else:
            usage_records.append(usage_record)

        # Write back all records
        self._write_usage_records(usage_records)

        # Attempt to trigger variable reward
        return self.get_variable_reward(context)

    def _get_adaptive_trigger_rate(self, context: str) -> float:
        """
        Adaptive reward trigger rate:
        - 40% if user absent 3+ days (re-engagement)
        - 10% if a reward already fired within last hour (fatigue prevention)
        - 20% default
        """
        usage_records = self._read_usage_records()
        context_records = [r for r in usage_records if r.get("context") == context]

        if not context_records:
            # No previous usage, use default
            return 0.2

        # Sort by date descending to get last usage
        context_records.sort(key=lambda r: r.get("date"), reverse=True)
        last_usage = context_records[0]
        last_usage_date = datetime.strptime(last_usage.get("date"), "%Y-%m-%d").date()

        # Check for re-engagement (gap > 2 days)
        today = datetime.now().date()
        gap_days = (today - last_usage_date).days
        if gap_days > 2:
            return 0.4

        # Check for fatigue prevention (reward fired < 1 hour ago)
        now = datetime.now()
        last_reward_time = self._last_reward_time.get(context)
        if last_reward_time:
            elapsed = (now - last_reward_time).total_seconds()
            if elapsed < 3600:  # 1 hour in seconds
                return 0.1

        return 0.2

    def get_variable_reward(self, context: str) -> Optional[str]:
        """
        Adaptive random chance of returning a surprise reward message.
        Uses adaptive trigger rate based on engagement and fatigue metrics.

        Returns:
            One of 5 motivational messages if triggered, None otherwise
        """
        trigger_rate = self._get_adaptive_trigger_rate(context)
        if random.random() < trigger_rate:
            # Record the reward time for this context
            self._last_reward_time[context] = datetime.now()

            messages = [
                f"🔥 Hot session! Your {context} preferences are getting sharper.",
                f"✨ Insight unlocked! Pattern detected in your {context} behavior.",
                f"⚡ Power move! Your {context} preference just got 10% stronger.",
                f"🎯 On fire! You're in the top tier of {context} users.",
                f"🌟 Momentum! Keep going — your {context} habit is accelerating."
            ]
            return random.choice(messages)
        return None

    def get_cue_reminder(self, context: str) -> Optional[str]:
        """
        Return a reminder message if user hasn't logged usage for 2+ days
        (preventive window on day 2) for a context that previously had a streak of 2+.

        Returns:
            Reminder message if applicable, None otherwise
        """
        usage_records = self._read_usage_records()
        context_records = [r for r in usage_records if r.get("context") == context]

        if not context_records:
            return None

        # Sort by date descending
        context_records.sort(key=lambda r: r.get("date"), reverse=True)

        # Get current streak
        current_streak = self.get_streak(context)

        # If streak is active (> 0), don't remind
        if current_streak > 0:
            return None

        # Check if the user ever had a streak of 2+ by looking at all historical streaks
        # Look back through records to see if there was ever a 2+ day streak
        today = datetime.now().date()
        last_usage_date = None

        if context_records:
            last_usage = context_records[0]
            last_usage_date = datetime.strptime(last_usage.get("date"), "%Y-%m-%d").date()

        # If last usage was >= 2 days ago, check if they had a streak before
        if last_usage_date and (today - last_usage_date).days >= 2:
            # Count consecutive days before the break
            max_streak = 0
            current_count = 1
            for i in range(1, len(context_records)):
                prev_date = datetime.strptime(context_records[i].get("date"), "%Y-%m-%d").date()
                curr_date = datetime.strptime(context_records[i - 1].get("date"), "%Y-%m-%d").date()

                if (curr_date - prev_date).days == 1:
                    current_count += 1
                else:
                    max_streak = max(max_streak, current_count)
                    current_count = 1

            max_streak = max(max_streak, current_count)

            # If they had a 2+ streak before, remind them
            if max_streak >= 2:
                return f"Hey! You haven't logged {context} today — {max_streak}-day habit at risk. Quick update keeps it alive."

        return None

    def get_streak(self, context: str) -> int:
        """
        Calculate current consecutive-day streak for a context with 1-day grace period.

        Grace period: If the gap between consecutive days is exactly 2 (one missed day),
        the streak continues instead of breaking. A user can only use the grace period
        ONCE per streak. If the gap exceeds 2 days, the grace period resets.

        Returns 0 if no usage or if streak is truly broken (gap > 2 days).
        """
        usage_records = self._read_usage_records()

        # Filter for this context and sort by date descending
        context_records = [r for r in usage_records if r.get("context") == context]
        context_records.sort(key=lambda r: r.get("date"), reverse=True)

        if not context_records:
            return 0

        streak = 0
        today = datetime.now().date()
        current_date = today

        for record in context_records:
            record_date = datetime.strptime(record.get("date"), "%Y-%m-%d").date()

            gap_days = (current_date - record_date).days

            # If this record is today or yesterday, continue streak
            if gap_days == 0 or gap_days == 1:
                streak += 1
                current_date = record_date
            # Grace period: gap of exactly 2 days (one missed day)
            elif gap_days == 2 and not self._grace_used.get(context, False):
                # Use grace period and mark it as used
                self._grace_used[context] = True
                self._save_grace_state()
                streak += 1
                current_date = record_date
            else:
                # Streak is broken; reset grace period tracking
                self._grace_used[context] = False
                self._save_grace_state()
                break

        return streak

    def get_achievements(self, context: str) -> List[str]:
        """
        Return list of earned achievement badges for a context.
        Achievements include streaks, first usage, and total usage milestones.
        """
        achievements = []

        streak = self.get_streak(context)
        total_usage = self._get_total_usage(context)

        # Check each achievement threshold
        if total_usage >= 1:
            achievements.append("First Step")

        if streak >= 3:
            achievements.append("Getting Started")

        if streak >= 7:
            achievements.append("Building Habit")

        if streak >= 14:
            achievements.append("Committed")

        if streak >= 30:
            achievements.append("Expert")

        if total_usage >= 50:
            achievements.append("Power User")

        return achievements

    def _get_total_usage(self, context: str) -> int:
        """Get total usage count for a context"""
        usage_records = self._read_usage_records()
        context_records = [r for r in usage_records if r.get("context") == context]
        return len(context_records)

    def _get_days_since_first_usage(self, context: str) -> int:
        """Get number of days elapsed since first usage of a context"""
        usage_records = self._read_usage_records()
        context_records = [r for r in usage_records if r.get("context") == context]

        if not context_records:
            return 0

        # Find the earliest date
        context_records.sort(key=lambda r: r.get("date"))
        first_date = datetime.strptime(context_records[0].get("date"), "%Y-%m-%d").date()
        today = datetime.now().date()

        return (today - first_date).days

    def _get_active_days(self, context: str) -> int:
        """
        Count the number of UNIQUE dates in usage records for a context.

        Returns:
            Number of distinct dates on which the context was used
        """
        usage_records = self._read_usage_records()
        context_records = [r for r in usage_records if r.get("context") == context]

        # Get unique dates
        unique_dates = set(r.get("date") for r in context_records)
        return len(unique_dates)

    def get_mastery_score(self, context: str) -> int:
        """
        Calculate mastery score for a context (0-100).

        Components:
        - Consistency (40 points): min(40, current_streak / 30 * 40)
        - Volume (30 points): min(30, total_usage / 100 * 30)
        - Longevity (30 points): min(30, active_days / 90 * 30)

        Returns integer 0-100.
        """
        current_streak = self.get_streak(context)
        total_usage = self._get_total_usage(context)
        active_days = self._get_active_days(context)

        # Consistency component: max 30 days streak = max 40 points
        consistency_score = min(40, int(current_streak / 30 * 40))

        # Volume component: 100 usages = max 30 points
        volume_score = min(30, int(total_usage / 100 * 30))

        # Longevity component: 90 active days = max 30 points
        longevity_score = min(30, int(active_days / 90 * 30))

        total = consistency_score + volume_score + longevity_score

        # Save mastery snapshot
        score = min(100, total)
        self._save_mastery_snapshot(context, score)

        return score

    def format_mastery_label(self, score: int) -> str:
        """
        Return mastery label based on score.

        - 0-19: "Novice"
        - 20-39: "Beginner"
        - 40-59: "Practitioner"
        - 60-79: "Advanced"
        - 80-99: "Expert"
        - 100: "Master"
        """
        if score == 100:
            return "Master"
        elif score >= 80:
            return "Expert"
        elif score >= 60:
            return "Advanced"
        elif score >= 40:
            return "Practitioner"
        elif score >= 20:
            return "Beginner"
        else:
            return "Novice"

    def get_summary(self) -> Dict:
        """
        Return summary of all contexts with their streaks, total usages, and achievements.
        Returns dict: {context: {streak: int, total_usage: int, achievements: List[str]}}
        """
        usage_records = self._read_usage_records()

        # Group by context
        contexts_set = set(r.get("context") for r in usage_records)

        summary = {}
        for context in contexts_set:
            summary[context] = {
                "streak": self.get_streak(context),
                "total_usage": self._get_total_usage(context),
                "achievements": self.get_achievements(context)
            }

        return summary

    def format_progress_report(self) -> str:
        """
        Generate human-readable progress report for the weekly digest.
        Includes streaks, achievements, milestones, mastery scores, and variable rewards.
        """
        summary = self.get_summary()

        if not summary:
            return "No usage recorded yet. Start using preferences to build habits!"

        lines = ["### Habit Progress\n"]

        # Sort by streak length (descending)
        sorted_contexts = sorted(
            summary.items(),
            key=lambda x: x[1]["streak"],
            reverse=True
        )

        for context, stats in sorted_contexts:
            streak = stats["streak"]
            total = stats["total_usage"]
            achievements = stats["achievements"]

            # Format streak info
            if streak == 0:
                streak_str = "No current streak"
            else:
                streak_str = f"{streak}-day streak"

            # Format achievements
            if achievements:
                achievements_str = " | Badges: " + ", ".join(achievements)
            else:
                achievements_str = ""

            line = f"- **{context}**: {streak_str} ({total} total usages){achievements_str}"
            lines.append(line)

            # Add mastery score with delta
            mastery_score = self.get_mastery_score(context)
            mastery_label = self.format_mastery_label(mastery_score)
            delta = self.get_mastery_delta(context)
            delta_str = self._format_delta(delta)
            lines.append(f"  📊 Mastery: {mastery_score}/100 ({mastery_label}) {delta_str}")

            # Check for cue reminders
            reminder = self.get_cue_reminder(context)
            if reminder:
                lines.append(f"  💡 {reminder}")

        # Add milestone notifications
        milestone_msg = self.check_milestone_notification()
        if milestone_msg:
            lines.append(f"\n🎉 {milestone_msg}")

        return "\n".join(lines)

    def check_milestone_notification(self) -> Optional[str]:
        """
        Check if a new milestone was just hit (in the last usage record).
        Returns notification message if applicable, None otherwise.
        """
        usage_records = self._read_usage_records()

        if not usage_records:
            return None

        # Get the most recent usage record
        latest = max(usage_records, key=lambda r: r.get("timestamp", ""))
        context = latest.get("context")

        streak = self.get_streak(context)
        total_usage = self._get_total_usage(context)

        # Check if a milestone was just achieved
        milestone_messages = []

        if streak == 3:
            milestone_messages.append(f"3-day streak on '{context}'!")
        elif streak == 7:
            milestone_messages.append(f"You've reached a 7-day streak on '{context}'!")
        elif streak == 14:
            milestone_messages.append(f"14-day habit established for '{context}'!")
        elif streak == 30:
            milestone_messages.append(f"30-day expert milestone for '{context}'!")

        if total_usage == 50:
            milestone_messages.append(f"Power User achievement unlocked for '{context}'!")

        if milestone_messages:
            return " ".join(milestone_messages)

        return None

    def _read_usage_records(self) -> List[Dict]:
        """Read all usage records from JSONL file"""
        if not self.usage_file.exists():
            return []

        records = []
        with open(self.usage_file, 'r') as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return records

    def _write_usage_records(self, records: List[Dict]) -> None:
        """Write all usage records to JSONL file"""
        self.usage_file.unlink(missing_ok=True)
        with open(self.usage_file, 'a') as f:
            for record in records:
                f.write(json.dumps(record) + '\n')

    def _get_grace_state_file(self) -> Path:
        """Return path to grace state JSON file"""
        return self.habits_dir / "grace_state.json"

    def _load_grace_state(self) -> Dict[str, bool]:
        """
        Load grace period state from file.

        Returns:
            Dict mapping context to boolean (whether grace was used)
        """
        grace_file = self._get_grace_state_file()
        if not grace_file.exists():
            return {}

        try:
            with open(grace_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save_grace_state(self) -> None:
        """Write grace period state to file"""
        grace_file = self._get_grace_state_file()
        with open(grace_file, 'w') as f:
            json.dump(self._grace_used, f)

    def _get_mastery_history_file(self) -> Path:
        """Return path to mastery history JSONL file"""
        return self.base_dir / "mastery_history.jsonl"

    def _save_mastery_snapshot(self, context: str, score: int) -> None:
        """
        Append mastery score snapshot to history file.

        Args:
            context: Preference context
            score: Mastery score (0-100)
        """
        history_file = self._get_mastery_history_file()
        today = datetime.now().strftime("%Y-%m-%d")

        # Check if we already saved a snapshot for this context today
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    for line in f:
                        if line.strip():
                            try:
                                record = json.loads(line)
                                if (record.get("context") == context and
                                    record.get("date") == today):
                                    # Already saved today, skip
                                    return
                            except json.JSONDecodeError:
                                continue
            except IOError:
                pass

        # Append new snapshot
        snapshot = {
            "context": context,
            "score": score,
            "date": today
        }
        with open(history_file, 'a') as f:
            f.write(json.dumps(snapshot) + '\n')

    def _get_previous_mastery(self, context: str, days_ago: int = 7) -> Optional[int]:
        """
        Find mastery score from approximately days_ago days ago for a context.

        Args:
            context: Preference context
            days_ago: Number of days back to search for

        Returns:
            Mastery score if found, None otherwise
        """
        history_file = self._get_mastery_history_file()
        if not history_file.exists():
            return None

        target_date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
        closest_record = None
        closest_diff = None

        try:
            with open(history_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line)
                            if record.get("context") == context:
                                record_date = datetime.strptime(record.get("date"), "%Y-%m-%d").date()
                                target = datetime.strptime(target_date, "%Y-%m-%d").date()
                                diff = abs((record_date - target).days)

                                if closest_diff is None or diff < closest_diff:
                                    closest_diff = diff
                                    closest_record = record
                        except json.JSONDecodeError:
                            continue
        except IOError:
            return None

        return closest_record.get("score") if closest_record else None

    def get_mastery_delta(self, context: str, days_ago: int = 7) -> Optional[int]:
        """
        Calculate change in mastery score over the last days_ago days.

        Args:
            context: Preference context
            days_ago: Number of days to compare against

        Returns:
            Difference (current - previous), or None if no history
        """
        current_score = self.get_mastery_score(context)
        previous_score = self._get_previous_mastery(context, days_ago)

        if previous_score is None:
            return None

        return current_score - previous_score

    def _format_delta(self, delta: Optional[int]) -> str:
        """
        Format delta for display in progress report.

        Args:
            delta: Mastery delta or None

        Returns:
            Formatted string like "↑ +5 pts" or "↓ 3 pts" or ""
        """
        if delta is None or delta == 0:
            return ""
        elif delta > 0:
            return f"↑ +{delta} pts"
        else:
            return f"↓ {delta} pts"


class WeeklyDigestEnhanced:
    """Enhanced weekly digest that integrates habit tracking with preference stats"""

    def __init__(self, habit_tracker: HabitTracker, preference_manager=None, friction_metrics=None):
        """
        Initialize enhanced digest with habit tracker and optional preference manager.

        Args:
            habit_tracker: HabitTracker instance
            preference_manager: PreferenceStorageManager instance (optional)
            friction_metrics: Friction metrics instance with get_summary() method (optional)
        """
        self.habit_tracker = habit_tracker
        self.preference_manager = preference_manager
        self.friction_metrics = friction_metrics

    def generate_digest(self) -> str:
        """
        Generate complete weekly digest combining habit progress and preference stats.
        """
        sections = []

        # Title
        sections.append("## Weekly Preference & Habit Digest")
        sections.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

        # Habit progress section
        habit_report = self.habit_tracker.format_progress_report()
        sections.append(habit_report)

        # Preference stats section (if manager provided)
        if self.preference_manager:
            sections.append(self._format_preference_stats())

        # Friction metrics section (if provided)
        if self.friction_metrics:
            sections.append(self._format_friction_stats())

        # Summary and recommendations
        sections.append(self._format_recommendations())

        return "\n\n".join(sections)

    def _format_preference_stats(self) -> str:
        """Format preference statistics for digest"""
        try:
            stats = self.preference_manager.get_storage_info()

            lines = ["### Preference Statistics\n"]
            lines.append(f"- Total preferences: {stats.get('preferences_count', 0)}")
            lines.append(f"- Associations tracked: {stats.get('associations_count', 0)}")
            lines.append(f"- Context stacks: {stats.get('contexts_count', 0)}")
            lines.append(f"- Behavioral signals: {stats.get('signals_count', 0)}")

            return "\n".join(lines)
        except Exception:
            return "### Preference Statistics\n*No statistics available*"

    def _format_friction_stats(self) -> str:
        """Format friction metrics for digest"""
        try:
            summary = self.friction_metrics.get_summary()

            lines = ["### Performance Metrics\n"]
            lines.append(f"- Correction success rate: {summary.get('correction_success_rate', 0)}%")
            lines.append(f"- Feedback success rate: {summary.get('feedback_success_rate', 0)}%")
            lines.append(f"- Avg processing time: {summary.get('avg_processing_time', 0)}ms")

            return "\n".join(lines)
        except Exception:
            return "### Performance Metrics\n*No metrics available*"

    def _format_recommendations(self) -> str:
        """Format recommendations based on habit progress"""
        summary = self.habit_tracker.get_summary()

        lines = ["### Recommendations\n"]

        if not summary:
            lines.append("- Start using preferences to build habits and unlock achievements!")
        else:
            # Find contexts without streaks
            inactive = [ctx for ctx, stats in summary.items() if stats["streak"] == 0]

            if inactive:
                lines.append(f"- Consider revisiting these contexts: {', '.join(inactive[:3])}")

            # Find contexts with high streaks
            active = sorted(
                [(ctx, stats) for ctx, stats in summary.items() if stats["streak"] > 0],
                key=lambda x: x[1]["streak"],
                reverse=True
            )

            if active:
                top_context = active[0]
                lines.append(f"- Great work on '{top_context[0]}' — keep the momentum going!")

        return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    tracker = HabitTracker("/tmp/test_habits")

    # Simulate usage over several days
    for i in range(10):
        date = (datetime.now() - timedelta(days=10-i)).strftime("%Y-%m-%d")
        tracker.record_usage("coding", date)

    for i in range(5):
        date = (datetime.now() - timedelta(days=5-i)).strftime("%Y-%m-%d")
        tracker.record_usage("writing", date)

    # Get streak and achievements
    print("Coding streak:", tracker.get_streak("coding"))
    print("Coding achievements:", tracker.get_achievements("coding"))
    print("Writing streak:", tracker.get_streak("writing"))
    print("Writing achievements:", tracker.get_achievements("writing"))

    # Get summary
    print("\nSummary:", tracker.get_summary())

    # Get progress report
    print("\nProgress Report:")
    print(tracker.format_progress_report())

    # Check milestone
    print("\nMilestone:", tracker.check_milestone_notification())
