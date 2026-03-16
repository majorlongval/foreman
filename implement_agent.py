"""
  python implement_agent.py --once          # Single pass then exit
  python implement_agent.py --issue 8       # Process a specific issue
  python implement_agent.py --dry-run       # Plan + LLM calls, no GitHub writes
  python implement_agent.py --cost-summary  # Display daily cost summary
"""
import os
import re
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from github import Github, GithubException
from cost_monitor import CostTracker
from llm_client import LLMClient, ModelRouter
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
ROUTING_PROFILE = os.environ.get("ROUTING_PROFILE", "balanced")
COST_CEILING_USD = float(os.environ.get("COST_CEILING_USD", "5.0"))
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL", "300"))
MAX_FILES_PER_ISSUE = int(os.environ.get("MAX_FILES_PER_ISSUE", "10"))
LABEL_READY = "ready"
LABEL_IMPLEMENTING = "foreman-implementing"
LABEL_READY_FOR_REVIEW = "ready-for-review"

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.implement")
# Suppress noisy internal logs
logging.getLogger("litellm").setLevel(logging.WARNING)

def get_coding_standards() -> str:
    """Reads STANDARDS.md from the repository root."""
    try:
        standards_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STANDARDS.md")
        if os.path.exists(standards_path):
            with open(standards_path, "r", encoding="utf-8") as f:
                return f.read()
        return "No specific coding standards provided."
    except Exception as e:
        log.error(f"Error reading STANDARDS.md: {e}")
        return "Error loading coding standards."

# ─── Prompts ─────────────────────────────────────────────────
PLAN_SYSTEM = """You are FOREMAN, an autonomous implementation agent.
You will receive a GitHub issue (title + structured body) and the current repository file tree.
Your job: produce a JSON implementation plan.
Output ONLY valid JSON with this exact schema:
{
  "branch": "foreman/issue-{number}-{slug}",
  "files": [
    {
      "path": "relative/path/to/file.py",
      "action": "create" or "modify",
      "description": "What this file does / what change is needed",
      "relevant_context_paths": ["path/to/existing/file/for/context"]
    }
  ],
  "pr_title": "Short imperative title (max 72 chars)",
  "pr_summary": "2-3 sentence description of the implementation approach"
}
Rules:
- Branch name: prefix "foreman/", lowercase, hyphens only, max 60 chars total
- For "modify" actions, include the file path in relevant_context_paths too
- Maximum 10 files per plan — only what directly implements the acceptance criteria
- No test files unless explicitly required by acceptance criteria
- NEVER rewrite an existing file entirely if you only need to add a few lines — use "modify" and describe the minimal change needed
- NEVER touch files unrelated to the acceptance criteria
- Prefer creating new files over modifying large existing ones
- No markdown fences. Pure JSON only."""

IMPLEMENT_SYSTEM = f"""You are FOREMAN, an autonomous code implementation agent.
You will receive a GitHub issue, an implementation plan, the specific file to write,
and contents of relevant existing files for context.
Coding Standards:
{get_coding_standards()}
Output ONLY the complete file content. No markdown fences. No explanation.
No preamble. The raw file content starts at character 0.
Rules:
- Match the existing code style exactly (imports, logging patterns, class structure)
- Follow the coding standards strictly
- Include logging statements — this runs unattended, logs are the only visibility
- Wrap everything in try/except — never let an unhandled exception crash a loop
- Keep it simple and focused. No over-engineering.
- If modifying an existing file, preserve all existing code and only add/change what's needed

Before you commit:
- PyGithub paginators: Do NOT wrap in list(). Iterate directly.
- Optimization: NEVER call get_label() inside a loop. Use string-based filtering.
- Env Vars: Use float() for all numeric environment variables unless they are strictly integer counts/limits.
- Performance: Cache expensive GitHub API results (like get_git_tree) at the instance level.
- PR Safety: Always check pr.mergeable_state == "clean" before calling pr.merge()."""

