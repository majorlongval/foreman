"""Tests for cost tracking integration with memory/shared/costs/."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from brain.cost_tracking import append_cost_entry, load_today_cycles, load_today_spend


@pytest.fixture
def costs_dir(tmp_path: Path) -> Path:
    d = tmp_path / "shared" / "costs"
    d.mkdir(parents=True)
    return d


class TestLoadTodaySpend:
    def test_no_file_returns_zero(self, costs_dir: Path) -> None:
        spend = load_today_spend(costs_dir)
        assert spend == 0.0

    def test_reads_existing_entries(self, costs_dir: Path) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost_file = costs_dir / f"{today}.jsonl"
        entries = [
            {"cost_usd": 0.15, "agent": "gandalf", "action": "deliberate"},
            {"cost_usd": 0.08, "agent": "galadriel", "action": "review"},
        ]
        cost_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        spend = load_today_spend(costs_dir)
        assert abs(spend - 0.23) < 0.001


class TestAppendCostEntry:
    def test_appends_to_today_file(self, costs_dir: Path) -> None:
        append_cost_entry(
            costs_dir,
            agent="gimli",
            model="gemini/gemini-2.5-flash",
            action="implement",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.05,
        )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        content = (costs_dir / f"{today}.jsonl").read_text()
        entry = json.loads(content.strip())
        assert entry["agent"] == "gimli"
        assert entry["cost_usd"] == 0.05
        assert entry["model"] == "gemini/gemini-2.5-flash"

    def test_appends_multiple_entries(self, costs_dir: Path) -> None:
        for i in range(3):
            append_cost_entry(
                costs_dir,
                agent="gandalf",
                model="gemini/gemini-2.5-flash",
                action=f"action_{i}",
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
            )
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (costs_dir / f"{today}.jsonl").read_text().strip().split("\n")
        assert len(lines) == 3


class TestLoadTodayCycles:
    def test_no_file_returns_zero(self, costs_dir: Path) -> None:
        assert load_today_cycles(costs_dir) == 0

    def test_counts_council_entries_as_cycles(self, costs_dir: Path) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost_file = costs_dir / f"{today}.jsonl"
        entries = [
            {"action": "council", "cost_usd": 0.01},
            {"action": "execution", "cost_usd": 0.02},
            {"action": "execution", "cost_usd": 0.02},
            {"action": "council", "cost_usd": 0.01},
            {"action": "execution", "cost_usd": 0.02},
        ]
        cost_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
        # 2 council entries = 2 cycles, regardless of execution entries
        assert load_today_cycles(costs_dir) == 2

    def test_ignores_malformed_lines(self, costs_dir: Path) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        cost_file = costs_dir / f"{today}.jsonl"
        cost_file.write_text('{"action": "council", "cost_usd": 0.01}\nnot-json\n{"action": "council"}\n')
        assert load_today_cycles(costs_dir) == 2
