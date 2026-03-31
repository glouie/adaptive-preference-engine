import unittest

from adaptive_preference_engine.services.habits import HabitTracker as CoreHabitTracker
from adaptive_preference_engine.services.loading import PreferenceLoader as CorePreferenceLoader
from adaptive_preference_engine.services.signals import (
    SignalProcessor as CoreSignalProcessor,
    StrengthCalculator as CoreStrengthCalculator,
)
from scripts.habit_tracker import HabitTracker
from scripts.preference_loader import PreferenceLoader
from scripts.signal_processor import SignalProcessor, StrengthCalculator


class ServiceMigrationTests(unittest.TestCase):
    def test_service_wrappers_expose_core_classes(self):
        self.assertIs(HabitTracker, CoreHabitTracker)
        self.assertIs(PreferenceLoader, CorePreferenceLoader)
        self.assertIs(SignalProcessor, CoreSignalProcessor)
        self.assertIs(StrengthCalculator, CoreStrengthCalculator)


if __name__ == "__main__":
    unittest.main()
