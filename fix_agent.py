"""
FOREMAN Fix Agent — v0.2
Reads review comments from FOREMAN's code reviews, generates minimal fixes,
and pushes them to the PR branch.

Triggered by: GitHub Actions on pull_request_review event
Automated pipeline processes feedback to auto-merge, request human review, or attempt fixes.

Usage:
  python fix_agent.py --pr 42          # Fix issues on a specific PR
  python fix_agent.py --once           # Check all PRs for fixable reviews
  python fix_agent.py --dry-run        # Generate fixes without pushing
  python fix_agent.py --cost-summary   # Show daily API cost summary
"""

import ast
import difflib
import json
import os
import re
import sys

import logging
import argparse
from datetime import datetime, timezone

from github import Github
from llm_client import LLMClient, ModelRouter
from cost_monitor import CostTracker, print_daily_summary
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")
COST_CEILING_USD = float(os.environ.get("FIX_COST_CEILING_USD", "1.0"))

AUTO_MERGE_ENABLED = os.environ.get("AUTO_MERGE_ENABLED", "false").lower() == "true"

LABEL_FIXING = "fixing"
LABEL_NEEDS_HUMAN = "needs-human"
LABEL_REVIEWED = "reviewed"
LABEL_NO_AUTO_MERGE = "no-auto-merge"

BOT_SIGNATURE = "\n\n---\n_Review by FOREMAN 🤖_"
FIX_SIGNATURE = "\n\n---\n_Fix by FOREMAN 🔧_"

MAX_FIX_CYCLES = int(os.environ.get("MAX_FIX_CYCLES", "3"))
CONFIDENCE_THRESHOLD_HIGH = float(os.environ.get("CONFIDENCE_THRESHOLD_HIGH", "0.80"))
CONFIDENCE_THRESHOLD_MEDIUM = float(os.environ.get("CONFIDENCE_THRESHOLD_MEDIUM", "0.50"))

# ─── Logging ──────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.fixer")

# ─── Fix Prompt ──────────────────────────────────────────────

PATCH_SYSTEM = """You are FOREMAN's code patcher. You receive a file and review issues with suggested fixes.

Your ONLY job: output a JSON array of search/replace operations.

Each operation:
{
  "search": "exact existing code to find (multi-line OK, must be unique in file)",
  "replace": "exact replacement code",
  "issue": "which review issue this addresses"
}

Rules:
- Output ONLY valid JSON. No markdown fences. No explanation.
- Each search string MUST appear exactly once in the file.
- Each search string MUST include enough surrounding context lines to be unique.
- ONLY address CRITICAL and IMPORTANT issues from the review.
- Fix each issue COMPREHENSIVELY: if a review identifies a pattern (e.g., missing
  label check, missing cache, missing guard clause), scan the ENTIRE file for all
  instances of that pattern and fix every one — not just the cited line number.
  Line numbers in reviews are hints pointing to one example, not the full scope.
- If a suggested fix is provided verbatim in the review, use it as the template
  and apply the same pattern everywhere it is needed in the file.
- Do NOT "clean up" or "improve" anything beyond fixing the identified issues.
"""


# ─── Patch Helpers ───────────────────────────────────────────

def parse_json(text: str) -> list | None:
    """Strip markdown fences and parse JSON. Returns list or None."""
    if not text or not text.strip():
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
        if not isinstance(result, list):
            return None
        return result
    except (json.JSONDecodeError, ValueError):
        return None


def apply_patches(content: str, patches: list) -> tuple[str, list[str]]:
    """Apply search/replace patches. Returns (patched_content, errors)."""
    errors = []
    for i, patch in enumerate(patches, 1):
        if "search" not in patch or "replace" not in patch:
            errors.append(f"Patch {i}: missing required 'search' or 'replace' key")
            continue
        search = patch["search"]
        replace = patch["replace"]
        count = content.count(search)
        if count == 0:
            errors.append(f"Patch {i}: search string not found in file")
            continue
        if count > 1:
            errors.append(f"Patch {i}: search string matches {count} locations (must be unique)")
            continue
        content = content.replace(search, replace, 1)
    return content, errors


