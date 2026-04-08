"""Tests for APEConfig. Run: pytest tests/test_config.py -v"""
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from scripts.config import APEConfig


@pytest.fixture
def cfg_dir(tmp_path):
    return tmp_path


class TestAPEConfig:
    def test_defaults_without_config_file(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.knowledge") == 3000
        assert cfg.get("token_budgets.preferences") == 500
        assert cfg.get("pruning.convention") == 120

    def test_config_json_overrides_defaults(self, cfg_dir):
        (cfg_dir / "config.json").write_text(json.dumps({"token_budgets": {"knowledge": 5000}}))
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.knowledge") == 5000
        assert cfg.get("token_budgets.preferences") == 500

    def test_get_missing_key_returns_default(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("nonexistent.key", 42) == 42

    def test_save_defaults_creates_file(self, cfg_dir):
        APEConfig.save_defaults(str(cfg_dir))
        assert (cfg_dir / "config.json").exists()
        data = json.loads((cfg_dir / "config.json").read_text())
        assert "token_budgets" in data
        assert "pruning" in data

    def test_save_defaults_does_not_overwrite(self, cfg_dir):
        (cfg_dir / "config.json").write_text(json.dumps({"custom": True}))
        APEConfig.save_defaults(str(cfg_dir))
        assert json.loads((cfg_dir / "config.json").read_text()) == {"custom": True}

    def test_partition_budget_default(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.partition") == 1000

    def test_context_injection_budget_default(self, cfg_dir):
        cfg = APEConfig.load(str(cfg_dir))
        assert cfg.get("token_budgets.context_injection") == 2000
