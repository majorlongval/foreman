import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta
from pathlib import Path

import seed_agent
from seed_agent import GitHubClient, ForemanAgent, load_vision


# ─── Helpers ──────────────────────────────────────────────────

def make_issue(number, title, labels=None, created_at=None):
    if labels is None:
        labels = []
    issue = MagicMock()
    issue.number = number
    issue.title = title
    issue.body = "body"
    
    label_mocks = []
    for label in labels:
        lm = MagicMock()
        lm.name = label
        label_mocks.append(lm)
    issue.labels = label_mocks
    
    if created_at:
        issue.created_at = created_at
        
    return issue


# ─── Fixtures ─────────────────────────────────────────────────

@pytest.fixture
def mock_github(mocker):
    return mocker.patch('seed_agent.Github')


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "fake_token")
    monkeypatch.setenv("FOREMAN_REPO", "fake/repo")


@pytest.fixture
def base_agent(mocker, mock_github, mock_env):
    mocker.patch('seed_agent.CostTracker')
    mocker.patch('seed_agent.LLMClient')
    mocker.patch('seed_agent.ModelRouter')
    mocker.patch('seed_agent.tg')
    mocker.patch('seed_agent.state')
    
    gh_client = GitHubClient("fake_token", "fake/repo")
    # Using once=True prevents infinite loops in tests that might accidentally trigger loops
    agent = ForemanAgent(gh_client, dry_run=False, once=True)
    return agent


# ─── Tests: Vision Loader ─────────────────────────────────────

def test_load_vision_success(mocker):
    mocker.patch.object(Path, 'exists', return_value=True)
    mocker.patch.object(Path, 'read_text', return_value="# Fake Vision Document")
    
    vision_text = load_vision()
    assert vision_text == "# Fake Vision Document"


def test_load_vision_fallback(mocker):
    mocker.patch.object(Path, 'exists', return_value=False)
    vision_text = load_vision()
    assert vision_text == ""


# ─── Tests: GitHubClient ──────────────────────────────────────

def test_github_client_ensure_labels(mock_github):
    repo_mock = mock_github.return_value.get_repo.return_value
    repo_mock.get_labels.return_value = [MagicMock(name="existing-label")]
    
    GitHubClient("token", "repo")

    assert repo_mock.create_label.call_count >= 7  # All the standard foreman labels


def test_get_refinement_queue_filters_forbidden(mock_github):
    client = GitHubClient("token", "repo")
    client.repo = MagicMock()
    
    issue_safe = make_issue(1, "Safe", ["needs-refinement"])
    issue_forbidden = make_issue(2, "Forbidden", ["needs-refinement", seed_agent.LABEL_IMPLEMENTING])
    
    client.repo.get_issues.return_value = [issue_safe, issue_forbidden]
    
    queue = client.get_refinement_queue()
    assert len(queue) == 1
    assert queue[0].number == 1


def test_create_refined_issue(mock_github):
    client = GitHubClient("token", "repo")
    client.repo = MagicMock()
    
    original = make_issue(10, "Original", ["needs-refinement"])
    new_issue = make_issue(11, "Refined")
    client.repo.create_issue.return_value = new_issue
    
    result_num = client.create_refined_issue(original, "Refined Body", "Refined Title")
    
    assert result_num == 11
    client.repo.create_issue.assert_called_once()
    original.add_to_labels.assert_called()
    original.remove_from_labels.assert_called()
    original.edit.assert_called_with(state="closed", state_reason="completed")
    original.create_comment.assert_called()


def test_create_draft_issues_dry_run(mock_github):
    client = GitHubClient("token", "repo", dry_run=True)
    drafts = [{"title": "Draft 1", "body": "Body", "reasoning": "R1"}]
    
    created = client.create_draft_issues(drafts)
    
    assert len(created) == 1
    assert created[0] == (-1, "Draft 1")


# ─── Tests: Agent Logic ───────────────────────────────────────

def test_auto_promote_refined_issues_success(base_agent):
    now = datetime.now(timezone.utc)
    
    issue_old = make_issue(1, "Old Issue", [seed_agent.LABEL_AUTO_REFINED], created_at=now - timedelta(hours=25))
    issue_new = make_issue(2, "New Issue", [seed_agent.LABEL_AUTO_REFINED], created_at=now - timedelta(hours=2))
    
    base_agent.github.get_auto_refined_issues = MagicMock(return_value=[issue_old, issue_new])
    
    count = base_agent.auto_promote_refined_issues()
    
    assert count == 1
    issue_old.remove_from_labels.assert_called_with(seed_agent.LABEL_AUTO_REFINED)
    issue_old.add_to_labels.assert_called_with(seed_agent.LABEL_READY)
    issue_new.remove_from_labels.assert_not_called()
    seed_agent.tg.assert_called_once()


def test_auto_promote_skips_hold_label(base_agent):
    now = datetime.now(timezone.utc)
    issue_hold = make_issue(1, "Hold Issue", [seed_agent.LABEL_AUTO_REFINED, seed_agent.LABEL_HOLD], created_at=now - timedelta(hours=25))
    
    base_agent.github.get_auto_refined_issues = MagicMock(return_value=[issue_hold])
    
    count = base_agent.auto_promote_refined_issues()
    assert count == 0
    issue_hold.remove_from_labels.assert_not_called()