# ─── GitHub Client ────────────────────────────────────────────
class GitHubClient:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        self.gh = Github(auth=__import__("github").Auth.Token(token))
        self.repo = self.gh.get_repo(repo_name)
        self.dry_run = dry_run
        self._ensure_labels()

    def _ensure_labels(self):
        existing = {l.name for l in self.repo.get_labels()}
        needed = {
            LABEL_READY: "0075ca",              # blue
            LABEL_IMPLEMENTING: "e4a100",       # orange — in progress
            LABEL_READY_FOR_REVIEW: "e99695",   # pink — PR opened
        }
        for name, color in needed.items():
            if name not in existing:
                if not self.dry_run:
                    self.repo.create_label(name=name, color=color)
                log.info(f"  Created label: {name}")

    def get_implementation_queue(self) -> list:
        try:
            issues = self.repo.get_issues(
                state="open",
                labels=[self.repo.get_label(LABEL_READY)],
                sort="created",
                direction="asc",
            )
        except GithubException as e:
            log.error(f"  Failed to fetch issues: {e}")
            return []
        queue = []
        for issue in issues:
            labels = {l.name for l in issue.labels}
            if LABEL_IMPLEMENTING in labels:
                log.info(f"  Skipping #{issue.number} — already being implemented")
                continue
            queue.append(issue)
        return queue

    def get_issue(self, number: int):
        return self.repo.get_issue(number)

    def get_repo_tree(self) -> list[str]:
        try:
            sha = self.repo.get_branch("main").commit.sha
            tree = self.repo.get_git_tree(sha, recursive=True)
            return [item.path for item in tree.tree if item.type == "blob"]
        except GithubException as e:
            log.error(f"  Failed to get repo tree: {e}")
            return []

    def get_file_contents(self, path: str, branch: str = None) -> tuple:
        try:
            kwargs = {"ref": branch} if branch else {}
            f = self.repo.get_contents(path, **kwargs)
            return f.decoded_content.decode("utf-8"), f.sha
        except Exception:
            return None, None

    def ensure_branch(self, branch_name: str):
        if self.dry_run:
            log.info(f"  [DRY RUN] Would create branch: {branch_name}")
            return
        sha = self.repo.get_branch("main").commit.sha
        try:
            self.repo.get_git_ref(f"heads/{branch_name}")
            self.repo.get_git_ref(f"heads/{branch_name}").delete()
            log.info(f"  Deleted stale branch: {branch_name}")
        except GithubException:
            pass
        self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
        log.info(f"  Created branch: {branch_name}")

    def commit_file(self, branch: str, path: str, content: str, message: str, existing_sha: str = None):
        if self.dry_run:
            log.info(f"  [DRY RUN] Would commit {path} to {branch}")
            return
        if len(content) > 900_000:
            raise ValueError(f"Generated content too large for {path}: {len(content)} bytes")
        if path.endswith(".py"):
            import ast
            try:
                ast.parse(content)
            except SyntaxError as e:
                raise ValueError(f"Syntax error in generated {path}: {e}")
        try:
            if existing_sha:
                self.repo.update_file(path, message, content, existing_sha, branch=branch)
            else:
                self.repo.create_file(path, message, content, branch=branch)
            log.info(f"  Committed: {path}")
        except GithubException as e:
            log.error(f"  Failed to commit {path}: {e}")
            raise

    def create_pr(self, branch: str, title: str, body: str) -> object:
        if self.dry_run:
            log.info(f"  [DRY RUN] Would open PR: {title}")
            return None
        try:
            pr = self.repo.create_pull(title=title, body=body, head=branch, base="main")
            log.info(f"  Opened PR #{pr.number}: {pr.html_url}")
            return pr
        except GithubException as e:
            log.error(f"  Failed to create PR: {e}")
            raise

