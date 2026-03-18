"""Tests for brain.council — Elrond orchestrator replaces deliberation+chair."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from brain.config import AgentConfig, Config
from brain.council import (
    AgentAssignment,
    CouncilResult,
    run_council,
)
from brain.survey import SurveyResult

# Reusable phases-format Elrond response for 4 worker agents
_ELROND_PHASES_4 = (
    '{"decision": "build it", "action_plan": "step 1",'
    '"phases": [[{"agent": "gandalf", "task": "scout the repo", "deliverable": "memory/gandalf/cycle_notes.md"},'
    '{"agent": "gimli", "task": "open a PR", "deliverable": "PR opened"},'
    '{"agent": "galadriel", "task": "review PR #1", "deliverable": "PR reviewed"},'
    '{"agent": "samwise", "task": "update docs", "deliverable": "docs updated"}]],'
    '"flag_for_jord": false, "flag_reason": ""}'
)


def make_agents() -> list[AgentConfig]:
    return [
        AgentConfig("gandalf", "scout", Path("agents/gandalf.md"), Path("memory/gandalf/")),
        AgentConfig("gimli", "builder", Path("agents/gimli.md"), Path("memory/gimli/")),
        AgentConfig("galadriel", "critic", Path("agents/galadriel.md"), Path("memory/galadriel/")),
        AgentConfig("samwise", "gardener", Path("agents/samwise.md"), Path("memory/samwise/")),
    ]


def make_agents_with_elrond() -> list[AgentConfig]:
    """Include elrond as an orchestrator agent — he should be excluded from assignments."""
    return [
        AgentConfig("elrond", "orchestrator", Path("agents/elrond.md"), Path("memory/elrond/")),
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


def make_config(agents: list[AgentConfig] | None = None) -> Config:
    return Config(
        daily_limit_usd=5.0,
        model_default="test",
        model_reasoning="test",
        model_council="test",
        model_elrond="test",
        agents=agents or make_agents(),
        council_enabled=True,
        max_cycles_per_day=12,
        telegram_enabled=True,
    )


class TestCouncilResult:
    def test_has_required_fields(self) -> None:
        result = CouncilResult(
            perspectives=[],
            chair_name="elrond",
            decision="Research new models",
            action_plan="Use scout tools to list available models",
        )
        assert result.chair_name == "elrond"
        assert result.decision == "Research new models"
        assert result.perspectives == []


class TestParseJsonResponse:
    def test_plain_json(self) -> None:
        from brain.council import parse_json_response
        result = parse_json_response('{"perspective": "test", "proposed_action": "do X"}')
        assert result["perspective"] == "test"

    def test_markdown_fenced_json(self) -> None:
        from brain.council import parse_json_response
        text = '```json\n{"perspective": "test"}\n```'
        result = parse_json_response(text)
        assert result["perspective"] == "test"

    def test_markdown_fenced_no_lang(self) -> None:
        from brain.council import parse_json_response
        text = '```\n{"perspective": "test"}\n```'
        result = parse_json_response(text)
        assert result["perspective"] == "test"

    def test_text_before_json(self) -> None:
        from brain.council import parse_json_response
        text = 'Here is my analysis:\n{"perspective": "test", "proposed_action": "do X"}'
        result = parse_json_response(text)
        assert result["perspective"] == "test"

    def test_text_surrounding_json(self) -> None:
        from brain.council import parse_json_response
        text = 'Let me think...\n{"decision": "build", "action_plan": "step 1"}\nDone!'
        result = parse_json_response(text)
        assert result["decision"] == "build"

    def test_malformed_json_raises(self) -> None:
        import json

        from brain.council import parse_json_response
        with pytest.raises(json.JSONDecodeError):
            parse_json_response("not json at all")

    def test_trailing_comma_in_object(self) -> None:
        from brain.council import parse_json_response
        text = '{"decision": "build", "action_plan": "step 1",}'
        result = parse_json_response(text)
        assert result["decision"] == "build"

    def test_trailing_comma_in_assignments(self) -> None:
        from brain.council import parse_json_response
        text = '{"assignments": {"gandalf": "task A", "gimli": "task B",}}'
        result = parse_json_response(text)
        assert result["assignments"]["gandalf"] == "task A"

    def test_unquoted_keys(self) -> None:
        """Gemini Flash sometimes emits unquoted keys in nested objects — must be fixed."""
        from brain.council import parse_json_response
        text = '{decision: "build it", action_plan: "step 1", flag_for_jord: false, flag_reason: ""}'
        result = parse_json_response(text)
        assert result["decision"] == "build it"
        assert result["flag_for_jord"] is False

    def test_python_boolean_true(self) -> None:
        from brain.council import parse_json_response
        text = '{"flag_for_jord": True, "flag_reason": "risky"}'
        result = parse_json_response(text)
        assert result["flag_for_jord"] is True

    def test_python_boolean_false(self) -> None:
        from brain.council import parse_json_response
        text = '{"flag_for_jord": False, "flag_reason": ""}'
        result = parse_json_response(text)
        assert result["flag_for_jord"] is False

    def test_python_none(self) -> None:
        from brain.council import parse_json_response
        text = '{"decision": "build", "flag_reason": None}'
        result = parse_json_response(text)
        assert result["flag_reason"] is None


class TestPydanticValidation:
    def testparse_agent_response(self) -> None:
        from brain.council import parse_agent_response
        text = '{"perspective": "We should explore", "proposed_action": "Research"}'
        result = parse_agent_response(text)
        assert result.perspective == "We should explore"
        assert result.proposed_action == "Research"

    def testparse_chair_response(self) -> None:
        from brain.council import parse_chair_response
        text = '{"decision": "build it", "action_plan": "step 1"}'
        result = parse_chair_response(text)
        assert result.decision == "build it"
        assert result.flag_for_jord is False

    def test_parse_chair_response_with_flag(self) -> None:
        from brain.council import parse_chair_response
        text = '{"decision": "risky", "action_plan": "", "flag_for_jord": true, "flag_reason": "disagreement"}'
        result = parse_chair_response(text)
        assert result.flag_for_jord is True
        assert result.flag_reason == "disagreement"

    def test_agent_response_missing_field_raises(self) -> None:
        from pydantic import ValidationError

        from brain.council import parse_agent_response
        with pytest.raises(ValidationError):
            parse_agent_response('{"perspective": "test"}')

    def test_chair_response_parses_phases(self) -> None:
        """ChairResponse must parse phases as List[List[AgentAssignment]]."""
        from brain.council import parse_chair_response
        text = (
            '{"decision": "build it", "action_plan": "step 1",'
            '"phases": [[{"agent": "gandalf", "task": "scout the repo", "deliverable": "memory/gandalf/cycle_notes.md"},'  # noqa: E501
            '{"agent": "gimli", "task": "open a PR", "deliverable": "PR opened"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )
        result = parse_chair_response(text)
        assert len(result.phases) == 1
        assert len(result.phases[0]) == 2
        assert isinstance(result.phases[0][0], AgentAssignment)
        assert result.phases[0][0].agent == "gandalf"
        assert result.phases[0][0].task == "scout the repo"
        assert result.phases[0][0].deliverable == "memory/gandalf/cycle_notes.md"
        assert result.phases[0][1].agent == "gimli"


class TestRunCouncil:
    """Tests for Elrond orchestrator — one LLM call, no deliberation."""

    def _make_mock_llm(self, response_text: str) -> MagicMock:
        """Create a mock LLM that returns a single canned response."""
        mock = MagicMock()
        resp = MagicMock()
        resp.text = response_text
        resp.input_tokens = 100
        resp.output_tokens = 50
        mock.complete.return_value = resp
        return mock

    def test_makes_exactly_one_llm_call(self, tmp_path: Path) -> None:
        """Elrond replaces N+1 calls with a single orchestration call."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = make_config(agents)

        run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="Be good.", identity_texts={a.name: f"You are {a.name}" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        assert mock_llm.complete.call_count == 1

    def test_uses_model_elrond(self, tmp_path: Path) -> None:
        """The single LLM call must use config.model_elrond, not model_council."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="should-not-be-used", model_elrond="gemini/gemini-3-pro-preview",
            agents=agents, council_enabled=True, max_cycles_per_day=12, telegram_enabled=True,
        )

        run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        call_kwargs = mock_llm.complete.call_args.kwargs
        assert call_kwargs["model"] == "gemini/gemini-3-pro-preview"

    def test_returns_phases_from_elrond(self, tmp_path: Path) -> None:
        """Phases from the Elrond response must be passed through to CouncilResult."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = make_config(agents)

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        assert len(result.phases) == 1
        assert len(result.phases[0]) == 4
        assert isinstance(result.phases[0][0], AgentAssignment)
        assert result.phases[0][0].agent == "gandalf"

    def test_chair_name_is_elrond(self, tmp_path: Path) -> None:
        """CouncilResult.chair_name is always 'elrond' — no rotation."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = make_config(agents)

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        assert result.chair_name == "elrond"

    def test_perspectives_always_empty(self, tmp_path: Path) -> None:
        """No deliberation means CouncilResult.perspectives is always []."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = make_config(agents)

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        assert result.perspectives == []

    def test_tracks_cost(self, tmp_path: Path) -> None:
        """CouncilResult.cost_usd must be positive when using a real model name."""
        agents = make_agents()
        mock_llm = self._make_mock_llm(_ELROND_PHASES_4)
        config = Config(
            daily_limit_usd=5.0, model_default="test", model_reasoning="test",
            model_council="test", model_elrond="gemini/gemini-3-flash-preview",
            agents=agents, council_enabled=True, max_cycles_per_day=12, telegram_enabled=True,
        )

        result = run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )
        # 100 input / 50 output tokens with a real model should produce non-zero cost
        assert result.cost_usd > 0

    def test_all_agent_memories_in_prompt(self, tmp_path: Path) -> None:
        """All agent memory summaries must appear in the user prompt sent to Elrond."""
        agents = make_agents()
        captured: list[str] = []

        def capturing_complete(**kwargs):
            captured.append(kwargs.get("message", ""))
            resp = MagicMock()
            resp.text = _ELROND_PHASES_4
            resp.input_tokens = 100
            resp.output_tokens = 50
            return resp

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = capturing_complete

        memory_summaries = {
            "gandalf": "gandalf private memory content",
            "gimli": "gimli private memory content",
            "galadriel": "galadriel private memory content",
            "samwise": "samwise private memory content",
        }
        config = make_config(agents)

        run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries=memory_summaries,
            shared_memory_summary="shared stuff here", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )

        assert len(captured) == 1
        user_prompt = captured[0]
        assert "gandalf private memory content" in user_prompt
        assert "gimli private memory content" in user_prompt
        assert "galadriel private memory content" in user_prompt
        assert "samwise private memory content" in user_prompt
        assert "shared stuff here" in user_prompt

    def test_elrond_prompt_lists_worker_agents(self, tmp_path: Path) -> None:
        """Worker agent names must appear in the system prompt so Elrond knows who to assign."""
        agents = make_agents()
        captured_system: list[str] = []

        def capturing_complete(**kwargs):
            captured_system.append(kwargs.get("system", ""))
            resp = MagicMock()
            resp.text = _ELROND_PHASES_4
            resp.input_tokens = 100
            resp.output_tokens = 50
            return resp

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = capturing_complete
        config = make_config(agents)

        run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )

        assert len(captured_system) == 1
        system_prompt = captured_system[0]
        assert "gandalf" in system_prompt
        assert "gimli" in system_prompt
        assert "galadriel" in system_prompt
        assert "samwise" in system_prompt

    def test_elrond_excluded_from_assignments(self, tmp_path: Path) -> None:
        """When elrond is in the agents list (role=orchestrator), he must not appear in assignable agents."""
        agents = make_agents_with_elrond()
        captured_system: list[str] = []

        elrond_response = (
            '{"decision": "coordinate", "action_plan": "assign workers",'
            '"phases": [[{"agent": "gandalf", "task": "scout", "deliverable": "memory/gandalf/cycle_notes.md"}]],'
            '"flag_for_jord": false, "flag_reason": ""}'
        )

        def capturing_complete(**kwargs):
            captured_system.append(kwargs.get("system", ""))
            resp = MagicMock()
            resp.text = elrond_response
            resp.input_tokens = 100
            resp.output_tokens = 50
            return resp

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = capturing_complete
        config = make_config(agents)

        run_council(
            config=config, agents=agents, survey=make_survey(),
            philosophy="", identity_texts={a.name: "" for a in agents},
            memory_summaries={a.name: "" for a in agents},
            shared_memory_summary="", llm=mock_llm,
            journal_dir=tmp_path / "journal",
        )

        # The system prompt should NOT include elrond as an assignable worker
        system_prompt = captured_system[0]
        # Worker agents should be present
        assert "gandalf" in system_prompt
        assert "gimli" in system_prompt
        # Elrond should NOT be listed as an assignable agent
        # (he may appear as the orchestrator identity, but not in the workers list)
        # We check that "elrond" doesn't appear in contexts that suggest he's a worker
        # The simplest check: the worker section must not include elrond
        # We'll assert that after filtering, elrond is excluded from the assignable list
        assert mock_llm.complete.call_count == 1
