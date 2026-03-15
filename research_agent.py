import os
import re
import sys
import json
import time
import logging
import argparse
from datetime import datetime, timezone
from github import Github, GithubException

from llm_client import LLMClient
from telegram_notifier import notify as tg

# ─── Configuration ────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("FOREMAN_REPO", "")
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
POLL_INTERVAL_SEC = int(os.environ.get("POLL_INTERVAL", "300"))

LABEL_READY = "ready"
LABEL_RESEARCH = "research"
LABEL_RESEARCHING = "foreman-researching"
LABEL_READY_FOR_REVIEW = "ready-for-review"

RESEARCH_MODEL = "perplexity/sonar-reasoning-pro"

# ─── Logging ──────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("foreman.research")

# ─── GitHub Client ────────────────────────────────────────────
class GitHubClient:
    def __init__(self, token: str, repo_name: str, dry_run: bool = False):
        try:
            self.gh = Github(auth=__import__("github").Auth.Token(token))
            self.repo = self.gh.get_repo(repo_name)
            self.dry_run = dry_run
            self._ensure_labels()
        except Exception as e:
            log.error(f"Failed to initialize GitHub client: {e}")
            raise

    def _ensure_labels(self):
        try:
            existing = {l.name for l in self.repo.get_labels()}
            needed = {
                LABEL_READY: "0075ca",
                LABEL_RESEARCH: "fbca04",
                LABEL_RESEARCHING: "e4a100",
                LABEL_READY_FOR_REVIEW: "e99695",
            }
            for name, color in needed.items():
                if name not in existing:
                    if not self.dry_run:
                        self.repo.create_label(name=name, color=color)
                    log.info(f"  Created label: {name}")
        except Exception as e:
            log.error(f"Error ensuring labels: {e}")

    def get_research_queue(self) -> list:
        try:
            # Issues with 'research' AND 'ready'
            issues = self.repo.get_issues(
                state="open",
                labels=[self.repo.get_label(LABEL_READY), self.repo.get_label(LABEL_RESEARCH)],
                sort="created",
                direction="asc",
            )
            queue = []
            for issue in issues:
                labels = {l.name for l in issue.labels}
                if LABEL_RESEARCHING in labels:
                    log.info(f"  Skipping #{issue.number} — already being researched")
                    continue
                queue.append(issue)
            return queue
        except Exception as e:
            log.error(f"Failed to fetch research queue: {e}")
            return []

    def get_issue(self, number: int):
        return self.repo.get_issue(number)

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
            log.info(f"  Branch {branch_name} already exists.")
        except GithubException:
            self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=sha)
            log.info(f"  Created branch: {branch_name}")

    def commit_file(self, branch: str, path: str, content: str, message: str, existing_sha: str = None):
        if self.dry_run:
            log.info(f"  [DRY RUN] Would commit {path} to {branch}")
            return
        try:
            if existing_sha:
                self.repo.update_file(path, message, content, existing_sha, branch=branch)
            else:
                self.repo.create_file(path, message, content, branch=branch)
            log.info(f"  Committed: {path}")
        except Exception as e:
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
        except Exception as e:
            log.error(f"  Failed to create PR: {e}")
            raise

