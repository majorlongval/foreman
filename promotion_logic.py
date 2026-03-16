import logging
from datetime import datetime, timezone, timedelta
from github import GithubException

# Logging setup
log = logging.getLogger("foreman.promotion")

class IssuePromoter:
    """
    Handles the logic for promoting issues from 'auto-refined' to 'ready'
    after a cooling period, ensuring they aren't on 'hold'.
    """

    def __init__(self, github_client, dry_run: bool = False):
        self.github = github_client
        self.dry_run = dry_run
        # Use constants from the environment/client if available, otherwise defaults
        self.label_auto_refined = "auto-refined"
        self.label_ready = "ready"
        self.label_hold = "hold"
        # 24 hours is the requirement from the issue, though seed_agent uses a different env var
        # We'll default to 24.0 unless overridden by the agent's config
        self.promo_delay_hours = 24.0

    def get_stale_refined_issues(self):
        """
        Identifies issues with 'auto-refined' label that are older than the threshold
        and do not have a 'hold' label.
        """
        stale_issues = []
        try:
            # Note: seed_agent.py has a get_auto_refined_issues method we should leverage
            # or replicate the logic here to be self-contained for the promotion_logic module.
            issues = self.github.repo.get_issues(
                state="open",
                labels=[self.label_auto_refined],
                sort="created",
                direction="asc"
            )

            now = datetime.now(timezone.utc)
            threshold = timedelta(hours=self.promo_delay_hours)

            for issue in issues:
                try:
                    labels = {l.name for l in issue.labels}
                    
                    # 1. Check for hold label
                    if self.label_hold in labels:
                        log.info(f"Skipping #{issue.number} - has '{self.label_hold}' label.")
                        continue

                    # 2. Check timing
                    # We look at the 'labeled' event for 'auto-refined' to be precise
                    # but fallback to created_at if event history is messy.
                    refined_at = None
                    try:
                        for event in issue.get_events():
                            if event.event == "labeled" and event.label.name == self.label_auto_refined:
                                refined_at = event.created_at
                                # We want the latest time it was labeled 'auto-refined'
                    except Exception as e:
                        log.warning(f"Could not retrieve events for #{issue.number}: {e}")

                    if not refined_at:
                        refined_at = issue.created_at

                    # Ensure timezone awareness
                    if refined_at.tzinfo is None:
                        refined_at = refined_at.replace(tzinfo=timezone.utc)

                    age = now - refined_at
                    if age >= threshold:
                        log.info(f"Issue #{issue.number} is stale ({age.total_seconds()/3600:.1f}h old).")
                        stale_issues.append(issue)
                    else:
                        log.debug(f"Issue #{issue.number} is only {age.total_seconds()/3600:.1f}h old. Waiting.")

                except Exception as e:
                    log.error(f"Error processing issue #{issue.number} for promotion: {e}")
                    continue

        except Exception as e:
            log.error(f"Error fetching issues for promotion: {e}")

        return stale_issues

    def promote_issue(self, issue):
        """
        Updates labels and posts the promotion comment.
        """
        try:
            log.info(f"Promoting issue #{issue.number}: {issue.title}")
            
            comment_text = "Automated Promotion: This issue has passed the 24-hour review period and is now ready for development."

            if self.dry_run:
                log.info(f"[DRY RUN] Would remove '{self.label_auto_refined}', add '{self.label_ready}', and comment on #{issue.number}")
                return True

            # Perform actions
            # Note: remove_from_labels/add_to_labels are the PyGithub methods
            issue.remove_from_labels(self.label_auto_refined)
            issue.add_to_labels(self.label_ready)
            issue.create_comment(comment_text)
            
            log.info(f"Successfully promoted #{issue.number} to '{self.label_ready}'")
            return True

        except GithubException as ge:
            log.error(f"GitHub API error promoting #{issue.number}: {ge}")
            return False
        except Exception as e:
            log.error(f"Unexpected error promoting #{issue.number}: {e}")
            return False

def check_and_promote(github_client, dry_run: bool = False, delay_hours: float = 24.0):
    """
    Main entry point for the promotion logic.
    """
    log.info("Starting automated issue promotion check...")
    try:
        promoter = IssuePromoter(github_client, dry_run=dry_run)
        promoter.promo_delay_hours = delay_hours
        
        stale_issues = promoter.get_stale_refined_issues()
        if not stale_issues:
            log.info("No issues ready for promotion at this time.")
            return 0

        promoted_count = 0
        for issue in stale_issues:
            if promoter.promote_issue(issue):
                promoted_count += 1
        
        log.info(f"Promotion cycle complete. Promoted {promoted_count} issues.")
        return promoted_count

    except Exception as e:
        log.error(f"Critical error in check_and_promote: {e}")
        return 0