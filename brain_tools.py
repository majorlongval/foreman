"""
FOREMAN Brain Tools — GitHub tool schemas and implementations for the Brain.

Defines TOOL_SCHEMAS (Claude API format) and implementation functions that
operate on a PyGithub repo object.  Called from the Brain's Telegram handler
via run_in_executor.
"""

import logging

log = logging.getLogger("foreman.brain.tools")

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
            "Create a new GitHub issue. Defaults to the 'needs-refinement' label "
            "if no labels are specified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "The issue title.",
                },
                "body": {
                    "type": "string",
                    "description": "The issue body (Markdown).",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Labels to apply. Defaults to ['needs-refinement'] if omitted.",
                },
            },
            "required": ["title", "body"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read a file from the repository's main branch. Content is truncated "
            "at 10,000 characters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file relative to the repo root.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "get_repo_tree",
        "description": "List all file paths in the repository.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


# ─── Tool Implementations ────────────────────────────────────

_LABEL_ORDER = [
    "ready",
    "foreman-implementing",
    "ready-for-review",
    "auto-refined",
    "needs-refinement",
    "draft",
]


def get_project_status(repo):
    """Summarize open issues grouped by label + open PRs."""
    try:
        issues = list(repo.get_issues(state="open"))
        pulls = list(repo.get_pulls(state="open"))

        # Separate real issues from PRs (GitHub API returns PRs as issues)
        real_issues = [i for i in issues if i.pull_request is None]

        # Group issues by label
        grouped = {}
        unlabeled = []
        for issue in real_issues:
            labels = [l.name for l in issue.labels]
            if not labels:
                unlabeled.append(issue)
            else:
                for label in labels:
                    grouped.setdefault(label, []).append(issue)

        lines = ["# Project Status\n"]

        # Issues by label in defined order
        lines.append("## Open Issues by Label\n")
        seen_labels = set()
        for label in _LABEL_ORDER:
            if label in grouped:
                seen_labels.add(label)
                lines.append(f"### {label} ({len(grouped[label])})")
                for i in grouped[label]:
                    lines.append(f"  - #{i.number}: {i.title}")
                lines.append("")

        # Any remaining labels not in the defined order
        for label in sorted(grouped.keys()):
            if label not in seen_labels:
                lines.append(f"### {label} ({len(grouped[label])})")
                for i in grouped[label]:
                    lines.append(f"  - #{i.number}: {i.title}")
                lines.append("")

        if unlabeled:
            lines.append(f"### (unlabeled) ({len(unlabeled)})")
            for i in unlabeled:
                lines.append(f"  - #{i.number}: {i.title}")
            lines.append("")

        # Open PRs
        lines.append(f"## Open Pull Requests ({len(pulls)})\n")
        for pr in pulls:
            reviews = list(pr.get_reviews())
            review_state = reviews[-1].state if reviews else "NO_REVIEW"
            lines.append(f"  - PR #{pr.number}: {pr.title}  [{review_state}]")

        return "\n".join(lines)

    except Exception as e:
        log.error(f"get_project_status failed: {e}")
        return f"Error getting project status: {e}"


def _get_issue(repo, number):
    """Get full issue details + recent comments."""
    try:
        issue = repo.get_issue(number)

        labels = ", ".join(l.name for l in issue.labels)
        assignees = ", ".join(a.login for a in issue.assignees) or "(none)"

        lines = [
            f"# Issue #{issue.number}: {issue.title}\n",
            f"State: {issue.state}",
            f"Labels: {labels or '(none)'}",
            f"Assignees: {assignees}",
            f"Created: {issue.created_at}",
            f"Updated: {issue.updated_at}",
            f"\n## Body\n\n{issue.body or '(empty)'}",
        ]

        # Last 5 comments
        comments = list(issue.get_comments())
        recent = comments[-5:] if len(comments) > 5 else comments
        if recent:
            lines.append(f"\n## Recent Comments ({len(recent)} of {len(comments)})\n")
            for c in recent:
                body = c.body[:500] + "..." if len(c.body) > 500 else c.body
                lines.append(f"**{c.user.login}** ({c.created_at}):\n{body}\n")

        return "\n".join(lines)

    except Exception as e:
        log.error(f"get_issue failed: {e}")
        return f"Error getting issue #{number}: {e}"


def _get_pr(repo, number):
    """Get PR details, changed files, reviews, inline comments."""
    try:
        pr = repo.get_pull(number)

        labels = ", ".join(l.name for l in pr.labels)

        lines = [
            f"# PR #{pr.number}: {pr.title}\n",
            f"State: {pr.state}",
            f"Mergeable: {pr.mergeable}",
            f"Base: {pr.base.ref} <- Head: {pr.head.ref}",
            f"Labels: {labels or '(none)'}",
            f"Created: {pr.created_at}",
            f"Updated: {pr.updated_at}",
            f"\n## Body\n\n{pr.body or '(empty)'}",
        ]

        # Changed files
        files = list(pr.get_files())
        lines.append(f"\n## Changed Files ({len(files)})\n")
        for f in files:
            lines.append(f"  - {f.filename} (+{f.additions}/-{f.deletions})")

        # Reviews
        reviews = list(pr.get_reviews())
        if reviews:
            lines.append(f"\n## Reviews ({len(reviews)})\n")
            for r in reviews:
                lines.append(f"  - {r.user.login}: {r.state}")
                if r.body:
                    body = r.body[:300] + "..." if len(r.body) > 300 else r.body
                    lines.append(f"    {body}")

        # Inline review comments (last 10)
        review_comments = list(pr.get_review_comments())
        recent_rc = review_comments[-10:] if len(review_comments) > 10 else review_comments
        if recent_rc:
            lines.append(f"\n## Inline Review Comments ({len(recent_rc)} of {len(review_comments)})\n")
            for rc in recent_rc:
                body = rc.body[:300] + "..." if len(rc.body) > 300 else rc.body
                lines.append(f"  - {rc.user.login} on `{rc.path}` (line {rc.position}):")
                lines.append(f"    {body}\n")

        return "\n".join(lines)

    except Exception as e:
        log.error(f"get_pr failed: {e}")
        return f"Error getting PR #{number}: {e}"


def _label_issue(repo, number, label):
    """Add a label to an issue."""
    try:
        issue = repo.get_issue(number)
        issue.add_to_labels(label)
        log.info(f"Added label '{label}' to #{number}")
        return f"Added label '{label}' to #{number}."

    except Exception as e:
        log.error(f"label_issue failed: {e}")
        return f"Error adding label '{label}' to #{number}: {e}"


def _merge_pr(repo, number):
    """Merge a PR after checking mergeable status."""
    try:
        pr = repo.get_pull(number)

        if pr.state != "open":
            return f"Cannot merge PR #{number}: state is '{pr.state}', not 'open'."

        if not pr.mergeable:
            return (
                f"Cannot merge PR #{number}: not mergeable. "
                f"Mergeable state: {pr.mergeable_state}"
            )

        result = pr.merge()
        log.info(f"Merged PR #{number}: {result.sha}")
        return f"Merged PR #{number} (sha: {result.sha})."

    except Exception as e:
        log.error(f"merge_pr failed: {e}")
        return f"Error merging PR #{number}: {e}"


def _create_issue(repo, title, body, labels=None):
    """Create a new issue with optional labels."""
    try:
        if labels is None:
            labels = ["needs-refinement"]

        # Resolve label objects, skip any that don't exist
        label_objects = []
        for name in labels:
            try:
                label_objects.append(repo.get_label(name))
            except Exception:
                log.warning(f"Label '{name}' not found, skipping")

        issue = repo.create_issue(title=title, body=body, labels=label_objects)
        applied = ", ".join(l.name for l in issue.labels)
        log.info(f"Created issue #{issue.number}: {title}")
        return f"Created issue #{issue.number}: {title}\nLabels: {applied or '(none)'}"

    except Exception as e:
        log.error(f"create_issue failed: {e}")
        return f"Error creating issue: {e}"


def _read_file(repo, path):
    """Read a file from the repo's main branch, truncate at 10K chars."""
    try:
        content = repo.get_contents(path, ref="main")
        text = content.decoded_content.decode("utf-8")

        if len(text) > 10000:
            return (
                f"{text[:10000]}\n\n--- truncated ({len(text)} total characters) ---"
            )
        return text

    except Exception as e:
        log.error(f"read_file failed: {e}")
        return f"Error reading '{path}': {e}"


def _get_repo_tree(repo):
    """List all file paths in the repo."""
    try:
        tree = repo.get_git_tree("main", recursive=True)
        paths = sorted(item.path for item in tree.tree if item.type == "blob")
        return "\n".join(paths)

    except Exception as e:
        log.error(f"get_repo_tree failed: {e}")
        return f"Error getting repo tree: {e}"


# ─── Dispatcher ──────────────────────────────────────────────

_TOOL_FUNCTIONS = {
    "get_project_status": lambda repo, tool_input: get_project_status(repo),
    "get_issue": lambda repo, tool_input: _get_issue(repo, tool_input["number"]),
    "get_pr": lambda repo, tool_input: _get_pr(repo, tool_input["number"]),
    "label_issue": lambda repo, tool_input: _label_issue(repo, tool_input["number"], tool_input["label"]),
    "merge_pr": lambda repo, tool_input: _merge_pr(repo, tool_input["number"]),
    "create_issue": lambda repo, tool_input: _create_issue(
        repo, tool_input["title"], tool_input["body"], tool_input.get("labels"),
    ),
    "read_file": lambda repo, tool_input: _read_file(repo, tool_input["path"]),
    "get_repo_tree": lambda repo, tool_input: _get_repo_tree(repo),
}


def execute_tool(name, tool_input, repo):
    """Dispatch a tool call by name. Returns a string result."""
    func = _TOOL_FUNCTIONS.get(name)
    if func is None:
        log.warning(f"Unknown tool: {name}")
        return f"Error: unknown tool '{name}'"
    log.info(f"Executing tool: {name} with input: {tool_input}")
    return func(repo, tool_input)
