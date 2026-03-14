import os
import logging
import json
import re
from typing import List, Dict, Any, Optional
from github import Repository, Issue, PullRequest, GithubException

from llm_client import LLMClient, ModelRouter
from duplicate_check import DuplicateChecker
from telegram_notifier import notify

log = logging.getLogger("foreman.hygiene")

class HygieneAgent:
    """
    Backlog hygiene agent that closes stale or already-implemented issues
    and flags duplicates using PR analysis and LLM codebase auditing.
    """

    def __init__(self, repo: Repository.Repository, dry_run: bool = False):
        self.repo = repo
        self.dry_run = dry_run
        self.llm = LLMClient()
        self.router = ModelRouter(profile=os.environ.get("ROUTING_PROFILE", "balanced"))
        self.duplicate_checker = DuplicateChecker(repo)
        
        self.protected_label = "protected"
        self.needs_human_label = "needs-human"
        self.duplicate_label = "duplicate"
        self.audited_label = "hygiene-audited"
        
        self.confidence_threshold_close = 0.95
        self.confidence_threshold_flag = 0.75
        self._cached_paths = None

    def run(self):
        """Orchestrate the hygiene process across all open issues."""
        log.info(f"🚀 Starting Backlog Hygiene Agent (dry_run={self.dry_run})")
        stats = {"closed": 0, "flagged": 0, "duplicates": 0, "processed": 0}
        
        try:
            # Get up to 50 open issues, processing older ones first to control API costs
            open_issues = self.repo.get_issues(state="open", sort="created", direction="asc")[:50]
            log.info(f"Found {len(open_issues)} open issues to process this run.")
            
            # Fetch recent merged PRs for reference check
            merged_prs = []
            try:
                prs = self.repo.get_pulls(state="closed", sort="updated", direction="desc")[:100]
                merged_prs = [pr for pr in prs if pr.merged]
                log.info(f"Fetched {len(merged_prs)} recent merged PRs for reference checking.")
            except Exception as e:
                log.warning(f"Failed to fetch merged PRs: {e}")

            for issue in open_issues:
                try:
                    # Skip Pull Requests (GitHub API /issues returns both)
                    if issue.pull_request:
                        continue
                    
                    labels = [l.name for l in issue.get_labels()]
                    if self.protected_label in labels:
                        log.info(f"  Skipping protected issue #{issue.number}")
                        continue
                    
                    # Skip if already flagged for human, as duplicate, or previously audited to avoid repetitive actions
                    if self.needs_human_label in labels or self.duplicate_label in labels or self.audited_label in labels:
                        continue

                    stats["processed"] += 1
                    log.info(f"🔍 Auditing issue #{issue.number}: {issue.title}")
                    
                    # 1. Check Merged PRs for references
                    pr_ref = self._check_merged_prs(issue, merged_prs)
                    if pr_ref:
                        self._close_issue(issue, f"Closed: This issue appears to be implemented by merged PR #{pr_ref.number} ('{pr_ref.title}').")
                        stats["closed"] += 1
                        continue

                    # 2. Check Near-duplicates among other open issues
                    duplicate = self.duplicate_checker.is_duplicate(issue.title, issue.body or "")
                    if duplicate and duplicate["number"] < issue.number:
                        # Only flag the newer issue as a duplicate of the older one
                        self._flag_duplicate(issue, duplicate)
                        stats["duplicates"] += 1
                        continue

                    # 3. LLM-based codebase content audit
                    impl_check = self._check_codebase_implementation(issue)
                    if impl_check["confidence"] >= self.confidence_threshold_close:
                        self._close_issue(issue, f"Automatically closed: Codebase appears to already implement this feature.\n\n<b>Explanation:</b> {impl_check['explanation']}")
                        stats["closed"] += 1
                    elif impl_check["confidence"] >= self.confidence_threshold_flag:
                        self._flag_needs_human(issue, f"Possible existing implementation detected (Confidence: {impl_check['confidence']:.2f}).\n\n<b>Explanation:</b> {impl_check['explanation']}")
                        stats["flagged"] += 1
                    else:
                        # Add audited label to prevent infinite LLM re-evaluation loops on stale issues
                        if not self.dry_run:
                            try:
                                issue.add_to_labels(self.audited_label)
                            except Exception as e:
                                log.error(f"  Failed to add {self.audited_label} label to #{issue.number}: {e}")

                except Exception as e:
                    log.error(f"  Error processing issue #{issue.number}: {e}")

            summary = (
                f"🧹 <b>Backlog Hygiene Summary</b>\n"
                f"• Processed: {stats['processed']}\n"
                f"• Closed: {stats['closed']}\n"
                f"• Duplicates: {stats['duplicates']}\n"
                f"• Needs Review: {stats['flagged']}\n"
                f"Dry run: {self.dry_run}"
            )
            log.info(summary.replace("<b>", "").replace("</b>", ""))
            notify(summary)

        except Exception as e:
            log.error(f"❌ Hygiene Agent run failed: {e}", exc_info=True)

    def _check_merged_prs(self, issue: Issue.Issue, prs: List[PullRequest.PullRequest]) -> Optional[PullRequest.PullRequest]:
        """Check if any merged PR references this issue number or title."""
        ref_patterns = [
            re.compile(rf"\b(close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#{issue.number}\b", re.I),
            re.compile(rf"#{issue.number}\b")
        ]
        
        for pr in prs:
            # Check PR body for "closes #N" etc
            if pr.body:
                for pattern in ref_patterns:
                    if pattern.search(pr.body):
                        log.info(f"  Found reference to #{issue.number} in PR #{pr.number} body")
                        return pr
            
            # Check PR title for issue number
            if f"#{issue.number}" in pr.title:
                log.info(f"  Found reference to #{issue.number} in PR #{pr.number} title")
                return pr
            
            # Heuristic match for title (ignoring common prefixes)
            clean_issue_title = issue.title.lower().strip()
            clean_pr_title = pr.title.lower().replace("closes", "").replace("fixes", "").replace("implement", "").strip()
            if len(clean_issue_title) > 15 and clean_issue_title in clean_pr_title:
                log.info(f"  Issue title matches PR #{pr.number} title")
                return pr
        
        return None

    def _check_codebase_implementation(self, issue: Issue.Issue) -> Dict[str, Any]:
        """Use LLM to compare issue description against relevant codebase files."""
        try:
            # 1. Fetch file list and select relevant files
            if self._cached_paths is None:
                tree = self.repo.get_git_tree(self.repo.default_branch, recursive=True).tree
                self._cached_paths = [
                    item.path for item in tree 
                    if item.type == "blob" 
                    and not any(x in item.path for x in ("node_modules", "dist", "vendor"))
                    and not item.path.startswith(".") 
                    and "/." not in item.path
                ]
            
            paths = self._cached_paths
            
            # Heuristic: match keywords from issue title to file paths
            keywords = [k.lower() for k in re.findall(r'\w+', issue.title) if len(k) > 3]
            scored_paths = []
            for p in paths:
                score = sum(2 if kw in p.lower() else 0 for kw in keywords)
                if "/" not in p: score += 1 # Root files
                if p.endswith((".py", ".js", ".ts", ".go")): score += 1
                if score > 0:
                    scored_paths.append((score, p))
            
            relevant_paths = [p for s, p in sorted(scored_paths, key=lambda x: x[0], reverse=True)[:6]]
            
            if not relevant_paths:
                relevant_paths = [p for p in paths if "/" not in p][:5]

            # 2. Load context
            context = ""
            for path in relevant_paths:
                try:
                    content = self.repo.get_contents(path).decoded_content.decode("utf-8")
                    context += f"\n--- FILE: {path} ---\n{content[:2500]}\n"
                except:
                    continue

            if not context:
                return {"confidence": 0.0, "explanation": "No relevant files found."}

            # 3. Ask LLM
            system = (
                "You are an expert code auditor. Given an issue and code snippets, determine if the issue is ALREADY implemented. "
                "Respond strictly in JSON: {\"confidence\": float (0.0-1.0), \"explanation\": \"string\"}. "
                "Confidence > 0.9 means you are certain it exists. 0.7-0.9 means likely but requires review."
            )
            
            prompt = (
                f"ISSUE TITLE: {issue.title}\nISSUE BODY: {issue.body}\n\n"
                f"CODE CONTEXT:\n{context}\n\n"
                f"Is this already implemented? Return JSON."
            )
            
            response = self.llm.complete(
                model=self.router.get("review"),
                system=system,
                message=prompt
            )
            
            # Parse JSON from response
            match = re.search(r"\{.*\}", response.text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            
            return {"confidence": 0.0, "explanation": "Failed to parse LLM response."}
            
        except Exception as e:
            log.warning(f"  Codebase check failed for #{issue.number}: {e}")
            return {"confidence": 0.0, "explanation": f"Audit failed: {str(e)}"}

    def _close_issue(self, issue: Issue.Issue, comment: str):
        log.info(f"  -> ACTION: Close #{issue.number}")
        if self.dry_run:
            log.info(f"  [DRY RUN] Would close #{issue.number}")
            return
        try:
            issue.create_comment(comment)
            issue.edit(state="closed")
        except Exception as e:
            log.error(f"  Failed to close issue #{issue.number}: {e}")

    def _flag_duplicate(self, issue: Issue.Issue, duplicate_info: Dict):
        log.info(f"  -> ACTION: Flag duplicate #{issue.number} (of #{duplicate_info['number']})")
        if self.dry_run:
            log.info(f"  [DRY RUN] Would flag #{issue.number} as duplicate")
            return
        try:
            comment = f"Potential duplicate of #{duplicate_info['number']} (Similarity: {duplicate_info['score']:.2f})."
            issue.create_comment(comment)
            issue.add_to_labels(self.duplicate_label)
        except Exception as e:
            log.error(f"  Failed to label duplicate #{issue.number}: {e}")

    def _flag_needs_human(self, issue: Issue.Issue, comment: str):
        log.info(f"  -> ACTION: Flag needs-human #{issue.number}")
        if self.dry_run:
            log.info(f"  [DRY RUN] Would flag #{issue.number} for review")
            return
        try:
            issue.create_comment(comment)
            issue.add_to_labels(self.needs_human_label)
            notify(f"🔎 <b>Hygiene Alert</b>\nIssue #{issue.number} might be implemented. Review required.\n{issue.title}")
        except Exception as e:
            log.error(f"  Failed to label needs-human #{issue.number}: {e}")


if __name__ == "__main__":
    import sys
    from github import Github
    
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    
    if not token or not repo_name:
        print("GITHUB_TOKEN and GITHUB_REPOSITORY environment variables required.")
        sys.exit(1)
        
    g = Github(token)
    repo = g.get_repo(repo_name)
    
    dry_run = "--dry-run" in sys.argv
    agent = HygieneAgent(repo, dry_run=dry_run)
    agent.run()