def check_scope(original: str, patched: str, review_body: str) -> list[str]:
    """Warn if patches touch lines not mentioned in the review."""
    mentioned_ranges = []
    for match in re.finditer(r'`[^`]+\.\w+:(\d+)(?:-(\d+))?`', review_body):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        mentioned_ranges.append((start, end))

    if not mentioned_ranges:
        return []

    changed_lines = set()
    orig_line = 0
    for line in difflib.unified_diff(original.splitlines(), patched.splitlines(), lineterm=""):
        if line.startswith("@@"):
            m = re.search(r"@@ -(\d+)", line)
            if m:
                orig_line = int(m.group(1)) - 1
        elif line.startswith("---") or line.startswith("+++"):
            pass
        elif line.startswith("-"):
            orig_line += 1
            changed_lines.add(orig_line)
        elif not line.startswith("+"):
            orig_line += 1

    warnings = []
    for ln in sorted(changed_lines):
        if not any(start <= ln <= end for start, end in mentioned_ranges):
            warnings.append(f"Line {ln} changed but not within any reviewed range {mentioned_ranges}")
    return warnings


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
            LABEL_NO_AUTO_MERGE: "ededed",
        }
        for name, color in needed.items():
            if name not in existing:
                if not self.dry_run:
                    try:
                        self.repo.create_label(name=name, color=color)
                    except Exception as e:
                        log.warning(f"  Could not create label {name}: {e}")

    def _get_all_foreman_reviews(self, pr) -> list[str]:
        """Get all FOREMAN review bodies with issues, oldest first."""
        try:
            return [
                r.body for r in pr.get_reviews()
                if r.body and "Review by FOREMAN" in r.body
                and ("[CRITICAL]" in r.body.upper() or "[IMPORTANT]" in r.body.upper())
            ]
        except Exception:
            return []

    def _get_latest_foreman_review(self, pr) -> str | None:
        """Get the body of the most recent FOREMAN review."""
        try:
            reviews = [
                r.body for r in pr.get_reviews()
                if r.body and "Review by FOREMAN" in r.body
            ]
            return reviews[-1] if reviews else None
        except Exception as e:
            log.warning(f"  Failed to fetch reviews for PR #{pr.number}: {e}")
            return None

    def _calculate_confidence_score(self, pr, review_body: str) -> float:
        """Calculate confidence score (0.0 to 1.0) based on verdict, issues, and PR size."""
        score = 0.5  # Baseline

        if '"verdict": "APPROVE"' in review_body:
            score = 0.9
        elif '"verdict": "COMMENT"' in review_body:
            score = 0.6
        elif '"verdict": "REQUEST_CHANGES"' in review_body:
            score = 0.3

        # Severity penalties
        criticals = len(re.findall(r'\[CRITICAL\]', review_body, re.IGNORECASE))
        importants = len(re.findall(r'\[IMPORTANT\]', review_body, re.IGNORECASE))
        score -= (criticals * 0.15)
        score -= (importants * 0.05)

        # PR Size penalty
        try:
            total_changes = (pr.additions or 0) + (pr.deletions or 0)
            if total_changes > 1000:
                score -= 0.2
            elif total_changes > 500:
                score -= 0.1
        except Exception:
            pass

        return max(0.0, min(1.0, score))

    def _criticals_overlap(self, body1: str, body2: str) -> bool:
        """Return True if two reviews share most of the same CRITICAL issue descriptions."""
        def extract_criticals(body):
            return set(re.findall(r'\[CRITICAL\][^\n]*', body, re.IGNORECASE))

        c1 = extract_criticals(body1)
        c2 = extract_criticals(body2)
        if not c1 or not c2:
            return False
        overlap = len(c1 & c2)
        return overlap >= max(1, len(c1) // 2)

    def _count_fix_cycles(self, pr) -> int:
        """Count FOREMAN review cycles on this PR."""
        count = 0
        try:
            for review in pr.get_reviews():
                if review.body and "Review by FOREMAN" in review.body:
                    count += 1
        except Exception:
            pass
        return count

    _FILE_EXTENSIONS = ('.py', '.yml', '.yaml', '.json', '.toml', '.md', '.txt', '.cfg', '.ini', '.sh')

    def _parse_affected_files(self, review_body: str) -> list[str]:
        """Extract file paths mentioned in review issues."""
        files = set()
        for match in re.finditer(r'`([^`]+\.\w+)(?::\d+(?:-\d+)?)?`', review_body):
            filepath = match.group(1)
            if any(filepath.endswith(ext) for ext in self._FILE_EXTENSIONS):
                files.add(filepath)
        return list(files)

    def _extract_issues_for_file(self, review_body: str, filepath: str) -> str:
        """Extract review issues relevant to a specific file."""
        lines = review_body.split('\n')
        relevant = []
        for line in lines:
            if filepath in line and ('CRITICAL' in line.upper() or 'IMPORTANT' in line.upper()):
                relevant.append(line)
            elif relevant and line.startswith('  ') and not line.startswith('- **['):
                relevant.append(line)
        return '\n'.join(relevant) if relevant else review_body

    def _is_approve_ready(self, pr) -> bool:
        """Check if PR meets all criteria for auto-merge."""
        if not AUTO_MERGE_ENABLED:
            return False

        labels = {l.name for l in pr.labels}
        if LABEL_NO_AUTO_MERGE in labels:
            log.info(f"  Auto-merge opted out via label for PR #{pr.number}")
            return False

        if not self.dry_run:
            try:
                pr.update()
            except Exception as e:
                log.warning(f"  Failed to update PR data: {e}")

        if pr.mergeable is False:
            log.warning(f"  PR #{pr.number} is not mergeable (conflicts)")
            return False

        if pr.mergeable is not True:
            log.info(f"  PR #{pr.number} mergeable status is {pr.mergeable}")
            return False

        if pr.mergeable_state in ("pending", "unknown", None):
            log.info(f"  PR #{pr.number} mergeable_state is '{pr.mergeable_state}'")
            return False

        latest_review = self._get_latest_foreman_review(pr)
        if not latest_review:
            return False
            
        if '"verdict": "APPROVE"' not in latest_review:
            return False

        if "[CRITICAL]" in latest_review.upper() or "[IMPORTANT]" in latest_review.upper():
            log.warning(f"  PR #{pr.number} has APPROVE verdict but still lists critical issues")
            return False

        return True

    def _try_auto_merge(self, pr):
        """Attempt to squash-merge the PR if eligible."""
        try:
            if not self._is_approve_ready(pr):
                return

            log.info(f"  PR #{pr.number} is ready for auto-merge")
            
            if self.dry_run:
                log.info(f"  [DRY RUN] Would auto-merge PR #{pr.number}")
                return

            status = pr.merge(
                merge_method="squash",
                commit_title=f"auto-merge PR #{pr.number}: {pr.title}",
                commit_message=f"Merged automatically by FOREMAN after approval.{FIX_SIGNATURE}"
            )
            if not status.merged:
                raise Exception(f"GitHub API returned merged=False: {getattr(status, 'message', 'unknown')}")
            log.info(f"  PR #{pr.number} merged successfully")
            tg(f"✅ Auto-merged PR #{pr.number}: {pr.title}\n{pr.html_url}")

        except Exception as e:
            log.error(f"  Auto-merge failed for PR #{pr.number}: {e}")
            try:
                if not self.dry_run:
                    pr.add_to_labels(LABEL_NEEDS_HUMAN)
            except Exception:
                pass
            tg(f"❌ Auto-merge failed for PR #{pr.number}: {e}\n{pr.html_url}")

    def fix_pr(self, pr) -> bool:
        """Process a PR using the automated pipeline (Auto-merge, Human Review, or Fix)."""
        log.info(f"Processing PR #{pr.number}: {pr.title}")
        
        try:
            latest_review = self._get_latest_foreman_review(pr)
            if not latest_review:
                log.info(f"  No FOREMAN review found — skipping")
                self.stats["skipped"] += 1
                return True

            score = self._calculate_confidence_score(pr, latest_review)
            
            verdict = "COMMENT"
            if '"verdict": "APPROVE"' in latest_review: verdict = "APPROVE"
            elif '"verdict": "REQUEST_CHANGES"' in latest_review: verdict = "REQUEST_CHANGES"
            
            log.info(f"  Confidence Score: {score:.2f}, Verdict: {verdict}")

            # 1. High confidence path: Auto-merge
            if score > CONFIDENCE_THRESHOLD_HIGH and verdict == "APPROVE":
                log.info(f"  High confidence path triggered")
                self._try_auto_merge(pr)
                self.stats["fixed"] += 1
                return True

            # 2. Medium confidence path: Human Review
            if CONFIDENCE_THRESHOLD_MEDIUM <= score <= CONFIDENCE_THRESHOLD_HIGH and verdict == "COMMENT":
                log.info(f"  Medium confidence path triggered — requesting human review")
                if not self.dry_run:
                    try:
                        pr.add_to_labels(LABEL_NEEDS_HUMAN)
                    except Exception: pass
                    tg(f"🤔 PR #{pr.number} requires human review (Confidence: {score:.2f})\n{pr.html_url}")
                self.stats["skipped"] += 1
                return True

            # 3. Low confidence path: Fix Agent
            log.info(f"  Low confidence path triggered — attempting automated fix")

            cycles = self._count_fix_cycles(pr)
            if cycles >= MAX_FIX_CYCLES:
                log.info(f"  Max fix cycles ({MAX_FIX_CYCLES}) reached — escalating")
                if not self.dry_run:
                    try:
                        pr.add_to_labels(LABEL_NEEDS_HUMAN)
                    except Exception: pass
                    tg(f"⚠️ PR #{pr.number} reached max fix cycles ({MAX_FIX_CYCLES}) — escalation required\n{pr.html_url}")
                self.stats["skipped"] += 1
                return True

            all_reviews = self._get_all_foreman_reviews(pr)
            if len(all_reviews) >= 2 and self._criticals_overlap(all_reviews[-1], all_reviews[-2]):
                log.warning(f"  Fix agent stalled — patterns not converging")
                if not self.dry_run:
                    try:
                        pr.add_to_labels(LABEL_NEEDS_HUMAN)
                    except Exception: pass
                    pr.create_issue_comment(
                        f"⚠️ Fix agent stalled — patterns are not converging. Human intervention needed."
                        + FIX_SIGNATURE
                    )
                    tg(f"⚠️ PR #{pr.number} stalled — fix agent not converging\n{pr.html_url}")
                self.stats["skipped"] += 1
                return True

            review_body = latest_review
            affected_files = self._parse_affected_files(review_body)
            if not affected_files:
                log.warning(f"  Could not parse affected files from review — skipping")
                self.stats["skipped"] += 1
                return True

            log.info(f"  Affected files: {affected_files}")
            branch = pr.head.ref

            if not self.dry_run:
                try:
                    self.repo.merge(base=branch, head="main", commit_message=f"Merge main into {branch}")
                except Exception: pass

            if not self.dry_run:
                try:
                    pr.add_to_labels(LABEL_FIXING)
                except Exception: pass

            fixes_applied = []
            fixes_ready = []

            for filepath in affected_files:
                if not self.cost.check_ceiling():
                    break
                try:
                    contents = self.repo.get_contents(filepath, ref=branch)
                    current_content = contents.decoded_content.decode("utf-8")
                    file_sha = contents.sha
                except Exception: continue

                history_parts = []
                for i, rev in enumerate(all_reviews):
                    issues = self._extract_issues_for_file(rev, filepath)
                    history_parts.append(f"**Round {i+1}:**\n{issues}")
                review_history = "\n\n---\n".join(history_parts) if history_parts else review_body

                model = self.router.get("fix")
                prompt = f"## Review History\n\n{review_history}\n\n## Current File: {filepath}\n\n{current_content}"
                patched = None
                for attempt in range(2):
                    response = self.llm.complete(model=model, system=PATCH_SYSTEM, message=prompt)
                    self.cost.record(model, response, agent="fixer", action="fix")
                    patches = parse_json(response.text)
                    if patches is None:
                        prompt += "\n\nYour previous response was not valid JSON."
                        continue
                    patched_content, errors = apply_patches(current_content, patches)
                    if errors:
                        prompt += f"\n\nPatch application failed:\n" + "\n".join(errors)
                        continue
                    if filepath.endswith(".py"):
                        try:
                            ast.parse(patched_content)
                        except SyntaxError:
                            prompt += f"\n\nPatched file has syntax error. Fix it."
                            continue
                    patched = patched_content
                    break
                if patched and patched.strip() != current_content.strip():
                    fixes_ready.append((filepath, patched, file_sha))

            for filepath, patched, file_sha in fixes_ready:
                if not self.dry_run:
                    self.repo.update_file(
                        filepath, f"fix: address review comments in {filepath}",
                        patched, file_sha, branch=branch
                    )
                    fixes_applied.append(filepath)

            if fixes_applied:
                summary = "Applied fixes for:\n" + "\n".join(f"- `{f}`" for f in fixes_applied)
                if not self.dry_run:
                    pr.create_issue_comment(summary + FIX_SIGNATURE)
                    try:
                        pr.remove_from_labels(LABEL_REVIEWED)
                    except Exception: pass
                    tg(f"🔧 Fix agent pushed fixes to PR #{pr.number}: {', '.join(fixes_applied)}\n{pr.html_url}")
                log.info(f"  Fixed {len(fixes_applied)} files")
                self.stats["fixed"] += 1
            else:
                log.info(f"  No fixes were applied")
                self.stats["skipped"] += 1
            return True

        except Exception as e:
            log.error(f"  Process failed for PR #{pr.number}: {e}")
            self.stats["failed"] += 1
            tg(f"❌ Fix agent failed on PR #{pr.number}: {e}\n{pr.html_url}")
            return False
        finally:
            if not self.dry_run:
                try:
                    pr.remove_from_labels(LABEL_FIXING)
                except Exception: pass

    def get_fixable_prs(self) -> list:
        """Get open PRs that have FOREMAN reviews."""
        pulls = self.repo.get_pulls(state="open", sort="created", direction="asc")
        fixable = []
        for pr in pulls:
            pr_labels = {l.name for l in pr.labels}
            if LABEL_FIXING in pr_labels or LABEL_NEEDS_HUMAN in pr_labels:
                continue
            if self._get_latest_foreman_review(pr):
                fixable.append(pr)
        return fixable

    def run_once(self, pr_number: int = None) -> dict:
        log.info("=" * 60)
        log.info(f"FOREMAN fixer @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        if not self.cost.check_ceiling():
            log.warning("Parked — cost ceiling reached")
            return self.stats
        if pr_number:
            try:
                pr = self.repo.get_pull(pr_number)
                self.fix_pr(pr)
            except Exception as e:
                log.error(f"Failed to process PR #{pr_number}: {e}")
        else:
            queue = self.get_fixable_prs()
            log.info(f"Eligible PRs: {len(queue)}")
            for pr in queue:
                try:
                    self.fix_pr(pr)
                except Exception as e:
                    log.error(f"Error processing PR #{pr.number}: {e}")
                if not self.cost.check_ceiling():
                    break
        log.info(f"Stats: {self.stats}")
        log.info(f"{self.cost.summary()}")
        return self.stats


def main():
    parser = argparse.ArgumentParser(description="FOREMAN Fix Agent")
    parser.add_argument("--pr", type=int, default=None, help="Fix a specific PR")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="Generate fixes without pushing")
    parser.add_argument("--cost-summary", action="store_true", help="Show daily API cost summary")
    args = parser.parse_args()
    if args.cost_summary:
        print_daily_summary()
        sys.exit(0)
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
        sys.exit(1)


if __name__ == "__main__":
    main()