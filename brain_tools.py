"""
FOREMAN Brain Tools — GitHub tool schemas and implementations for the Brain.

Defines TOOL_SCHEMAS (Claude API format) and implementation functions that
operate on a PyGithub repo object.  Called from the Brain's Telegram handler
via run_in_executor.
"""

import os
import math
import logging
import numpy as np
from github import Repository
from openai import OpenAI

log = logging.getLogger("foreman.brain.tools")

# Configuration for duplicate detection
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.9"))

# ─── Tool Schemas (Claude API format) ────────────────────────

TOOL_SCHEMAS = [
    {
        "name": "get_project_status",
        "description": (
            "Get a summary of the project's current status: open issues grouped "
            "by label and open pull requests with their review state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_issue",
        "description": (
            "Get full details of a GitHub issue including title, body, labels, "
            "assignees, state, and the most recent comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "The issue number.",
                },
            },
            "required": ["number"],
        },
    },
    {
        "name": "get_pr",
        "description": (
            "Get full details of a pull request including title, body, state, "
            "changed files, reviews, and recent inline review comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "The pull request number.",
                },
            },
            "required": ["number"],
        },
    },
    {
        "name": "label_issue",
        "description": (
            "Add a label to an issue. Use 'ready' to trigger the implement agent. "
            "Use 'needs-refinement' to queue it for the seed agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "The issue or PR number.",
                },
                "label": {
                    "type": "string",
                    "description": "The label name to add.",
                },
            },
            "required": ["number", "label"],
        },
    },
    {
        "name": "merge_pr",
        "description": "Merge a pull request. Checks that the PR is mergeable before proceeding.",
        "input_schema": {
            "type": "object",
            "properties": {
                "number": {
                    "type": "integer",
                    "description": "The pull request number to merge.",
                },
            },
            "required": ["number"],
        },
    },
    {
        "name": "create_issue",
        "description": (
            "Create a new draft issue on GitHub. This is used for brainstorming. "
            "Automatically checks for semantic duplicates before creating."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The title of the issue.",
                },
                "body": {
                    "type": "string",
                    "description": "The detailed description of the issue.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply, e.g. ['brainstorm'].",
                },
            },
            "required": ["title", "body"],
        },
    },
]

# ─── Semantic Duplicate Check ────────────────────────────────

def get_embedding(text: str) -> list[float]:
    """Generate an embedding for the given text using OpenAI API."""
    try:
        # Assumes OPENAI_API_KEY is in env
        client = OpenAI()
        text = text.replace("\n", " ")
        response = client.embeddings.create(input=[text], model="text-embedding-3-small")
        return response.data[0].embedding
    except Exception as e:
        log.error(f"Error generating embedding: {e}")
        return []

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not v1 or not v2:
        return 0.0
    a = np.array(v1)
    b = np.array(v2)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def is_duplicate_issue(repo: Repository.Repository, title: str, body: str) -> tuple[bool, int]:
    """Check if a new issue is semantically similar to any open issue."""
    try:
        new_text = f"{title}\n{body}"
        new_embedding = get_embedding(new_text)
        if not new_embedding:
            return False, 0

        open_issues = repo.get_issues(state="open")
        for issue in open_issues:
            if issue.pull_request:
                continue
            
            existing_text = f"{issue.title}\n{issue.body or ''}"
            existing_embedding = get_embedding(existing_text)
            
            similarity = cosine_similarity(new_embedding, existing_embedding)
            if similarity >= SIMILARITY_THRESHOLD:
                log.info(f"Duplicate detected! New issue '{title}' is {similarity:.2f} similar to #{issue.number}")
                return True, issue.number
                
        return False, 0
    except Exception as e:
        log.error(f"Error checking for duplicate issues: {e}")
        return False, 0

# ─── Implementations ─────────────────────────────────────────

def get_project_status(repo: Repository.Repository):
    try:
        issues = repo.get_issues(state="open")
        pr_list = repo.get_pulls(state="open")
        
        status = "Open Issues:\n"
        for issue in issues:
            if not issue.pull_request:
                labels = ", ".join([l.name for l in issue.labels])
                status += f"- #{issue.number}: {issue.title} [{labels}]\n"
        
        status += "\nOpen Pull Requests:\n"
        for pr in pr_list:
            status += f"- #{pr.number}: {pr.title} (Mergeable: {pr.mergeable_state})\n"
            
        return status
    except Exception as e:
        log.error(f"Error in get_project_status: {e}")
        return f"Error: {str(e)}"

def get_issue(repo: Repository.Repository, number: int):
    try:
        issue = repo.get_issue(number)
        comments = issue.get_comments().get_page(0)
        comment_str = "\n".join([f"{c.user.login}: {c.body}" for c in comments[-5:]])
        return {
            "number": issue.number,
            "title": issue.title,
            "body": issue.body,
            "state": issue.state,
            "labels": [l.name for l in issue.labels],
            "recent_comments": comment_str
        }
    except Exception as e:
        log.error(f"Error in get_issue: {e}")
        return f"Error: {str(e)}"

def get_pr(repo: Repository.Repository, number: int):
    try:
        pr = repo.get_pull(number)
        return {
            "number": pr.number,
            "title": pr.title,
            "body": pr.body,
            "state": pr.state,
            "changed_files": pr.changed_files,
            "mergeable": pr.mergeable
        }
    except Exception as e:
        log.error(f"Error in get_pr: {e}")
        return f"Error: {str(e)}"

def label_issue(repo: Repository.Repository, number: int, label: str):
    try:
        issue = repo.get_issue(number)
        issue.add_to_labels(label)
        log.info(f"Added label '{label}' to #{number}")
        return f"Labeled #{number} with {label}"
    except Exception as e:
        log.error(f"Error in label_issue: {e}")
        return f"Error: {str(e)}"

def merge_pr(repo: Repository.Repository, number: int):
    try:
        pr = repo.get_pull(number)
        if pr.mergeable:
            pr.merge()
            log.info(f"Merged PR #{number}")
            return f"Merged PR #{number}"
        else:
            return f"PR #{number} is not mergeable."
    except Exception as e:
        log.error(f"Error in merge_pr: {e}")
        return f"Error: {str(e)}"

def create_issue(repo: Repository.Repository, title: str, body: str, labels: list[str] = None):
    try:
        is_dup, dup_number = is_duplicate_issue(repo, title, body)
        if is_dup:
            msg = f"Aborted creating issue '{title}'. It is a semantic duplicate of existing issue #{dup_number}."
            log.warning(msg)
            return msg

        issue = repo.create_issue(title=title, body=body, labels=labels or [])
        log.info(f"Created issue #{issue.number}: {title}")
        return f"Created issue #{issue.number}"
    except Exception as e:
        log.error(f"Error in create_issue: {e}")
        return f"Error: {str(e)}"