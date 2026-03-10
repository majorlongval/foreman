"""
FOREMAN Fix Agent — v0.1
Reads review comments from FOREMAN's code reviews, generates minimal fixes,
and pushes them to the PR branch.

Triggered by: GitHub Actions on pull_request_review event
Only acts on reviews posted by FOREMAN that contain CRITICAL or IMPORTANT issues.

Usage:
  python fix_agent.py --pr 42          # Fix issues on a specific PR
  python fix_agent.py --once           # Check all PRs for fixable reviews
  python fix_agent.py --dry-run        # Generate fixes without pushing
"""

import os
import re
import sys
import json
import logging
import argparse
from datetime import datetime, timezone

from github import Github, GithubException
from llm_client import LLMClient, ModelRouter
from cost_monitor import CostTracker
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")
COST_CEILING_USD = float(os.environ.get("FIX_COST_CEILING_USD", "1.0"))

LABEL_FIXING = "fixing"
LABEL_NEEDS_HUMAN = "needs-human"
LABEL_REVIEWED = "reviewed"

BOT_SIGNATURE = "\n\n---\n_Review by FOREMAN 🤖_"
FIX_SIGNATURE = "\n\n---\n_Fix by FOREMAN 🔧_"

MAX_FIX_CYCLES = int(os.environ.get("MAX_FIX_CYCLES", "2"))

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.fixer")

# ─── Fix Prompt ──────────────────────────────────────────────

FIX_SYSTEM = """You are FOREMAN's code fixer. You receive review comments and the current
file content. Your job is to make MINIMAL changes to fix the issues identified.

Rules:
- Fix ONLY the issues described in the review comments.
- Do NOT refactor, reorganize, rename, or "improve" anything not mentioned.
- Do NOT add features, comments, or documentation not requested.
- Preserve all existing functionality — your changes must be surgical.
- Match the existing code style exactly.
- Output ONLY the complete fixed file content. No markdown fences. No explanation.
  The raw file content starts at character 0.
"""


# ─── Fix Agent ───────────────────────────────────────────────

