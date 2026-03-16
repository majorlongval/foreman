"""Seed toolset — minimal tools the brain ships with on day one.

Tools: read_file, create_issue, create_pr, read_memory, write_memory,
send_telegram, check_budget, list_issues, list_prs.

Reuses existing brain_tools.py for GitHub operations.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from brain.memory import MemoryStore
from brain.cost_tracking import load_today_spend

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
        "description": "Read a memory file. Use 'agent_name/file.md' for own memory or 'shared/subdir/file.md' for shared.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Memory path (e.g., 'gandalf/notes.md' or 'shared/costs/2026-03-15.md')."},
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
            ctx.repo.create_file(
                path=file_data["path"],
                message=f"Add {file_data['path']}",
                content=file_data["content"],
                branch=branch,
            )

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
            labels = ", ".join(l.name for l in i.labels)
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
}
