"""Gather world state for council deliberation.

Surveys: budget, open issues, open PRs, recent incidents, shared decisions,
and last journal entry. Returns a SurveyResult that can be rendered as
context for LLM calls.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from brain.config import Config
from brain.cost_tracking import load_today_spend

log = logging.getLogger("foreman.brain.survey")


@dataclass
class SurveyResult:
    """Snapshot of the organism's current state."""

    budget_limit: float
    budget_spent: float
    open_issues: List[str]
    open_prs: List[str]
    recent_incidents: List[str]
    shared_decisions: List[str]
    journal_last_entry: Optional[str]
    inbox_note: Optional[str] = None
    # Maps "PR #N: title" → list of "author: comment body" strings
    pr_comments: Dict[str, List[str]] = field(default_factory=dict)

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self.budget_limit - self.budget_spent)

    @property
    def budget_exhausted(self) -> bool:
        return self.budget_spent >= self.budget_limit

    def to_context_string(self) -> str:
        """Render as a string for LLM context."""
        lines = [
            "# Current State",
            "",
            f"## Budget: ${self.budget_remaining:.2f} remaining "
            f"(${self.budget_spent:.2f} spent of ${self.budget_limit:.2f})",
            "",
        ]
        if self.open_issues:
            lines.append(f"## Open Issues ({len(self.open_issues)})")
            for issue in self.open_issues:
                lines.append(f"  - {issue}")
            lines.append("")
        if self.open_prs:
            lines.append(f"## Open PRs ({len(self.open_prs)})")
            for pr in self.open_prs:
                lines.append(f"  - {pr}")
            lines.append("")
        if self.recent_incidents:
            lines.append(f"## Recent Incidents ({len(self.recent_incidents)})")
            for incident in self.recent_incidents:
                lines.append(f"  - {incident}")
            lines.append("")
        if self.shared_decisions:
            lines.append("## Recent Decisions")
            for decision in self.shared_decisions:
                lines.append(f"  - {decision}")
            lines.append("")
        if self.journal_last_entry:
            lines.append("## Last Cycle")
            lines.append(self.journal_last_entry)
            lines.append("")
        if self.pr_comments:
            lines.append("## PR Comments")
            for pr_key, comments in self.pr_comments.items():
                lines.append(f"### {pr_key}")
                for comment in comments:
                    lines.append(f"  - {comment}")
            lines.append("")
        if self.inbox_note:
            lines.append("## Notes from Jord")
            lines.append(self.inbox_note)
        return "\n".join(lines)


def gather_survey(
    config: Config,
    memory_root: Path,
    repo: object,
    repo_root: Optional[Path] = None,
) -> SurveyResult:
    """Gather the full survey from GitHub, memory, and budget."""
    costs_dir = memory_root / "shared" / "costs"
    budget_spent = load_today_spend(costs_dir)

    open_issues: List[str] = []
    try:
        for issue in repo.get_issues(state="open"):
            if issue.pull_request is None:
                labels = ", ".join(l.name for l in issue.labels)
                label_str = f" [{labels}]" if labels else ""
                open_issues.append(f"#{issue.number}: {issue.title}{label_str}")
    except Exception as e:
        log.error(f"Failed to fetch issues: {e}")

    open_prs: List[str] = []
    pr_comments: Dict[str, List[str]] = {}
    try:
        for pr in repo.get_pulls(state="open"):
            key = f"PR #{pr.number}: {pr.title}"
            open_prs.append(key)
            try:
                comments = [
                    f"{c.user.login}: {c.body}"
                    for c in pr.get_issue_comments()
                ]
                if comments:
                    pr_comments[key] = comments
            except Exception as e:
                log.warning(f"Failed to fetch comments for PR #{pr.number}: {e}")
    except Exception as e:
        log.error(f"Failed to fetch PRs: {e}")

    incidents_dir = memory_root / "shared" / "incidents"
    recent_incidents = _read_recent_files(incidents_dir, limit=5)

    decisions_dir = memory_root / "shared" / "decisions"
    shared_decisions = _read_recent_files(decisions_dir, limit=5)

    journal_dir = memory_root / "shared" / "journal"
    journal_entries = _read_recent_files(journal_dir, limit=1)
    journal_last = journal_entries[0] if journal_entries else None

    inbox_note: Optional[str] = None
    if repo_root is not None:
        inbox_path = repo_root / "INBOX.md"
        if inbox_path.exists():
            content = inbox_path.read_text().strip()
            inbox_note = content if content else None

    return SurveyResult(
        budget_limit=config.daily_limit_usd,
        budget_spent=budget_spent,
        open_issues=open_issues,
        open_prs=open_prs,
        recent_incidents=recent_incidents,
        shared_decisions=shared_decisions,
        journal_last_entry=journal_last,
        inbox_note=inbox_note,
        pr_comments=pr_comments,
    )


def _read_recent_files(directory: Path, limit: int = 5) -> List[str]:
    """Read the most recent .md files from a directory, sorted by name descending."""
    if not directory.exists():
        return []
    files = sorted(
        (f for f in directory.iterdir() if f.is_file() and f.suffix == ".md"),
        key=lambda f: f.name,
        reverse=True,
    )
    return [f.read_text().strip() for f in files[:limit]]
