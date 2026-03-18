"""Seed toolset — minimal tools the brain ships with.

Includes tools for file manipulation, issue/PR management, memory, and communication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from brain.cost_tracking import load_today_spend
from brain.memory import MemoryStore

log = logging.getLogger("foreman.brain.tools")


@dataclass
class ToolContext:
    """Everything tools need to operate."""

    repo: object  # PyGithub Repository
    memory_root: Path
    agent_name: str
    notify_fn: Callable[[str], bool]
    costs_dir: Path
    budget_limit: float = 5.0
    agent_role: str = ""


TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": "Read a file from the repository's main branch.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to repo root."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_issue",
        "description": "Create a new GitHub issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title."},
                "body": {"type": "string", "description": "Issue body (Markdown)."},
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply.",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "create_pr",
        "description": "Create a branch, commit files, and open a pull request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name to create."},
                "title": {"type": "string", "description": "PR title."},
                "body": {"type": "string", "description": "PR body (Markdown)."},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                    "description": "Files to commit.",
                },
            },
            "required": ["branch", "title", "body", "files"],
        },
    },
    {
        "name": "read_memory",
        "description": (
            "Read a memory file. Use 'agent_name/file.md' for own memory "
            "or 'shared/subdir/file.md' for shared."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Memory path (e.g., 'gandalf/notes.md' or "
                        "'shared/costs/2026-03-15.md')."
                    ),
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_memory",
        "description": "Write a memory file. Can only write to own memory or shared/.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Memory path to write."},
                "content": {"type": "string", "description": "Content to write."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "send_telegram",
        "description": "Send a message to Jord via Telegram.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text."},
            },
            "required": ["message"],
        },
    },
    {
        "name": "check_budget",
        "description": "Check remaining budget for today.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_issues",
        "description": "List open GitHub issues with labels.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_prs",
        "description": "List open pull requests with status.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_pr",
        "description": (
            "Read a pull request: title, body, changed files, diff, "
            "and existing comments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to read."},
            },
            "required": ["pr_number"],
        },
    },
    {
        "name": "post_comment",
        "description": "Post a comment on a pull request.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to comment on."},
                "body": {"type": "string", "description": "Comment text (Markdown)."},
            },
            "required": ["pr_number", "body"],
        },
    },
    {
        "name": "approve_pr",
        "description": "Approve a pull request. Only available to the critic role.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to approve."},
                "comment": {"type": "string", "description": "Review comment."},
            },
            "required": ["pr_number", "comment"],
        },
    },
    {
        "name": "list_files",
        "description": (
            "List files and directories in a repo path. "
            "Use this to explore the repo before proposing changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path relative to repo root. Defaults to root.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "merge_pr",
        "description": "Squash-merge an approved pull request. Only available to the critic role.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to merge."},
            },
            "required": ["pr_number"],
        },
    },
    {
        "name": "close_issue",
        "description": "Close a GitHub issue, optionally posting a closing comment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_number": {"type": "integer", "description": "Issue number to close."},
                "comment": {"type": "string", "description": "Optional closing comment."},
            },
            "required": ["issue_number"],
        },
    },
    {
        "name": "close_pr",
        "description": "Close a pull request without merging, optionally posting a comment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to close."},
                "comment": {"type": "string", "description": "Optional closing comment."},
            },
            "required": ["pr_number"],
        },
    },
    {
        "name": "push_to_pr",
        "description": (
            "Push additional commits to an existing pull request's branch. "
            "Use this to address review feedback — do NOT open a second PR. "
            "Finds the PR's head branch and commits the provided files there."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pr_number": {"type": "integer", "description": "PR number to push to."},
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                    "description": "Files to commit to the PR branch.",
                },
            },
            "required": ["pr_number", "files"],
        },
    },
    {
        "name": "update_issue",
        "description": "Update an existing GitHub issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_number": {"type": "integer", "description": "Issue number to update."},
                "title": {"type": "string", "description": "New title."},
                "body": {"type": "string", "description": "New body (Markdown)."},
                "state": {
                    "type": "string",
                    "description": "Status of the issue (open or closed).",
                    "enum": ["open", "closed"],
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply (replaces existing labels).",
                },
            },
            "required": ["issue_number"],
        },
    },
    {
        "name": "post_issue_comment",
        "description": "Post a comment on a GitHub issue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "issue_number": {"type": "integer", "description": "Issue number to comment on."},
                "body": {"type": "string", "description": "Comment text (Markdown)."},
            },
            "required": ["issue_number", "body"],
        },
    },
]


def execute_tool(name: str, tool_input: dict, ctx: ToolContext) -> str:
    """Dispatch a tool call by name. Returns a string result."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'"
    try:
        return handler(tool_input, ctx)
    except Exception as e:
        log.error(f"Tool {name} failed: {e}")
        return f"Error executing {name}: {e}"