def test_refine_issue_success(base_agent, mocker):
    issue = make_issue(1, "Fix it", ["needs-refinement"])
    
    # Needs to pass validation: ## Tests and 2+ def test_
    mock_refine_resp = MagicMock()
    mock_refine_resp.text = "## Tests\ndef test_happy(): pass\ndef test_sad(): pass\n"
    mock_refine_resp.input_tokens = 10
    mock_refine_resp.output_tokens = 20
    
    mock_title_resp = MagicMock()
    mock_title_resp.text = "Implement Final Fix"
    mock_title_resp.input_tokens = 5
    mock_title_resp.output_tokens = 5
    
    base_agent.llm.complete.side_effect = [mock_refine_resp, mock_title_resp]
    base_agent.cost.check_ceiling.return_value = True
    
    mocker.patch.object(base_agent.github, 'create_refined_issue', return_value=2)
    
    success = base_agent.refine_issue(issue)
    
    assert success is True
    base_agent.github.create_refined_issue.assert_called_once_with(issue, mock_refine_resp.text, "Implement Final Fix")


def test_refine_issue_fails_validation(base_agent, mocker):
    issue = make_issue(1, "Fix it", ["needs-refinement"])
    
    # Missing tests section
    mock_refine_resp = MagicMock()
    mock_refine_resp.text = "Just a body, no tests."
    mock_refine_resp.input_tokens = 10
    mock_refine_resp.output_tokens = 20
    
    base_agent.llm.complete.return_value = mock_refine_resp
    base_agent.cost.check_ceiling.return_value = True
    
    mocker.patch.object(base_agent.github, 'create_refined_issue')
    
    success = base_agent.refine_issue(issue)
    
    assert success is False
    base_agent.github.create_refined_issue.assert_not_called()
    issue.create_comment.assert_called()
    issue.add_to_labels.assert_called_with(seed_agent.LABEL_REFINEMENT_FAILED)


def test_refine_issue_cost_ceiling_reached(base_agent, mocker):
    issue = make_issue(1, "Fix it", ["needs-refinement"])
    base_agent.cost.check_ceiling.return_value = False
    
    success = base_agent.refine_issue(issue)
    assert success is False


def test_brainstorm_success(base_agent, mocker):
    base_agent.vision = "Do great things"
    base_agent.github.get_all_open_issues = MagicMock(return_value=[])
    base_agent.github.get_closed_issues = MagicMock(return_value=[])
    
    mock_resp = MagicMock()
    mock_resp.text = '[{"title": "New Task", "body": "Details", "reasoning": "Because"}]'
    base_agent.llm.complete.return_value = mock_resp
    base_agent.cost.check_ceiling.return_value = True
    
    base_agent.github.create_draft_issues = MagicMock(return_value=[(100, "New Task")])
    
    created = base_agent.brainstorm()
    
    assert len(created) == 1
    assert created[0] == (100, "New Task")
    base_agent.github.create_draft_issues.assert_called_once()


def test_brainstorm_invalid_json(base_agent, mocker):
    base_agent.vision = "Do great things"
    base_agent.github.get_all_open_issues = MagicMock(return_value=[])
    base_agent.github.get_closed_issues = MagicMock(return_value=[])
    
    mock_resp = MagicMock()
    mock_resp.text = 'Not a json response'
    base_agent.llm.complete.return_value = mock_resp
    base_agent.cost.check_ceiling.return_value = True
    
    base_agent.github.create_draft_issues = MagicMock()
    
    created = base_agent.brainstorm()
    
    assert created == []
    base_agent.github.create_draft_issues.assert_not_called()
    assert base_agent.stats["failed"] == 1


def test_run_once_refine_mode(base_agent, mocker):
    base_agent.cost.check_ceiling.return_value = True
    
    issue = make_issue(1, "Queue Issue", ["needs-refinement"])
    base_agent.github.get_refinement_queue = MagicMock(return_value=[issue])
    
    mocker.patch.object(base_agent, 'auto_promote_refined_issues')
    mocker.patch.object(base_agent, 'refine_issue', return_value=True)
    mocker.patch.object(base_agent, 'brainstorm')
    
    base_agent.run_once()

    base_agent.auto_promote_refined_issues.assert_called_once()
    base_agent.refine_issue.assert_called_once_with(issue)
    base_agent.brainstorm.assert_not_called()


def test_run_once_brainstorm_mode(base_agent, mocker):
    base_agent.cost.check_ceiling.return_value = True
    
    # Empty queue should trigger brainstorm if below threshold
    base_agent.github.get_refinement_queue = MagicMock(return_value=[])
    base_agent.github.get_all_open_issues = MagicMock(return_value=[])
    
    mocker.patch.object(base_agent, 'auto_promote_refined_issues')
    mocker.patch.object(base_agent, 'refine_issue')
    mocker.patch.object(base_agent, 'brainstorm', return_value=[(1, "Task")])
    
    base_agent.run_once()
    
    base_agent.refine_issue.assert_not_called()
    base_agent.brainstorm.assert_called_once()


def test_run_once_brainstorm_cap_reached(base_agent, mocker):
    base_agent.cost.check_ceiling.return_value = True
    base_agent.github.get_refinement_queue = MagicMock(return_value=[])
    
    # Max open drafts hit
    open_issues = [make_issue(i, f"Issue {i}") for i in range(seed_agent.MAX_OPEN_DRAFTS)]
    base_agent.github.get_all_open_issues = MagicMock(return_value=open_issues)
    
    mocker.patch.object(base_agent, 'brainstorm')
    
    base_agent.run_once()
    
    # Should skip brainstorm
    base_agent.brainstorm.assert_not_called()