class FixAgent:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(auth=__import__("github").Auth.Token(token))
        self.repo = self.gh.get_repo(repo_name)
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.dry_run = dry_run
        self.stats = {"fixed": 0, "skipped": 0, "failed": 0}
        self._ensure_labels()
        log.info(f"\n{self.router.summary()}\n")

    def _ensure_labels(self):
        existing = {l.name for l in self.repo.get_labels()}
        needed = {
            LABEL_FIXING: "fbca04",
            LABEL_NEEDS_HUMAN: "d93f0b",
        }
        for name, color in needed.items():
            if name not in existing:
                if not self.dry_run:
                    self.repo.create_label(name=name, color=color)

    def _get_latest_foreman_review(self, pr) -> str | None:
        """Get the body of the most recent FOREMAN review with issues."""
        reviews = list(pr.get_reviews())
        for review in reversed(reviews):
            if review.body and BOT_SIGNATURE.strip() in review.body:
                # Check if it has CRITICAL or IMPORTANT issues
                body_upper = review.body.upper()
                if "[CRITICAL]" in body_upper or "[IMPORTANT]" in body_upper:
                    return review.body
        return None

    def _count_fix_cycles(self, pr) -> int:
        """Count FOREMAN review cycles on this PR."""
        count = 0
        for review in pr.get_reviews():
            if review.body and BOT_SIGNATURE.strip() in review.body:
                count += 1
        return count

    def _parse_affected_files(self, review_body: str) -> list[str]:
        """Extract file paths mentioned in review issues."""
        files = set()
        # Match patterns like `filename.py:123` or `filename.py:10-20`
        for match in re.finditer(r'`([^`]+\.\w+)(?::\d+(?:-\d+)?)?`', review_body):
            filepath = match.group(1)
            # Basic sanity check — looks like a file path
            if '.' in filepath and not filepath.startswith('http'):
                files.add(filepath)
        return list(files)

    def _extract_issues_for_file(self, review_body: str, filepath: str) -> str:
        """Extract review issues relevant to a specific file."""
        lines = review_body.split('\n')
        relevant = []
        for line in lines:
            if filepath in line and ('CRITICAL' in line.upper() or 'IMPORTANT' in line.upper()):
                relevant.append(line)
                # Include the next line if it's a continuation (indented)
            elif relevant and line.startswith('  ') and not line.startswith('- **['):
                relevant.append(line)
        return '\n'.join(relevant) if relevant else review_body

    def fix_pr(self, pr) -> bool:
        """Apply fixes to a PR based on the latest FOREMAN review."""
        log.info(f"Fixing PR #{pr.number}: {pr.title}")

        # Check cycle count
        cycles = self._count_fix_cycles(pr)
        if cycles >= MAX_FIX_CYCLES:
            log.info(f"  Max fix cycles ({MAX_FIX_CYCLES}) reached — skipping")
            self.stats["skipped"] += 1
            return True

        # Get the latest review with issues
        review_body = self._get_latest_foreman_review(pr)
        if not review_body:
            log.info(f"  No actionable FOREMAN review found — skipping")
            self.stats["skipped"] += 1
            return True

        # Parse affected files
        affected_files = self._parse_affected_files(review_body)
        if not affected_files:
            log.warning(f"  Could not parse affected files from review — skipping")
            self.stats["skipped"] += 1
            return True

        log.info(f"  Affected files: {affected_files}")

        # Claim the PR
        if not self.dry_run:
            try:
                pr.add_to_labels(self.repo.get_label(LABEL_FIXING))
            except Exception:
                pass

        branch = pr.head.ref
        fixes_applied = []

        try:
            for filepath in affected_files:
                if not self.cost.check_ceiling():
                    break

                # Get current file content from PR branch
                try:
                    contents = self.repo.get_contents(filepath, ref=branch)
                    current_content = contents.decoded_content.decode("utf-8")
                    file_sha = contents.sha
                except Exception as e:
                    log.warning(f"  Could not read {filepath} from branch {branch}: {e}")
                    continue

                # Extract issues for this file
                file_issues = self._extract_issues_for_file(review_body, filepath)

                # Generate fix
                log.info(f"  Generating fix for {filepath}")
                model = self.router.get("implement")
                response = self.llm.complete(
                    model=model,
                    system=FIX_SYSTEM,
                    message=(
                        f"## Review Comments\n\n{file_issues}\n\n"
                        f"## Current File: {filepath}\n\n{current_content}"
                    ),
                    max_tokens=65536,
                )
                self.cost.record(model, response, agent="fixer", action="fix")

                fixed_content = response.text
                if not fixed_content or not fixed_content.strip():
                    log.error(f"  Empty fix for {filepath} — skipping")
                    continue

                # Syntax check Python files
                if filepath.endswith(".py"):
                    import ast
                    try:
                        ast.parse(fixed_content)
                    except SyntaxError as e:
                        log.error(f"  Syntax error in fix for {filepath}: {e} — skipping")
                        continue

                # Skip if content unchanged
                if fixed_content.strip() == current_content.strip():
                    log.info(f"  No changes needed for {filepath}")
                    continue

                # Push fix
                if not self.dry_run:
                    self.repo.update_file(
                        filepath,
                        f"fix: address review comments in {filepath}",
                        fixed_content,
                        file_sha,
                        branch=branch,
                    )
                    log.info(f"  Pushed fix for {filepath}")
                else:
                    log.info(f"  [DRY RUN] Would push fix for {filepath}")

                fixes_applied.append(filepath)

            # Post summary comment
            if fixes_applied:
                summary = "Applied fixes for:\n" + "\n".join(
                    f"- `{f}`" for f in fixes_applied
                )
                if not self.dry_run:
                    pr.create_issue_comment(summary + FIX_SIGNATURE)
                    # Remove fixing label — review agent will pick it up on synchronize
                    try:
                        pr.remove_from_labels(self.repo.get_label(LABEL_FIXING))
                    except Exception:
                        pass
                    # Remove reviewed label so review agent runs again
                    try:
                        pr.remove_from_labels(self.repo.get_label(LABEL_REVIEWED))
                    except Exception:
                        pass
                log.info(f"  Fixed {len(fixes_applied)} files")
                self.stats["fixed"] += 1
            else:
                log.info(f"  No fixes were applied")
                self.stats["skipped"] += 1

            return True

        except Exception as e:
            log.error(f"  Fix failed for PR #{pr.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False

        finally:
            # Release fixing label
            if not self.dry_run:
                try:
                    pr.remove_from_labels(self.repo.get_label(LABEL_FIXING))
                except Exception:
                    pass

    def get_fixable_prs(self) -> list:
        """Get open PRs that have FOREMAN reviews with issues."""
        pulls = self.repo.get_pulls(state="open", sort="created", direction="asc")
        fixable = []
        for pr in pulls:
            pr_labels = {l.name for l in pr.labels}
            if LABEL_FIXING in pr_labels:
                continue  # Already being fixed
            if LABEL_NEEDS_HUMAN in pr_labels:
                continue  # Escalated
            # Check for a FOREMAN review with issues
            review = self._get_latest_foreman_review(pr)
            if review:
                fixable.append(pr)
        return fixable

    def run_once(self, pr_number: int = None) -> dict:
        log.info("=" * 60)
        log.info(f"FOREMAN fixer @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

        if not self.cost.check_ceiling():
            log.warning("Parked — cost ceiling reached")
            return self.stats

        if pr_number:
            pr = self.repo.get_pull(pr_number)
            self.fix_pr(pr)
        else:
            queue = self.get_fixable_prs()
            log.info(f"Fixable PRs: {len(queue)}")
            for pr in queue:
                self.fix_pr(pr)
                if not self.cost.check_ceiling():
                    break

        log.info(f"Stats: {self.stats}")
        log.info(f"{self.cost.summary()}")
        return self.stats


# ─── CLI ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FOREMAN Fix Agent")
    parser.add_argument("--pr", type=int, default=None, help="Fix a specific PR")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="Generate fixes without pushing")
    args = parser.parse_args()

    for var in ["GITHUB_TOKEN", "FOREMAN_REPO"]:
        if not os.environ.get(var):
            log.error(f"{var} not set")
            sys.exit(1)

    agent = FixAgent(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)

    if args.pr:
        agent.run_once(pr_number=args.pr)
    elif args.once:
        agent.run_once()
    else:
        log.error("Fix agent runs on-demand only. Use --pr N or --once")
        sys.exit(1)


if __name__ == "__main__":
    main()
