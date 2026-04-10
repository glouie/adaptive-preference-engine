"""Preference tiering engine — classifies preferences into hot/warm/cold tiers."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional

from adaptive_preference_engine.storage import PreferenceStorageManager

HOT_CONFIDENCE = 0.70
HOT_MIN_USES = 8
WARM_CONFIDENCE = 0.45
WARM_INACTIVITY_DAYS = 14
COLD_INACTIVITY_DAYS = 30


class TieringEngine:
    def __init__(self, storage: PreferenceStorageManager):
        self.storage = storage

    def recalculate(self) -> Dict[str, List[str]]:
        promoted = []
        demoted = []
        unchanged = []

        all_prefs = self.storage.preferences.get_all_preferences()

        for pref in all_prefs:
            old_tier = getattr(pref, 'tier', 'hot')

            confidence = pref.confidence
            uses = pref.learning.use_count
            pinned = getattr(pref, 'pinned', False)
            last_signal_at = getattr(pref, 'last_signal_at', None)

            new_tier = self.classify(confidence, uses, pinned, last_signal_at)

            if new_tier != old_tier:
                pref.tier = new_tier
                pref.last_updated = datetime.now().isoformat()
                self.storage.preferences.save_preference(pref)

                if self._tier_rank(new_tier) > self._tier_rank(old_tier):
                    promoted.append(pref.id)
                else:
                    demoted.append(pref.id)
            else:
                unchanged.append(pref.id)

        return {
            "promoted": promoted,
            "demoted": demoted,
            "unchanged": unchanged
        }

    def classify(self, confidence: float, uses: int, pinned: bool,
                 last_signal_at: Optional[str]) -> str:
        if pinned:
            return "hot"

        now = datetime.now()
        inactive_days = None
        if last_signal_at:
            try:
                last = datetime.fromisoformat(last_signal_at)
                inactive_days = (now - last).days
            except ValueError:
                pass

        if confidence < WARM_CONFIDENCE:
            return "cold"
        if inactive_days is not None and inactive_days >= COLD_INACTIVITY_DAYS:
            return "cold"

        if confidence >= HOT_CONFIDENCE or uses >= HOT_MIN_USES:
            if inactive_days is not None and inactive_days >= WARM_INACTIVITY_DAYS:
                return "warm"
            return "hot"

        return "warm"

    def promote(self, pref_id: str) -> bool:
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return False

        old_tier = getattr(pref, 'tier', 'hot')

        if old_tier == "cold":
            new_tier = "warm"
        elif old_tier == "warm":
            new_tier = "hot"
        else:
            return False

        pref.tier = new_tier
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)
        return True

    def demote(self, pref_id: str) -> bool:
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return False

        old_tier = getattr(pref, 'tier', 'hot')

        if old_tier == "hot":
            new_tier = "warm"
        elif old_tier == "warm":
            new_tier = "cold"
        else:
            return False

        pref.tier = new_tier
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)
        return True

    def pin(self, pref_id: str) -> bool:
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return False

        was_pinned = getattr(pref, 'pinned', False)
        old_tier = getattr(pref, 'tier', 'hot')

        if was_pinned and old_tier == "hot":
            return False

        pref.pinned = True
        pref.tier = "hot"
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)
        return True

    def unpin(self, pref_id: str) -> bool:
        pref = self.storage.preferences.get_preference(pref_id)
        if not pref:
            return False

        was_pinned = getattr(pref, 'pinned', False)

        if not was_pinned:
            return False

        pref.pinned = False

        confidence = pref.confidence
        uses = pref.learning.use_count
        last_signal_at = getattr(pref, 'last_signal_at', None)

        new_tier = self.classify(confidence, uses, False, last_signal_at)
        pref.tier = new_tier
        pref.last_updated = datetime.now().isoformat()
        self.storage.preferences.save_preference(pref)
        return True

    def get_tier_summary(self) -> Dict[str, int]:
        summary = {"hot": 0, "warm": 0, "cold": 0}

        all_prefs = self.storage.preferences.get_all_preferences()

        for pref in all_prefs:
            tier = getattr(pref, 'tier', 'hot')
            if tier in summary:
                summary[tier] += 1

        return summary

    def backfill(self) -> Dict[str, List[str]]:
        promoted = []
        demoted = []
        unchanged = []

        all_prefs = self.storage.preferences.get_all_preferences()

        for pref in all_prefs:
            old_tier = getattr(pref, 'tier', None)

            confidence = pref.confidence
            uses = pref.learning.use_count
            pinned = getattr(pref, 'pinned', False)

            new_tier = self.classify(confidence, uses, pinned, None)

            pref.tier = new_tier
            if not hasattr(pref, 'pinned'):
                pref.pinned = False
            pref.last_updated = datetime.now().isoformat()
            self.storage.preferences.save_preference(pref)

            if old_tier is None:
                unchanged.append(pref.id)
            elif new_tier != old_tier:
                if self._tier_rank(new_tier) > self._tier_rank(old_tier):
                    promoted.append(pref.id)
                else:
                    demoted.append(pref.id)
            else:
                unchanged.append(pref.id)

        return {
            "promoted": promoted,
            "demoted": demoted,
            "unchanged": unchanged
        }

    @staticmethod
    def _tier_rank(tier: str) -> int:
        return {"cold": 0, "warm": 1, "hot": 2}.get(tier, 1)