# ─── Research Agent ───────────────────────────────────────────
class ResearchAgent:
    def __init__(self, github: GitHubClient, dry_run: bool = False):
        self.github = github
        self.llm = LLMClient()
        self.dry_run = dry_run
        self.stats = {"researched": 0, "failed": 0}

    def _slugify(self, text: str, max_len: int = 40) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
        return slug[:max_len].rstrip("-")

    def _build_prompt(self, issue) -> str:
        return (
            f"Please conduct detailed research and provide a summary for the following topic:\n\n"
            f"Topic: {issue.title}\n"
            f"Context: {issue.body or 'No body provided.'}\n\n"
            f"Format your response as a professional Markdown document. "
            f"Include an Executive Summary, Detailed Findings, and a Conclusion or Recommendations section. "
            f"Cite your sources with URLs where applicable."
        )

    def process_issue(self, issue) -> bool:
        log.info(f"🔍 Researching #{issue.number}: {issue.title}")
        if not self.dry_run:
            try:
                issue.add_to_labels(LABEL_RESEARCHING)
            except Exception as e:
                log.error(f"  Failed to claim issue: {e}")
                return False

        try:
            slug = self._slugify(issue.title)
            branch = f"foreman/research-{issue.number}-{slug}"
            file_path = f"docs/research/{slug}.md"

            log.info(f"  Querying {RESEARCH_MODEL}...")
            system_msg = "You are a specialized research agent. Your goal is to provide deep, cited research on technical or business topics."
            user_msg = self._build_prompt(issue)

            # Perplexity models require specific handling which LLMClient + LiteLLM should manage
            response = self.llm.complete(
                model=RESEARCH_MODEL,
                system=system_msg,
                message=user_msg
            )

            if not response.text or not response.text.strip():
                log.error("  Received empty response from LLM")
                return False

            content = response.text
            log.info(f"  Generated {len(content)} characters of research.")

            self.github.ensure_branch(branch)
            _, existing_sha = self.github.get_file_contents(file_path, branch=branch)
            
            self.github.commit_file(
                branch=branch,
                path=file_path,
                content=content,
                message=f"Add research summary for issue #{issue.number}",
                existing_sha=existing_sha
            )

            pr_body = (
                f"## Research Summary\n\n"
                f"This PR contains the research summary for issue #{issue.number}.\n\n"
                f"**Topic:** {issue.title}\n"
                f"**Generated File:** `{file_path}`\n\n"
                f"Closes #{issue.number}\n\n"
                f"---\n_Researched by FOREMAN via Perplexity API_"
            )
            
            pr = self.github.create_pr(
                branch=branch,
                title=f"Research: {issue.title}",
                body=pr_body
            )

            if pr and not self.dry_run:
                issue.create_comment(f"🤖 Research complete. View results in PR #{pr.number}: {pr.html_url}")
                issue.remove_from_labels(LABEL_READY)
                issue.remove_from_labels(LABEL_RESEARCH)
                issue.remove_from_labels(LABEL_RESEARCHING)
                issue.add_to_labels(LABEL_READY_FOR_REVIEW)
                tg(f"🔍 Research PR opened for #{issue.number}: <b>{issue.title}</b>\n{pr.html_url}")

            self.stats["researched"] += 1
            return True

        except Exception as e:
            log.error(f"  ❌ Research failed for #{issue.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            return False
        finally:
            if not self.dry_run:
                try:
                    issue.remove_from_labels(LABEL_RESEARCHING)
                except Exception:
                    pass

    def run_once(self, issue_number: int = None) -> dict:
        log.info("-" * 40)
        log.info(f"🔄 Research Cycle @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
        
        try:
            if issue_number:
                issue = self.github.get_issue(issue_number)
                self.process_issue(issue)
            else:
                queue = self.github.get_research_queue()
                log.info(f"📋 Research queue: {len(queue)} issues")
                if queue:
                    self.process_issue(queue[0])
                else:
                    log.info("  No research tasks pending.")
        except Exception as e:
            log.error(f"Cycle error: {e}")

        log.info(f"📊 Current session stats: {self.stats}")
        return self.stats

# ─── Main ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="FOREMAN Research Agent")
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--issue", type=int, default=None, help="Process a specific issue number")
    parser.add_argument("--dry-run", action="store_true", help="No GitHub writes")
    args = parser.parse_args()

    if not GITHUB_TOKEN or not REPO_NAME:
        log.error("❌ GITHUB_TOKEN and FOREMAN_REPO environment variables are required.")
        sys.exit(1)
    
    if not PERPLEXITY_API_KEY:
        log.warning("⚠️ PERPLEXITY_API_KEY not set. Research queries will likely fail.")

    try:
        github = GitHubClient(GITHUB_TOKEN, REPO_NAME, dry_run=args.dry_run)
        agent = ResearchAgent(github, dry_run=args.dry_run)

        if args.once or args.issue:
            agent.run_once(issue_number=args.issue)
        else:
            log.info(f"🚀 Research Agent started (Repo: {REPO_NAME})")
            while True:
                agent.run_once()
                log.info(f"💤 Sleeping {POLL_INTERVAL_SEC}s...")
                time.sleep(POLL_INTERVAL_SEC)
    except KeyboardInterrupt:
        log.info("\n🛑 Agent stopped by user")
    except Exception as e:
        log.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()