"""Tests for brain.council — agent deliberation and chair decision."""

import pytest
from unittest.mock import MagicMock, patch, call
from pathlib import Path
from brain.council import (
    AgentPerspective,
    CouncilResult,
    get_chair_index,
    save_chair_index,
    run_council,
)
from brain.config import Config, AgentConfig
from brain.survey import SurveyResult


def make_agents() -> list[AgentConfig]:
    return [
        AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
        AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        AgentConfig("galadriel", "critic", Path("agents/galadriel.md"), Path("memory/galadriel/")),
        AgentConfig("samwise", "gardener", Path("agents/samwise.md"), Path("memory/samwise/")),
    ]


def make_survey() -> SurveyResult:
    return SurveyResult(
        budget_limit=5.0,
        budget_spent=1.0,
        open_issues=["#95: Auto-promote"],
        open_prs=[],
        recent_incidents=[],
        shared_decisions=[],
        journal_last_entry=None,
    )


class TestChairRotation:
    def test_get_chair_index_no_file(self, tmp_path: Path) -> None:
        index = get_chair_index(tmp_path / "journal")
        assert index == 0

    def test_save_and_load_chair_index(self, tmp_path: Path) -> None:
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        save_chair_index(journal_dir, 2)
        assert get_chair_index(journal_dir) == 2

    def test_chair_rotates(self) -> None:
        agents = make_agents()
        # After chair index 2 (galadriel), next should be 3 (samwise)
        next_index = (2 + 1) % len(agents)
        assert next_index == 3
        assert agents[next_index].name == "samwise"

    def test_chair_wraps_around(self) -> None:
        agents = make_agents()
        next_index = (3 + 1) % len(agents)
        assert next_index == 0
        assert agents[next_index].name == "gandalf"


class TestAgentPerspective:
    def test_dataclass_fields(self) -> None:
        p = AgentPerspective(
            agent_name="gandalf",
            perspective="We should explore new models.",
            proposed_action="Research available Gemini models",
        )
        assert p.agent_name == "gandalf"
        assert "explore" in p.perspective.lower()


class TestCouncilResult:
    def test_has_required_fields(self) -> None:
        result = CouncilResult(
            perspectives=[
                AgentPerspective("gandalf", "Explore", "Research"),
            ],
            chair_name="gandalf",
            decision="Research new models",
            action_plan="Use scout tools to list available models",
        )
        assert result.chair_name == "gandalf"
        assert result.decision == "Research new models"


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        from brain.council import _parse_json_response
        result = _parse_json_response('{"perspective": "test", "proposed_action": "do X"}')
        assert result["perspective"] == "test"

    def test_markdown_fenced_json(self) -> None:
        from brain.council import _parse_json_response
        text = '```json\n{"perspective": "test"}\n```'
        result = _parse_json_response(text)
        assert result["perspective"] == "test"

    def test_markdown_fenced_no_lang(self) -> None:
        from brain.council import _parse_json_response
        text = '```\n{"perspective": "test"}\n```'
        result = _parse_json_response(text)
        assert result["perspective"] == "test"

    def test_text_before_json(self) -> None:
        from brain.council import _parse_json_response
        text = 'Here is my analysis:\n{"perspective": "test", "proposed_action": "do X"}'
        result = _parse_json_response(text)
        assert result["perspective"] == "test"

    def test_text_surrounding_json(self) -> None:
        from brain.council import _parse_json_response
        text = 'Let me think...\n{"decision": "build", "action_plan": "step 1"}\nDone!'
        result = _parse_json_response(text)
        assert result["decision"] == "build"

    def test_malformed_json_raises(self) -> None:
        from brain.council import _parse_json_response
        import json
        with pytest.raises(json.JSONDecodeError):
            _parse_json_response("not json at all")


class TestPydanticValidation:
    def test_parse_agent_response(self) -> None:
        from brain.council import _parse_agent_response
        text = '{"perspective": "We should explore", "proposed_action": "Research"}'
        result = _parse_agent_response(text)
        assert result.perspective == "We should explore"
        assert result.proposed_action == "Research"

    def test_parse_chair_response(self) -> None:
        from brain.council import _parse_chair_response
        text = '{"decision": "build it", "action_plan": "step 1"}'
        result = _parse_chair_response(text)
        assert result.decision == "build it"
        assert result.flag_for_jord is False

    def test_parse_chair_response_with_flag(self) -> None:
        from brain.council import _parse_chair_response
        text = '{"decision": "risky", "action_plan": "", "flag_for_jord": true, "flag_reason": "disagreement"}'
        result = _parse_chair_response(text)
        assert result.flag_for_jord is True
        assert result.flag_reason == "disagreement"

    def test_agent_response_missing_field_raises(self) -> None:
        from brain.council import _parse_agent_response
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _parse_agent_response('{"perspective": "test"}')


class TestRunCouncil:
    def _make_mock_llm(self, responses: list[str]) -> MagicMock:
        """Create a mock LLM that returns canned responses in order."""
        mock = MagicMock()
        call_count = {"n": 0}

        def side_effect(**kwargs):
            idx = call_count["n"]
            call_count["n"] += 1
            resp = MagicMock()
            resp.text = responses[idx % len(responses)]
            resp.input_tokens = 100
            resp.output_tokens = 50
            return resp

        mock.complete.side_effect = side_effect
        return mock

    def test_collects_perspectives_from_all_agents(self, tmp_path: Path) -> None:
        agents = make_agents()
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        survey = make_survey()
        agent_response = '{"perspective": "I think X", "proposed_action": "do X"}'
        chair_response = '{"decision": "do X", "action_plan": "step 1", "flag_for_jord": false, "flag_reason": ""}'
        # 4 agent calls + 1 chair call
        mock_llm = self._make_mock_llm([agent_response] * 4 + [chair_response])

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=survey,
            philosophy="Be good.", identity_texts={a.name: f"You are {a.name}" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm, journal_dir=journal_dir,
        )
        assert len(result.perspectives) == 4
        assert result.decision == "do X"

    def test_handles_agent_llm_failure_gracefully(self, tmp_path: Path) -> None:
        agents = make_agents()[:1]  # Just gandalf
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        survey = make_survey()

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = Exception("API down")

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=survey,
            philosophy="", identity_texts={"gandalf": ""},
            memory_summaries={"gandalf": ""}, shared_memory_summary="",
            llm=mock_llm, journal_dir=journal_dir,
        )
        assert "failed" in result.perspectives[0].perspective.lower()
        assert "failed" in result.decision.lower()

    def test_chair_rotation_advances(self, tmp_path: Path) -> None:
        agents = make_agents()
        journal_dir = tmp_path / "journal"
        journal_dir.mkdir()
        save_chair_index(journal_dir, 1)  # Start at gimli

        agent_response = '{"perspective": "ok", "proposed_action": "ok"}'
        chair_response = '{"decision": "ok", "action_plan": "ok", "flag_for_jord": false, "flag_reason": ""}'
        mock_llm = self._make_mock_llm([agent_response] * 4 + [chair_response])

        from brain.config import Config
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", agents=agents, council_enabled=True,
            max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm, journal_dir=journal_dir,
        )
        assert result.chair_name == "gimli"
        assert get_chair_index(journal_dir) == 2  # Advanced to galadriel
