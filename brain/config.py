"""Load and validate config.yml into typed dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import yaml


@dataclass(frozen=True)
class AgentConfig:
    """One agent's configuration from the roster."""

    name: str
    role: str
    identity_path: Path
    memory_path: Path

    @classmethod
    def from_dict(cls, name: str, data: dict) -> AgentConfig:
        return cls(
            name=name,
            role=data["role"],
            identity_path=Path(data["identity"]),
            memory_path=Path(data["memory"]),
        )


@dataclass(frozen=True)
class Config:
    """Parsed organism configuration."""

    daily_limit_usd: float
    model_default: str
    model_reasoning: str
    model_council: str
    # Elrond is the dedicated orchestrator model — replaces the rotating chair.
    # One call per cycle instead of N (deliberation) + 1 (chair) calls.
    model_elrond: str
    agents: List[AgentConfig]
    council_enabled: bool
    max_cycles_per_day: int
    telegram_enabled: bool

    @classmethod
    def from_dict(cls, data: dict) -> Config:
        budget = data.get("budget", {})
        models = data.get("models", {})
        loop = data.get("loop", {})
        comm = data.get("communication", {})

        agents_data = data.get("agents", {})
        agents = [AgentConfig.from_dict(name, agent_data) for name, agent_data in agents_data.items()]

        return cls(
            daily_limit_usd=budget.get("daily_limit_usd", 5.00),
            model_default=models.get("default", "gemini/gemini-2.5-flash"),
            model_reasoning=models.get("reasoning", "gemini/gemini-2.5-pro"),
            model_council=models.get("council", "anthropic/claude-sonnet-4-6"),
            model_elrond=models.get("elrond", "gemini/gemini-3-pro-preview"),
            agents=agents,
            council_enabled=loop.get("council_enabled", True),
            max_cycles_per_day=loop.get("max_cycles_per_day", 12),
            telegram_enabled=comm.get("telegram_enabled", True),
        )


def load_config(path: Path) -> Config:
    """Load config from a YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    return Config.from_dict(data)
