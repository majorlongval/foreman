import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from github import GithubException

from promotion_logic import IssuePromoter, check_and_promote

@pytest.fixture
def mock_github():
    return MagicMock()

def create_mock_label(name):
    label = MagicMock()
    label.name = name
    return label

def create_mock_event(event_type, label_name, created_at):
    event = MagicMock()
    event.event = event_type
    event.label.name = label_name
    event.created_at = created_at
    return event

def create_mock_issue(number, label_names, created_at, events=None):
    issue = MagicMock()
    issue.number = number
    issue.labels = [create_mock_label(name) for name in label_names]
    issue.created_at = created_at
    
    if events is not None:
        issue.get_events.return_value = events
    else:
        issue.get_events.return_value = []
        
    return issue

@pytest.fixture
def base_time():
    return datetime.now(timezone.utc)

def test_promoter_init(mock_github):
    promoter = IssuePromoter(mock_github, dry_run=True)
    assert promoter.github == mock_github
    assert promoter.dry_run is True
    assert promoter.label_auto_refined == "auto-refined"
    assert promoter.label_ready == "ready"
    assert promoter.promo_delay_hours == 24.0

def test_get_stale_issues_no_issues(mock_github):
    mock_github.repo.get_issues.return_value = []
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    assert stale_issues == []
    mock_github.repo.get_issues.assert_called_once_with(
        state="open",
        labels=["auto-refined"],
        sort="created",
        direction="asc"
    )

def test_get_stale_issues_happy_path_via_events(mock_github, base_time):
    old_time = base_time - timedelta(hours=25)
    
    event = create_mock_event("labeled", "auto-refined", old_time)
    issue = create_mock_issue(1, ["auto-refined"], base_time, events=[event])
    
    mock_github.repo.get_issues.return_value = [issue]
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    assert len(stale_issues) == 1
    assert stale_issues[0].number == 1

def test_get_stale_issues_skips_young_issues(mock_github, base_time):
    recent_time = base_time - timedelta(hours=10)
    
    event = create_mock_event("labeled", "auto-refined", recent_time)
    issue = create_mock_issue(2, ["auto-refined"], base_time, events=[event])
    
    mock_github.repo.get_issues.return_value = [issue]
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    assert len(stale_issues) == 0

def test_get_stale_issues_skips_hold_label(mock_github, base_time):
    old_time = base_time - timedelta(hours=25)
    
    event = create_mock_event("labeled", "auto-refined", old_time)
    # Issue has both auto-refined and hold labels
    issue = create_mock_issue(3, ["auto-refined", "hold"], old_time, events=[event])
    
    mock_github.repo.get_issues.return_value = [issue]
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    assert len(stale_issues) == 0

def test_get_stale_issues_fallback_to_created_at(mock_github, base_time):
    old_time = base_time - timedelta(hours=25)
    # No events returned, should fallback to created_at (which is old enough)
    issue = create_mock_issue(4, ["auto-refined"], old_time, events=[])
    
    mock_github.repo.get_issues.return_value = [issue]
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    assert len(stale_issues) == 1
    assert stale_issues[0].number == 4

def test_get_stale_issues_handles_event_fetch_error(mock_github, base_time):
    old_time = base_time - timedelta(hours=25)
    issue = create_mock_issue(5, ["auto-refined"], old_time)
    issue.get_events.side_effect = Exception("API rate limit exceeded")
    
    mock_github.repo.get_issues.return_value = [issue]
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    # Should fallback to created_at and succeed despite the event exception
    assert len(stale_issues) == 1
    assert stale_issues[0].number == 5

def test_get_stale_issues_github_api_failure(mock_github):
    mock_github.repo.get_issues.side_effect = GithubException(500, "Server Error")
    promoter = IssuePromoter(mock_github)
    
    stale_issues = promoter.get_stale_refined_issues()
    
    # Should gracefully catch error and return empty list
    assert stale_issues == []

def test_promote_issue_success(mock_github):
    issue = create_mock_issue(10, ["auto-refined"], datetime.now(timezone.utc))
    promoter = IssuePromoter(mock_github, dry_run=False)
    
    result = promoter.promote_issue(issue)
    
    assert result is True
    issue.remove_from_labels.assert_called_once_with("auto-refined")
    issue.add_to_labels.assert_called_once_with("ready")
    issue.create_comment.assert_called_once()
    assert "ready for development" in issue.create_comment.call_args[0][0]

def test_promote_issue_dry_run(mock_github):
    issue = create_mock_issue(11, ["auto-refined"], datetime.now(timezone.utc))
    promoter = IssuePromoter(mock_github, dry_run=True)
    
    result = promoter.promote_issue(issue)
    
    assert result is True
    issue.remove_from_labels.assert_not_called()
    issue.add_to_labels.assert_not_called()
    issue.create_comment.assert_not_called()

def test_promote_issue_github_exception(mock_github):
    issue = create_mock_issue(12, ["auto-refined"], datetime.now(timezone.utc))
    issue.remove_from_labels.side_effect = GithubException(403, "Forbidden")
    promoter = IssuePromoter(mock_github, dry_run=False)
    
    result = promoter.promote_issue(issue)
    
    assert result is False
    issue.add_to_labels.assert_not_called()
    issue.create_comment.assert_not_called()

def test_promote_issue_unexpected_exception(mock_github):
    issue = create_mock_issue(13, ["auto-refined"], datetime.now(timezone.utc))
    issue.add_to_labels.side_effect = Exception("Random error")
    promoter = IssuePromoter(mock_github, dry_run=False)
    
    result = promoter.promote_issue(issue)
    
    assert result is False

@patch("promotion_logic.IssuePromoter")
def test_check_and_promote_success(MockIssuePromoter, mock_github):
    mock_promoter_instance = MockIssuePromoter.return_value
    
    issue1 = create_mock_issue(101, [], datetime.now())
    issue2 = create_mock_issue(102, [], datetime.now())
    
    mock_promoter_instance.get_stale_refined_issues.return_value = [issue1, issue2]
    # First issue succeeds, second fails to promote
    mock_promoter_instance.promote_issue.side_effect = [True, False]
    
    promoted_count = check_and_promote(mock_github, dry_run=False, delay_hours=48.0)
    
    assert promoted_count == 1
    MockIssuePromoter.assert_called_once_with(mock_github, dry_run=False)
    assert mock_promoter_instance.promo_delay_hours == 48.0
    assert mock_promoter_instance.promote_issue.call_count == 2

@patch("promotion_logic.IssuePromoter")
def test_check_and_promote_no_stale_issues(MockIssuePromoter, mock_github):
    mock_promoter_instance = MockIssuePromoter.return_value
    mock_promoter_instance.get_stale_refined_issues.return_value = []
    
    promoted_count = check_and_promote(mock_github)
    
    assert promoted_count == 0
    mock_promoter_instance.promote_issue.assert_not_called()

@patch("promotion_logic.IssuePromoter")
def test_check_and_promote_handles_critical_exception(MockIssuePromoter, mock_github):
    mock_promoter_instance = MockIssuePromoter.return_value
    mock_promoter_instance.get_stale_refined_issues.side_effect = Exception("System Failure")
    
    promoted_count = check_and_promote(mock_github)
    
    assert promoted_count == 0