# ── Handler implementations ──────────────────────────────────


def _read_file(tool_input: dict, ctx: ToolContext) -> str:
    try:
        content = ctx.repo.get_contents(tool_input["path"], ref="main")
        text = content.decoded_content.decode("utf-8")
        if len(text) > 50000:
            return f"{text[:50000]}\n\n--- truncated ({len(text)} total chars) ---"
        return text
    except Exception as e:
        return f"Error reading '{tool_input['path']}': {e}"


def _create_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        label_objects = []
        for name in tool_input.get("labels", []):
            try:
                label_objects.append(ctx.repo.get_label(name))
            except Exception:
                pass
        issue = ctx.repo.create_issue(
            title=tool_input["title"],
            body=tool_input["body"],
            labels=label_objects,
        )
        return f"Issue #{issue.number} created: {issue.html_url}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _create_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        base_branch = ctx.repo.get_branch("main")
        ctx.repo.create_git_ref(
            ref=f"refs/heads/{tool_input['branch']}",
            sha=base_branch.commit.sha,
        )

        for file in tool_input["files"]:
            try:
                # Check if file already exists to get its SHA for update
                contents = ctx.repo.get_contents(file["path"], ref=tool_input["branch"])
                ctx.repo.update_file(
                    path=file["path"],
                    message=f"Update {file['path']}",
                    content=file["content"],
                    sha=contents.sha,
                    branch=tool_input["branch"],
                )
            except Exception:
                # File doesn't exist, create it
                ctx.repo.create_file(
                    path=file["path"],
                    message=f"Create {file['path']}",
                    content=file["content"],
                    branch=tool_input["branch"],
                )

        pr = ctx.repo.create_pull(
            title=tool_input["title"],
            body=tool_input["body"],
            head=tool_input["branch"],
            base="main",
        )
        return f"PR #{pr.number} created: {pr.html_url}"
    except Exception as e:
        return f"Error creating PR: {e}"


