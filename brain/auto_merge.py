"""Auto-Merge Agent logic — the safety gate for high-confidence PRs.

This module provides the logic to automatically merge pull requests that
meet specific safety criteria, reducing the manual burden on the Critic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from github.PullRequest import PullRequest
    from github.Repository import Repository

log = logging.getLogger("foreman.brain.auto_merge")


@dataclass
class PRSafetyStatus:
    """Result of the safety gate check for a PR."""

    is_safe: bool
    reasons: List[str]
    approvals: int
    has_changes_requested: bool
    ci_passed: bool


class AutoMergeAgent:
    """Logic for identifying and merging safe, high-confidence PRs."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def check_safety(self, pr: PullRequest) -> PRSafetyStatus:
        """Evaluate if a PR meets the safety gate requirements.

        A PR is considered safe if:
        1. It is not a draft.
        2. It has at least one approval.
        3. It has no 'Changes Requested' reviews.
        4. All CI/CD checks have passed.
        5. It has the 'auto-merge' label (high-confidence gate).
        """
        reasons = []

        # 1. Draft check
        if pr.draft:
            reasons.append("PR is a draft")

        # 2. Review check
        # Note: we use get_reviews() to see the full history and find the
        # latest state for each reviewer.
        reviews = list(pr.get_reviews())
        latest_reviews = {}
        for review in reviews:
            latest_reviews[review.user.login] = review.state

        approvals = sum(1 for state in latest_reviews.values() if state == "APPROVED")
        has_changes_requested = any(
            state == "CHANGES_REQUESTED" for state in latest_reviews.values()
        )

        if approvals < 1:
            reasons.append("Insufficient approvals (minimum 1 required)")
        if has_changes_requested:
            reasons.append("Has 'Changes Requested' reviews")

        # 3. CI Check
        # We check the combined status of the head commit.
        # This covers legacy Statuses. Check Runs are handled separately in some repos.
        ci_passed = True
        try:
            head_sha = pr.head.sha
            combined_status = self.repo.get_commit(head_sha).get_combined_status()
            if combined_status.state != "success" and combined_status.total_count > 0:
                ci_passed = False
                reasons.append(f"CI/CD status is '{combined_status.state}'")

            # Check Runs (modern GitHub Actions)
            check_runs = self.repo.get_commit(head_sha).get_check_runs()
            for run in check_runs:
                if run.status == "completed" and run.conclusion not in [
                    "success",
                    "neutral",
                    "skipped",
                ]:
                    ci_passed = False
                    reasons.append(f"Check run '{run.name}' failed ({run.conclusion})")
                elif run.status != "completed":
                    ci_passed = False
                    reasons.append(f"Check run '{run.name}' is still {run.status}")
        except Exception as e:
            log.warning(f"Failed to check CI status for PR #{pr.number}: {e}")
            # If we can't verify CI, we assume it's not safe
            ci_passed = False
            reasons.append("Could not verify CI status")

        # 4. Label Check
        labels = [l.name for l in pr.labels]
        if "auto-merge" not in labels:
            reasons.append("Missing 'auto-merge' label")

        is_safe = len(reasons) == 0
        return PRSafetyStatus(
            is_safe=is_safe,
            reasons=reasons,
            approvals=approvals,
            has_changes_requested=has_changes_requested,
            ci_passed=ci_passed,
        )

    def process_open_prs(self) -> List[int]:
        """Scan all open PRs and merge those that pass the safety gate."""
        merged_ids = []
        try:
            for pr in self.repo.get_pulls(state="open"):
                status = self.check_safety(pr)
                if status.is_safe:
                    log.info(f"PR #{pr.number} ('{pr.title}') passed safety gate. Merging...")
                    try:
                        # Squash merge is the default for the Fellowship
                        pr.merge(
                            merge_method="squash",
                            commit_title=f"auto: merge PR #{pr.number} {pr.title}",
                            commit_message=(
                                f"Merged by AutoMergeAgent after passing safety gate.\n"
                                f"Approvals: {status.approvals}"
                            ),
                        )
                        merged_ids.append(pr.number)
                    except Exception as e:
                        log.error(f"Failed to merge PR #{pr.number}: {e}")
                else:
                    log.debug(f"PR #{pr.number} skipped: {', '.join(status.reasons)}")
        except Exception as e:
            log.error(f"Error during auto-merge cycle: {e}")

        return merged_ids


def run_auto_merge_cycle(repo: Repository) -> List[int]:
    """Convenience function to run one auto-merge pass."""
    agent = AutoMergeAgent(repo)
    return agent.process_open_prs()