# ─── Implement Agent ──────────────────────────────────────────
class ImplementAgent:
    def __init__(self, github: GitHubClient, dry_run: bool = False):
        self.github = github
        self.llm = LLMClient()
        self.router = ModelRouter(ROUTING_PROFILE)
        self.cost = CostTracker(ceiling_usd=COST_CEILING_USD)
        self.dry_run = dry_run
        self.stats = {"implemented": 0, "skipped": 0, "failed": 0}
        log.info(f"\n{self.router.summary()}\n")

    def _complete(self, task: str, system: str, message: str, max_tokens: int = None):
        model = self.router.get(task)
        response = self.llm.complete(model, system, message, max_tokens)
        cost = self.cost.record(model, response, agent="implement", action=task)
        log.info(f"  💰 Cost: ${cost:.4f} | Model: {model}")
        return response

    def _parse_json(self, text: str, label: str) -> dict | None:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.error(f"  Failed to parse {label} JSON: {e}")
            log.error(f"  Raw: {raw[:500]}")
            return None

    def _slugify(self, text: str, max_len: int = 40) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug[:max_len].rstrip("-")

    def _extract_section(self, body: str, section: str) -> str:
        if not body:
            return ""
        parts = body.split(f"## {section}")
        if len(parts) < 2:
            return ""
        block = parts[1].split("##")[0].strip()
        return block

    def _build_plan_message(self, issue, file_tree: list[str]) -> str:
        tree_str = "\n".join(f"  {p}" for p in file_tree[:500])
        return (
            f"## Issue #{issue.number}: {issue.title}\n\n"
            f"{issue.body or '(no body)'}\n\n"
            f"## Repository File Tree\n\n{tree_str}"
        )

    def _build_implement_message(self, issue, plan: dict, file_spec: dict, context: dict) -> str:
        context_str = ""
        is_modify = file_spec["action"] == "modify"
        for path, content in context.items():
            limit = None if (is_modify and path == file_spec["path"]) else 20000
            body = content if limit is None else content[:limit]
            context_str += f"\n### {path}\n```\n{body}\n```\n"
        return (
            f"## Issue #{issue.number}: {issue.title}\n\n"
            f"{issue.body or ''}\n\n"
            f"## Implementation Plan\n"
            f"Branch: {plan['branch']}\n"
            f"File: {file_spec['path']}\n"
            f"Action: {file_spec['action']}\n"
            f"Description: {file_spec['description']}\n\n"
            f"## Context Files\n{context_str}"
        )

    def _build_pr_body(self, issue, plan: dict, branch: str) -> str:
        files_list = "\n".join(
            f"- `{f['path']}` ({f['action']}): {f['description']}"
            for f in plan["files"]
        )
        acceptance = self._extract_section(issue.body, "Acceptance Criteria")
        return (
            f"## Summary\n\n{plan['pr_summary']}\n\n"
            f"## Closes\n\nCloses #{issue.number}\n\n"
            f"## Files Changed\n\n{files_list}\n\n"
            f"## Acceptance Criteria\n\n{acceptance}\n\n"
            f"---\n_Implemented by FOREMAN_"
        )

    def process_issue(self, issue) -> bool:
        log.info(f"🔨 Implementing #{issue.number}: {issue.title}")
        if not self.dry_run:
            try:
                issue.add_to_labels(LABEL_IMPLEMENTING)
            except GithubException as e:
                log.error(f"  Failed to claim issue: {e}")
                return False
        try:
            file_tree = self.github.get_repo_tree()
            log.info(f"  Repo tree: {len(file_tree)} files")
            log.info("  Planning implementation...")
            plan_response = self._complete(
                task="plan",
                system=PLAN_SYSTEM,
                message=self._build_plan_message(issue, file_tree),
            )
            if not self.cost.check_ceiling():
                return False
            plan = self._parse_json(plan_response.text, "plan")
            if not plan:
                self.stats["failed"] += 1
                return False
            branch = plan["branch"]
            files = plan["files"][:MAX_FILES_PER_ISSUE]
            log.info(f"  Plan: branch={branch}, {len(files)} files")
            for f in files:
                log.info(f"    - {f['path']} ({f['action']}): {f.get('description', '')}")
            self.github.ensure_branch(branch)
            for file_spec in files:
                log.info(f"  Generating: {file_spec['path']} ({file_spec['action']})")
                context = {}
                for ctx_path in file_spec.get("relevant_context_paths", []):
                    content, _ = self.github.get_file_contents(ctx_path)
                    if content:
                        context[ctx_path] = content
                _, existing_sha = self.github.get_file_contents(file_spec["path"], branch=branch)
                if file_spec["action"] == "modify":
                    existing_content, _ = self.github.get_file_contents(file_spec["path"], branch=branch)
                    if existing_content:
                        context[file_spec["path"]] = existing_content
                impl_response = self._complete(
                    task="implement",
                    system=IMPLEMENT_SYSTEM,
                    message=self._build_implement_message(issue, plan, file_spec, context),
                )
                log.info(f"  Generated {len(impl_response.text or '')} chars for {file_spec['path']}")
                if not self.cost.check_ceiling():
                    return False
                commit_response = self._complete(
                    task="commit_msg",
                    system="Write a single-line git commit message. Imperative tone. Max 72 chars. No quotes.",
                    message=f"File: {file_spec['path']}\nDescription: {file_spec['description']}",
                    max_tokens=200,
                )
                content = impl_response.text
                if content:
                    content = content.strip()
                    if content.startswith("```"):
                        content = content.split("\n", 1)[1] if "\n" in content else content
                        content = content.rsplit("```", 1)[0].strip()
                if not content or not content.strip():
                    log.error(f"  LLM returned empty content for {file_spec['path']} — skipping")
                    self.stats["failed"] += 1
                    continue
                self.github.commit_file(
                    branch=branch,
                    path=file_spec["path"],
                    content=content,
                    message=commit_response.text.strip(),
                    existing_sha=existing_sha,
                )
                time.sleep(1)
            pr_body = self._build_pr_body(issue, plan, branch)
            pr = self.github.create_pr(
                branch=branch,
                title=plan["pr_title"],
                body=pr_body,
            )
            if pr and not self.dry_run:
                issue.create_comment(f"🤖 FOREMAN opened PR #{pr.number}: {pr.html_url}")
                issue.remove_from_labels(LABEL_READY)
                issue.remove_from_labels(LABEL_IMPLEMENTING)
                issue.add_to_labels(LABEL_READY_FOR_REVIEW)
                tg(f"🔨 PR opened for #{issue.number}: <b>{issue.title}</b>\n{pr.html_url}")
            self.stats["implemented"] += 1
            log.info(f"  ✅ Done #{issue.number}")
            return True
        except Exception as e:
            log.error(f"  ❌ Failed #{issue.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False
        finally:
            if not self.dry_run:
                try:
                    issue.remove_from_labels(LABEL_IMPLEMENTING)
                except Exception:
                    pass

    def run_once(self, issue_number: int = None) -> dict:
        log.info("=" * 60)
        log.info(f"🔄 FOREMAN implement pass @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        if not self.cost.check_ceiling():
            log.warning("💤 Parked — cost ceiling reached")
            return self.stats
        in_flight = list(self.github.repo.get_issues(state="open", labels=[self.github.repo.get_label(LABEL_IMPLEMENTING)]))
        if len(in_flight) >= 1:
            log.info(f"⏸️  {len(in_flight)} implementations already in flight — skipping")
            return self.stats
        if issue_number:
            issue = self.github.get_issue(issue_number)
            self.process_issue(issue)
        else:
            queue = self.github.get_implementation_queue()
            log.info(f"📋 Implementation queue: {len(queue)} issues")
            if not queue:
                log.info("  Nothing to implement")
            else:
                self.process_issue(queue[0])
        log.info(f"📊 Stats: {self.stats}")
        log.info(f"💰 {self.cost.summary()}")
        return self.stats

    def run_loop(self):
        log.info("🚀 FOREMAN implement agent starting")
        log.info(f"   Repo: {REPO_NAME}")
        log.info(f"   Poll interval: {POLL_INTERVAL_SEC}s")
        log.info(f"   Cost ceiling: ${COST_CEILING_USD:.2f}/session")
        log.info(f"   Dry run: {self.dry_run}")
        try:
            while True:
                self.run_once()
                log.info(f"💤 Sleeping {POLL_INTERVAL_SEC}s...")
                time.sleep(POLL_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("\n🛑 Implement agent stopped by user")
            log.info(f"📊 Final stats: {self.stats}")
            log.info(f"💰 {self.cost.summary()}")
            self.cost.save_session()

# ─── CLI ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FOREMAN Implement Agent")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--issue", type=int, default=None, help="Process a specific issue number")
    parser.add_argument("--dry-run", action="store_true", help="Plan + LLM, no GitHub writes")
    parser.add_argument("--profile", default=None, help="Routing profile: cheap, balanced, quality")
    parser.add_argument("--cost-summary", action="store_true", help="Display daily cost summary")
    args = parser.parse_args()

    global ROUTING_PROFILE
    if args.profile:
        ROUTING_PROFILE = args.profile

    if args.cost_summary:
        try:
            from cost_monitor import print_daily_summary
            print_daily_summary()
            sys.exit(0)
        except Exception as e:
            log.error(f"Failed to display cost summary: {e}")
            sys.exit(1)

    if not GITHUB_TOKEN:
        log.error("❌ GITHUB_TOKEN not set")
        sys.exit(1)
    if not REPO_NAME:
        log.error("❌ FOREMAN_REPO not set")
        sys.exit(1)

    github = GitHubClient(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)
    agent = ImplementAgent(github, dry_run=args.dry_run)
    if args.once or args.issue:
        stats = agent.run_once(issue_number=args.issue)
        if stats["failed"] > 0 and stats["implemented"] == 0:
            sys.exit(1)
    else:
        agent.run_loop()

if __name__ == "__main__":
    main()