def _read_memory(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path_parts = tool_input["path"].split("/")
        if len(path_parts) < 2:
            return "Error: path must be in 'owner/filename' format"
        owner = path_parts[0]
        filename = "/".join(path_parts[1:])

        store = MemoryStore(ctx.memory_root, ctx.agent_name)
        content = store.read(owner, filename)
        if content is None:
            return f"Memory not found: {tool_input['path']}"
        return content
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error reading memory: {e}"


def _write_memory(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path_parts = tool_input["path"].split("/")
        if len(path_parts) < 2:
            return "Error: path must be in 'owner/filename' format"
        owner = path_parts[0]
        filename = "/".join(path_parts[1:])

        store = MemoryStore(ctx.memory_root, ctx.agent_name)
        store.write(owner, filename, tool_input["content"])
        return f"Memory written to {tool_input['path']}"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"Error writing memory: {e}"


def _send_telegram(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.notify_fn(tool_input["message"]):
        return "Message sent to Jord via Telegram."
    return "Failed to send Telegram message."


def _check_budget(tool_input: dict, ctx: ToolContext) -> str:
    spent = load_today_spend(ctx.costs_dir)
    remaining = max(0.0, ctx.budget_limit - spent)
    return (
        f"Today's spend: ${spent:.4f} / ${ctx.budget_limit:.2f} limit. "
        f"Remaining: ${remaining:.4f}"
    )


def _list_issues(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issues = ctx.repo.get_issues(state="open")
        lines = ["# Open Issues"]
        for issue in issues:
            if issue.pull_request is None:
                labels = ", ".join(l.name for l in issue.labels)
                label_str = f" [{labels}]" if labels else ""
                lines.append(f"  - #{issue.number}: {issue.title}{label_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing issues: {e}"


def _list_prs(tool_input: dict, ctx: ToolContext) -> str:
    try:
        prs = ctx.repo.get_pulls(state="open")
        lines = [f"# Open PRs ({prs.totalCount})"]
        for pr in prs:
            lines.append(f"  - PR #{pr.number}: {pr.title}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing PRs: {e}"


def _read_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        files = pr.get_files()
        comments = pr.get_issue_comments()

        lines = [f"# PR #{pr.number}: {pr.title}", "", pr.body or "", ""]
        lines.append("## Changed Files")
        for f in files:
            lines.append(f"### {f.filename}")
            if f.patch:
                if len(f.patch) > 10000:
                    lines.append(f"{f.patch[:10000]}\n\n--- truncated ---")
                else:
                    lines.append(f.patch)
            lines.append("")

        if comments.totalCount > 0:
            lines.append("## Comments")
            for c in comments:
                lines.append(f"**{c.user.login}**: {c.body}\n")

        # CI checks
        try:
            commit = ctx.repo.get_commit(pr.head.sha)
            checks = commit.get_check_runs()
            if checks.totalCount > 0:
                lines.append("## CI Checks")
                for check in checks:
                    lines.append(f"  - {check.name}: {check.conclusion}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return f"Error reading PR: {e}"


def _post_comment(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        comment = pr.create_issue_comment(tool_input["body"])
        return f"Comment posted: {comment.html_url}"
    except Exception as e:
        return f"Error posting comment: {e}"


def _approve_pr(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.agent_role != "critic":
        return "Error: only the critic role can approve PRs."
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        pr.create_review(body=tool_input["comment"], event="APPROVE")
        return f"PR #{pr.number} approved."
    except Exception as e:
        return f"Error approving PR: {e}"


def _list_files(tool_input: dict, ctx: ToolContext) -> str:
    try:
        path = tool_input.get("path", ".")
        items = ctx.repo.get_contents(path, ref="main")
        if not isinstance(items, list):
            items = [items]
        lines = [f"# Contents of '{path}'"]
        for item in items:
            lines.append(f"  {item.name}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files: {e}"


def _merge_pr(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.agent_role != "critic":
        return "Error: only the critic role can merge PRs."
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        pr.merge(merge_method="squash")
        return f"PR #{pr.number} merged."
    except Exception as e:
        return f"Error merging PR: {e}"


def _close_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issue = ctx.repo.get_issue(tool_input["issue_number"])
        if tool_input.get("comment"):
            issue.create_comment(tool_input["comment"])
        issue.edit(state="closed")
        return f"Issue #{issue.number} closed."
    except Exception as e:
        return f"Error closing issue: {e}"


def _close_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        if tool_input.get("comment"):
            pr.create_issue_comment(tool_input["comment"])
        pr.edit(state="closed")
        return f"PR #{pr.number} closed."
    except Exception as e:
        return f"Error closing PR: {e}"


def _push_to_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        branch = pr.head.ref
        for file in tool_input["files"]:
            try:
                contents = ctx.repo.get_contents(file["path"], ref=branch)
                ctx.repo.update_file(
                    path=file["path"],
                    message=f"Update {file['path']}",
                    content=file["content"],
                    sha=contents.sha,
                    branch=branch,
                )
            except Exception:
                ctx.repo.create_file(
                    path=file["path"],
                    message=f"Create {file['path']}",
                    content=file["content"],
                    branch=branch,
                )
        return f"Pushed to PR #{pr.number} branch {branch}"
    except Exception as e:
        return f"Error pushing to PR: {e}"


def _update_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issue = ctx.repo.get_issue(tool_input["issue_number"])
        kwargs = {}
        if "title" in tool_input:
            kwargs["title"] = tool_input["title"]
        if "body" in tool_input:
            kwargs["body"] = tool_input["body"]
        if "state" in tool_input:
            kwargs["state"] = tool_input["state"]
        if "labels" in tool_input:
            kwargs["labels"] = tool_input["labels"]
        issue.edit(**kwargs)
        return f"Issue #{issue.number} updated."
    except Exception as e:
        return f"Error updating issue: {e}"


def _post_issue_comment(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issue = ctx.repo.get_issue(tool_input["issue_number"])
        comment = issue.create_comment(tool_input["body"])
        return f"Comment posted: {comment.html_url}"
    except Exception as e:
        return f"Error posting comment: {e}"


_HANDLERS = {
    "read_file": _read_file,
    "create_issue": _create_issue,
    "create_pr": _create_pr,
    "read_memory": _read_memory,
    "write_memory": _write_memory,
    "send_telegram": _send_telegram,
    "check_budget": _check_budget,
    "list_issues": _list_issues,
    "list_prs": _list_prs,
    "read_pr": _read_pr,
    "post_comment": _post_comment,
    "approve_pr": _approve_pr,
    "list_files": _list_files,
    "merge_pr": _merge_pr,
    "close_issue": _close_issue,
    "close_pr": _close_pr,
    "push_to_pr": _push_to_pr,
    "update_issue": _update_issue,
    "post_issue_comment": _post_issue_comment,
}
