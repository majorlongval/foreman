"""Seed toolset — minimal tools the brain ships with on day one.

Tools: read_file, create_issue, create_pr, push_to_pr, read_memory, write_memory,
send_telegram, check_budget, list_issues, list_prs, list_files,
merge_pr, close_issue, close_pr.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from github import GithubException

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
        "description": "Read a memory file. Use 'agent_name/file.md' for own memory or 'shared/subdir/file.md' for shared.",  # noqa: E501
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Memory path (e.g., 'gandalf/notes.md' or 'shared/costs/2026-03-15.md')."},  # noqa: E501
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
        "description": "Read a pull request: title, body, changed files, diff, and existing comments.",
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
        "description": "List files and directories in a repo path. Use this to explore the repo before proposing changes.",  # noqa: E501
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path relative to repo root. Defaults to root."},
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
        if len(text) > 10000:
            return f"{text[:10000]}\n\n--- truncated ({len(text)} total chars) ---"
        return text
    except Exception as e:
        return f"Error reading '{tool_input['path']}': {e}"


def _create_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        labels = tool_input.get("labels", [])
        label_objects = []
        for name in labels:
            try:
                label_objects.append(ctx.repo.get_label(name))
            except Exception:
                pass
        issue = ctx.repo.create_issue(
            title=tool_input["title"],
            body=tool_input["body"],
            labels=label_objects,
        )
        return f"Created issue #{issue.number}: {issue.title}"
    except Exception as e:
        return f"Error creating issue: {e}"


def _create_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        branch = tool_input["branch"]
        main_ref = ctx.repo.get_git_ref("heads/main")
        ctx.repo.create_git_ref(f"refs/heads/{branch}", main_ref.object.sha)

        for file_data in tool_input["files"]:
            _commit_file(ctx, file_data, branch)

        pr = ctx.repo.create_pull(
            title=tool_input["title"],
            body=tool_input["body"],
            head=branch,
            base="main",
        )
        return f"Created PR #{pr.number}: {pr.title}"
    except Exception as e:
        return f"Error creating PR: {e}"


def _read_memory(tool_input: dict, ctx: ToolContext) -> str:
    path = tool_input["path"]
    parts = path.split("/", 1)
    owner = parts[0]
    filename = parts[1] if len(parts) > 1 else ""
    store = MemoryStore(ctx.memory_root, ctx.agent_name)
    try:
        content = store.read(owner, filename)
        return content if content is not None else f"No file found at {path}"
    except PermissionError as e:
        return str(e)


def _write_memory(tool_input: dict, ctx: ToolContext) -> str:
    path = tool_input["path"]
    parts = path.split("/", 1)
    owner = parts[0]
    filename = parts[1] if len(parts) > 1 else ""
    store = MemoryStore(ctx.memory_root, ctx.agent_name)
    try:
        store.write(owner, filename, tool_input["content"])
        return f"Wrote to {path}"
    except PermissionError as e:
        return str(e)


def _send_telegram(tool_input: dict, ctx: ToolContext) -> str:
    success = ctx.notify_fn(tool_input["message"])
    return "Message sent." if success else "Failed to send message."


def _check_budget(tool_input: dict, ctx: ToolContext) -> str:
    spent = load_today_spend(ctx.costs_dir)
    remaining = max(0.0, ctx.budget_limit - spent)
    return f"Budget: ${remaining:.2f} remaining (${spent:.2f} spent of ${ctx.budget_limit:.2f})"


def _list_issues(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issues = list(ctx.repo.get_issues(state="open"))
        real = [i for i in issues if i.pull_request is None]
        lines = [f"# Open Issues ({len(real)})"]
        for i in real:
            labels = ", ".join(label.name for label in i.labels)
            label_str = f" [{labels}]" if labels else ""
            lines.append(f"  - #{i.number}: {i.title}{label_str}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing issues: {e}"


def _list_prs(tool_input: dict, ctx: ToolContext) -> str:
    try:
        prs = list(ctx.repo.get_pulls(state="open"))
        lines = [f"# Open PRs ({len(prs)})"]
        for pr in prs:
            lines.append(f"  - PR #{pr.number}: {pr.title}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing PRs: {e}"


_MAX_DIFF_CHARS = 8000


def _read_pr(tool_input: dict, ctx: ToolContext) -> str:
    # Returns title, body, changed files+diffs, and existing comments so
    # the critic can do a meaningful review without needing shell access.
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        parts = [
            f"# PR #{pr.number}: {pr.title}",
            "",
            pr.body or "(no description)",
            "",
            "## Changed Files",
        ]
        diff_chars = 0
        truncated = False
        for f in pr.get_files():
            parts.append(f"### {f.filename}")
            patch = f.patch or ""
            if diff_chars + len(patch) > _MAX_DIFF_CHARS:
                remaining = max(0, _MAX_DIFF_CHARS - diff_chars)
                parts.append(patch[:remaining])
                parts.append("... (truncated)")
                truncated = True
                break
            parts.append(patch)
            diff_chars += len(patch)
        if truncated:
            parts.append("\n(diff truncated — too large to show in full)")
        comments = list(pr.get_issue_comments())
        if comments:
            parts.append("\n## Comments")
            for c in comments:
                parts.append(f"**{c.user.login}:** {c.body}")
        # CI check results — Galadriel must not approve PRs with failing checks.
        # Fetch via the head commit's check runs; silently skip if unavailable.
        try:
            check_runs = list(ctx.repo.get_commit(pr.head.sha).get_check_runs())
            if check_runs:
                parts.append("\n## CI Checks")
                for run in check_runs:
                    parts.append(f"  - {run.name}: {run.conclusion or run.status}")
        except Exception:
            pass
        return "\n".join(parts)
    except Exception as e:
        return f"Error reading PR #{tool_input['pr_number']}: {e}"


def _post_comment(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        pr.create_issue_comment(tool_input["body"])
        return f"Posted comment on PR #{tool_input['pr_number']}."
    except Exception as e:
        return f"Error posting comment on PR #{tool_input['pr_number']}: {e}"


def _approve_pr(tool_input: dict, ctx: ToolContext) -> str:
    if ctx.agent_role != "critic":
        return "Only the critic role can approve PRs."
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        pr.create_review(body=tool_input["comment"], event="APPROVE")
        return f"Approved PR #{tool_input['pr_number']}."
    except Exception as e:
        return f"Error approving PR: {e}"


def _list_files(tool_input: dict, ctx: ToolContext) -> str:
    # Lets agents explore the repo directory tree before proposing changes.
    # Returns each entry with a trailing "/" for directories so callers can tell
    # at a glance what is a file and what is a folder.
    path = tool_input.get("path", "")
    try:
        contents = ctx.repo.get_contents(path)
        # get_contents returns a single object for a file, list for a dir
        if not isinstance(contents, list):
            contents = [contents]
        lines = [f"# Contents of '{path or '/'}'" ]
        for entry in contents:
            label = f"{entry.name}/" if entry.type == "dir" else entry.name
            lines.append(f"  {label}")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing files at '{path}': {e}"


def _merge_pr(tool_input: dict, ctx: ToolContext) -> str:
    # Merging is a high-trust action — only the critic (Galadriel) may do it
    # after she has already reviewed and approved the PR.
    if ctx.agent_role != "critic":
        return "Only the critic role can merge PRs."
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        pr.merge(merge_method="squash")
        return f"Merged PR #{tool_input['pr_number']}."
    except Exception as e:
        return f"Error merging PR #{tool_input['pr_number']}: {e}"


def _close_issue(tool_input: dict, ctx: ToolContext) -> str:
    try:
        issue = ctx.repo.get_issue(tool_input["issue_number"])
        comment = tool_input.get("comment", "")
        if comment:
            # Post the comment before closing so it appears in the timeline
            issue.create_comment(comment)
        issue.edit(state="closed")
        return f"Closed issue #{tool_input['issue_number']}."
    except Exception as e:
        return f"Error closing issue #{tool_input['issue_number']}: {e}"


def _close_pr(tool_input: dict, ctx: ToolContext) -> str:
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        comment = tool_input.get("comment", "")
        if comment:
            # Post the comment before closing so context is preserved
            pr.create_issue_comment(comment)
        pr.edit(state="closed")
        return f"Closed PR #{tool_input['pr_number']}."
    except Exception as e:
        return f"Error closing PR #{tool_input['pr_number']}: {e}"


def _push_to_pr(tool_input: dict, ctx: ToolContext) -> str:
    # Look up the PR to find its head branch, then commit each file there.
    # This is the right way to address review feedback — not opening a new PR.
    try:
        pr = ctx.repo.get_pull(tool_input["pr_number"])
        branch = pr.head.ref
        for file_data in tool_input["files"]:
            _commit_file(ctx, file_data, branch)
        return f"Pushed {len(tool_input['files'])} file(s) to PR #{pr.number} ({branch})."
    except Exception as e:
        return f"Error pushing to PR #{tool_input['pr_number']}: {e}"


def _commit_file(ctx: ToolContext, file_data: dict, branch: str) -> None:
    """Create or update a single file on the given branch.

    GitHub's Contents API raises a 422 if you call create_file on a path that
    already has content, so we probe with get_contents first. A GithubException
    with status 404 means the file doesn't exist yet — use create_file.
    Any other exception is re-raised so the caller can surface the error.
    """
    path = file_data["path"]
    content = file_data["content"]
    try:
        existing = ctx.repo.get_contents(path, ref=branch)
        ctx.repo.update_file(
            path=path,
            message=f"Update {path}",
            content=content,
            sha=existing.sha,
            branch=branch,
        )
    except GithubException as e:
        if e.status == 404:
            ctx.repo.create_file(
                path=path,
                message=f"Add {path}",
                content=content,
                branch=branch,
            )
        else:
            raise


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
}
