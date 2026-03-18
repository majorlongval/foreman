"""Tests for brain.config — config.yml loading and validation."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from brain.config import AgentConfig, Config, load_config

SAMPLE_CONFIG = {
    "budget": {"daily_limit_usd": 5.00},
    "models": {
        "default": "gemini/gemini-2.5-flash",
        "reasoning": "gemini/gemini-2.5-pro",
        "council": "anthropic/claude-sonnet-4-6",
    },
    "agents": {
        "gandalf": {
            "role": "scout",
            "identity": "agents/gandalf.md",
            "memory": "memory/gandalf/",
        },
        "gimli": {
            "role": "builder",
            "identity": "agents/gimli.md",
            "memory": "memory/gimli/",
        },
    },
    "loop": {
        "schedule": "every 2 hours",
        "council_enabled": True,
        "max_cycles_per_day": 12,
    },
    "communication": {"telegram_enabled": True},
}


class TestAgentConfig(unittest.TestCase):
    def test_from_dict(self):
        agent = AgentConfig.from_dict("gandalf", SAMPLE_CONFIG["agents"]["gandalf"])
        self.assertEqual(agent.name, "gandalf")
        self.assertEqual(agent.role, "scout")
        self.assertEqual(agent.identity_path, Path("agents/gandalf.md"))
        self.assertEqual(agent.memory_path, Path("memory/gandalf/"))

    def test_from_dict_preserves_name(self):
        agent = AgentConfig.from_dict("gimli", SAMPLE_CONFIG["agents"]["gimli"])
        self.assertEqual(agent.name, "gimli")
        self.assertEqual(agent.role, "builder")


class TestConfig(unittest.TestCase):
    def test_from_dict(self):
        config = Config.from_dict(SAMPLE_CONFIG)
        self.assertEqual(config.daily_limit_usd, 5.00)
        self.assertEqual(config.model_default, "gemini/gemini-2.5-flash")
        self.assertEqual(config.model_reasoning, "gemini/gemini-2.5-pro")
        self.assertEqual(config.model_council, "anthropic/claude-sonnet-4-6")
        self.assertTrue(config.council_enabled)
        self.assertEqual(config.max_cycles_per_day, 12)
        self.assertTrue(config.telegram_enabled)
        self.assertEqual(len(config.agents), 2)

    def test_agent_names(self):
        config = Config.from_dict(SAMPLE_CONFIG)
        names = [a.name for a in config.agents]
        self.assertIn("gandalf", names)
        self.assertIn("gimli", names)

    def test_agent_roster_order(self):
        config = Config.from_dict(SAMPLE_CONFIG)
        self.assertEqual(config.agents[0].name, "gandalf")
        self.assertEqual(config.agents[1].name, "gimli")

    def test_missing_budget_uses_default(self):
        data = {**SAMPLE_CONFIG, "budget": {}}
        config = Config.from_dict(data)
        self.assertEqual(config.daily_limit_usd, 5.00)

    def test_empty_agents_list(self):
        data = {**SAMPLE_CONFIG, "agents": {}}
        config = Config.from_dict(data)
        self.assertEqual(config.agents, [])

    def test_model_elrond_parsed(self):
        data = {
            **SAMPLE_CONFIG,
            "models": {
                **SAMPLE_CONFIG["models"],
                "elrond": "gemini/gemini-3-pro-preview",
            },
        }
        config = Config.from_dict(data)
        self.assertEqual(config.model_elrond, "gemini/gemini-3-pro-preview")

    def test_model_elrond_default(self):
        """model_elrond defaults to gemini-3-pro-preview when not in YAML."""
        config = Config.from_dict(SAMPLE_CONFIG)
        self.assertEqual(config.model_elrond, "gemini/gemini-3-pro-preview")


class TestLoadConfig(unittest.TestCase):
    def test_load_from_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.yml"
            config_path.write_text(yaml.dump(SAMPLE_CONFIG))
            config = load_config(config_path)
            self.assertEqual(config.daily_limit_usd, 5.00)
            self.assertEqual(len(config.agents), 2)

    def test_load_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(FileNotFoundError):
                load_config(Path(tmp_dir) / "nonexistent.yml")


if __name__ == "__main__":
    unittest.main()
