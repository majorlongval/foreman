"""
FOREMAN Fix Agent — v0.2
Reads review comments from FOREMAN's code reviews, generates minimal fixes,
and pushes them to the PR branch.

Triggered by: GitHub Actions on pull_request_review event
Only acts on reviews posted by FOREMAN that contain CRITICAL or IMPORTANT issues.

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
import time

import logging
import argparse
from datetime import datetime, timezone

from github import Github, GithubException
from llm_client import LLMClient, ModelRouter
from cost_monitor import CostTracker, print_daily_summary
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")
COST_CEILING_USD = float(os.environ.get("FIX_COST_CEILING_USD", "2.0"))

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
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:]
        # Remove closing fence
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
    """Apply search/replace patches. Returns (patched_content, errors).

    Each patch must have 'search' appearing exactly once in content.
    Errors are 1-indexed human-readable strings suitable for LLM retry prompts.
    """
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
            warnings.append(
                f"Line {ln} changed but not within any reviewed range {mentioned_ranges}"
            )
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
        }
        for name, color in needed.items():
            if name not in existing:
                if not self.dry_run:
                    self.repo.create_label(name=name, color=color)

    def _parse_review_data(self, review_body: str) -> dict:
        """Extract structured review data from the JSON block in the review body."""
        defaults = {
            "verdict": "COMMENT",
            "critical_count": 0,
            "important_count": 0,
            "suggestion_count": 0,
            "affected_files": [],
        }
        try:
            marker = "## Review Data"
            idx = review_body.find(marker)
            if idx == -1:
                return defaults
            after_marker = review_body[idx + len(marker):]
            json_start = after_marker.find("```json")
            if json_start == -1:
                return defaults
            json_content_start = after_marker.find("\n", json_start) + 1
            json_end = after_marker.find("```", json_content_start)
            if json_end == -1:
                return defaults
            json_str = after_marker[json_content_start:json_end].strip()
            data = json.loads(json_str)
            return {
                "verdict": data.get("verdict", defaults["verdict"]),
                "critical_count": int(data.get("critical_count", 0)),
                "important_count": int(data.get("important_count", 0)),
                "suggestion_count": int(data.get("suggestion_count", 0)),
                "affected_files": data.get("affected_files", []),
            }
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            log.warning(f"Failed to parse review data JSON: {e}")
            return defaults

    def _get_all_foreman_reviews(self, pr) -> list:
        """Get all FOREMAN review objects, oldest first."""
        return [
            r for r in pr.get_reviews()
            if r.body and BOT_SIGNATURE.strip() in r.body
        ]

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
        for review in pr.get_reviews():
            if review.body and BOT_SIGNATURE.strip() in review.body:
                count += 1
        return count

    def _extract_issues_for_file(self, review_body: str, filepath: str) -> str:
        """Extract review issues relevant to a specific file, including code blocks."""
        lines = review_body.split('\n')
        relevant = []
        is_collecting = False
        
        for line in lines:
            if f"`{filepath}" in line and ('CRITICAL' in line.upper() or 'IMPORTANT' in line.upper()):
                is_collecting = True
                relevant.append(line)
            elif is_collecting:
                if line.startswith('- **[') and f"`{filepath}" not in line:
                    is_collecting = False
                elif line.startswith('## Verdict') or line.startswith('## Review Data'):
                    is_collecting = False
                else:
                    relevant.append(line)
                    
        return '\n'.join(relevant).strip() if relevant else ""

    def fix_pr(self, pr) -> bool:
        """Apply fixes to a PR based on the latest FOREMAN review."""
        log.info(f"Fixing PR #{pr.number}: {pr.title}")

        try:
            cycles = self._count_fix_cycles(pr)
            if cycles >= MAX_FIX_CYCLES:
                log.info(f"  Max fix cycles ({MAX_FIX_CYCLES}) reached — skipping")
                self.stats["skipped"] += 1
                return True

            all_reviews = self._get_all_foreman_reviews(pr)
            if not all_reviews:
                log.info(f"  No FOREMAN review found — skipping")
                self.stats["skipped"] += 1
                return True

            latest_review = all_reviews[-1]
            review_data = self._parse_review_data(latest_review.body)
            
            if review_data["verdict"] == "APPROVE":
                log.info(f"  Latest review is APPROVE — skipping fix")
                self.stats["skipped"] += 1
                return True

            if review_data["critical_count"] == 0 and review_data["important_count"] == 0:
                log.info(f"  No critical or important issues — skipping fix")
                self.stats["skipped"] += 1
                return True

            # Convergence check
            if len(all_reviews) >= 2 and self._criticals_overlap(all_reviews[-1].body, all_reviews[-2].body):
                log.warning(f"  Fix agent stalled — same criticals in rounds {len(all_reviews)-1} and {len(all_reviews)}")
                if not self.dry_run:
                    try:
                        pr.add_to_labels(self.repo.get_label(LABEL_NEEDS_HUMAN))
                        pr.create_issue_comment(
                            f"⚠️ Fix agent stalled — the same critical issues were present in rounds "
                            f"{len(all_reviews)-1} and {len(all_reviews)}. Patches are not converging. "
                            f"Human intervention needed."
                            + FIX_SIGNATURE
                        )
                        tg(f"⚠️ PR #{pr.number} stalled — fix agent not converging\n{pr.html_url}")
                    except Exception: pass
                self.stats["skipped"] += 1
                return True

            affected_files = review_data["affected_files"]
            if not affected_files:
                log.warning(f"  No affected files in review data JSON")
                self.stats["skipped"] += 1
                return True

            log.info(f"  Affected files: {affected_files}")
            branch = pr.head.ref

            # Sync branch
            if not self.dry_run:
                try:
                    self.repo.merge(base=branch, head="main", commit_message=f"Merge main into {branch}")
                except Exception as e:
                    log.warning(f"  Sync failed: {e}")

            # Claim
            if not self.dry_run:
                try:
                    pr.add_to_labels(self.repo.get_label(LABEL_FIXING))
                except Exception: pass

            fixes_ready = []
            for filepath in affected_files:
                if not self.cost.check_ceiling(): break

                try:
                    contents = self.repo.get_contents(filepath, ref=branch)
                    current_content = contents.decoded_content.decode("utf-8")
                    file_sha = contents.sha
                except Exception as e:
                    log.warning(f"  Could not read {filepath}: {e}")
                    continue

                # Context history
                history_parts = []
                for i, rev in enumerate(all_reviews):
                    issues = self._extract_issues_for_file(rev.body, filepath)
                    if issues:
                        history_parts.append(f"**Round {i+1}:**\n{issues}")
                
                if not history_parts:
                    log.info(f"  No specific issues found for {filepath} in review text")
                    continue

                review_history = "\n\n---\n".join(history_parts)
                model = self.router.get("fix")
                prompt = f"## Review History\n\n{review_history}\n\n## Current File: {filepath}\n\n{current_content}"

                patched = None
                for attempt in range(2):
                    response = self.llm.complete(model=model, system=PATCH_SYSTEM, message=prompt)
                    self.cost.record(model, response, agent="fixer", action="fix")
                    patches = parse_json(response.text)
                    if patches is None:
                        prompt += "\n\nResponse was not valid JSON. Use ONLY a JSON array."
                        continue
                    patched_content, errors = apply_patches(current_content, patches)
                    if errors:
                        prompt += f"\n\nPatch failed:\n" + "\n".join(errors) + "\nFix search strings."
                        continue
                    if filepath.endswith(".py"):
                        try:
                            ast.parse(patched_content)
                        except SyntaxError as e:
                            prompt += f"\n\nSyntax error: {e}. Fix it."
                            continue
                    patched = patched_content
                    break

                if patched and patched.strip() != current_content.strip():
                    fixes_ready.append((filepath, patched, file_sha))

            if not self.dry_run:
                try:
                    pr.remove_from_labels(self.repo.get_label(LABEL_FIXING))
                except Exception: pass

            fixes_applied = []
            for filepath, patched, file_sha in fixes_ready:
                if not self.dry_run:
                    self.repo.update_file(filepath, f"fix: address review in {filepath}", patched, file_sha, branch=branch)
                    fixes_applied.append(filepath)
                else:
                    log.info(f"  [DRY RUN] Would fix {filepath}")

            if fixes_applied:
                summary = "Applied fixes for:\n" + "\n".join(f"- `{f}`" for f in fixes_applied)
                if not self.dry_run:
                    pr.create_issue_comment(summary + FIX_SIGNATURE)
                    try:
                        pr.remove_from_labels(self.repo.get_label(LABEL_REVIEWED))
                    except Exception: pass
                    tg(f"🔧 Fix agent pushed fixes to PR #{pr.number}\n{pr.html_url}")
                self.stats["fixed"] += 1
            else:
                self.stats["skipped"] += 1

            return True

        except Exception as e:
            log.error(f"  Fix failed for PR #{pr.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False

    def get_fixable_prs(self) -> list:
        """Get open PRs that have FOREMAN reviews with actionable issues."""
        pulls = self.repo.get_pulls(state="open", sort="created", direction="asc")
        fixable = []
        for pr in pulls:
            try:
                pr_labels = {l.name for l in pr.labels}
                if LABEL_FIXING in pr_labels or LABEL_NEEDS_HUMAN in pr_labels:
                    continue
                reviews = [r for r in pr.get_reviews() if r.body and BOT_SIGNATURE.strip() in r.body]
                if not reviews:
                    continue
                latest = reviews[-1]
                data = self._parse_review_data(latest.body)
                if data["verdict"] == "REQUEST_CHANGES" or (data["critical_count"] + data["important_count"] > 0):
                    fixable.append(pr)
            except Exception as e:
                log.error(f"Error checking PR #{pr.number}: {e}")
        return fixable

    def run_once(self, pr_number: int = None) -> dict:
        log.info("=" * 60)
        log.info(f"FOREMAN fixer @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        if not self.cost.check_ceiling(): return self.stats
        if pr_number:
            self.fix_pr(self.repo.get_pull(pr_number))
        else:
            queue = self.get_fixable_prs()
            for pr in queue:
                self.fix_pr(pr)
                if not self.cost.check_ceiling(): break
        log.info(f"Stats: {self.stats}")
        log.info(f"{self.cost.summary()}")
        return self.stats

def main():
    parser = argparse.ArgumentParser(description="FOREMAN Fix Agent")
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cost-summary", action="store_true")
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
        log.error("Use --pr N, --once, or --cost-summary")
        sys.exit(1)

if __name__ == "__main__":
    main()