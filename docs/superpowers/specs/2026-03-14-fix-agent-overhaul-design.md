# Fix Agent Overhaul — Design Spec

**Date:** 2026-03-14
**Status:** Approved

## Problem

The current `fix_agent.py` regenerates the **entire patched file** in a single LLM call. This causes two compounding failure modes:

1. **Unsolicited changes** — the model correctly applies the reviewer's fixes but also modifies adjacent code (renamed variables, removed dict keys, stripped comments), introducing regressions that the review cycle must then catch.
2. **Weak model** — the `fix` task in the cheap profile uses `gemini-3.1-flash-lite-preview`, the lowest-capability model in the roster, despite fix being at least as cognitively demanding as `implement`.

Real example from PR #47 (LiteLLM migration):
- Reviewer flagged 3 real issues with precise suggested fixes
- Fixer applied all 3 correctly, but also renamed `model_name` to `_`, removed bare pricing keys, and changed an unrelated warning message
- Second fix cycle introduced more regressions trying to fix the first

## Solution

Three targeted changes: a re-review trigger, a model upgrade, and a patch-based fix approach.

---

## Change 1 — Re-review Trigger (`review_agent.yml`)

Add a `push` trigger filtered to `foreman/**` branches. Currently the review agent only triggers on `pull_request` events (`opened`, `synchronize`). When the fix agent pushes a commit to a fix branch, no re-review fires automatically — a human must trigger it manually.

```yaml
on:
  push:
    branches:
      - 'foreman/**'
  pull_request:
    types: [opened, synchronize]
  workflow_dispatch:
```

No code changes required. Pure YAML.

---

## Change 2 — Model Bump (`llm_client.py`)

In `ROUTING_PROFILES["cheap"]`, change `fix` from `gemini/gemini-3.1-flash-lite-preview` to `gemini/gemini-3-flash-preview`.

| Task | Before | After |
|------|--------|-------|
| fix  | gemini-3.1-flash-lite-preview ($0.075/M) | gemini-3-flash-preview ($0.15/M) |

This matches the model used for `implement` and `brainstorm`. Cost increase is negligible — fix outputs are short JSON patches, not full files.

---

## Change 3 — Patch-Based Fix Agent (`fix_agent.py`)

### New LLM Prompt

Replace `FIX_SYSTEM` with `PATCH_SYSTEM`. The model outputs **only** a JSON array — no prose, no markdown fences:

```
You are FOREMAN's code patcher. You receive a file and review issues with suggested fixes.

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
- Do NOT add operations for things not mentioned in the review.
- Do NOT "clean up" or "improve" anything beyond the review scope.
- If a suggested fix is provided verbatim in the review, use it exactly.
```

### New Helper Functions

**`parse_json(text) -> list | None`**
Strips markdown fences (` ```json ` / ` ``` `), attempts `json.loads()`. Returns parsed list or `None` on failure.

**`apply_patches(content, patches) -> (str, list[str])`**
Iterates patches. For each:
- Count occurrences of `search` in `content`
- If 0: append error `"Patch N: search string not found"`
- If >1: append error `"Patch N: search string matches N locations (must be unique)"`
- If exactly 1: `content = content.replace(search, replace, 1)`

Returns `(patched_content, errors)`.

**`check_scope(original, patched, review_body) -> list[str]`**
Uses `difflib.unified_diff` to identify changed line numbers in the patched file. Extracts line ranges from the review body (pattern: `file.py:10-20`). Returns a list of warnings for lines changed outside referenced ranges. Scope violations are **warnings only** — they are logged but do not block the commit. The search/replace approach already constrains scope significantly; the check provides observability.

### Per-File Validation Loop

```
for attempt in range(2):
    call LLM with PATCH_SYSTEM
    patches = parse_json(response)
    if not patches:
        append "output valid JSON" to prompt; continue

    patched, errors = apply_patches(content, patches)
    if errors:
        append errors to prompt; continue

    warnings = check_scope(content, patched, review_body)
    if warnings:
        log warnings (do not retry, do not block)

    if filepath.endswith(".py"):
        try ast.parse(patched)
        except SyntaxError:
            append syntax error to prompt; continue

    # all checks passed
    return patched

# both attempts failed
log error; return None  # file skipped, others continue
```

If a file is skipped (both attempts exhausted), the fix agent continues to other files and posts a PR comment noting the skip. Cycle counting and escalation logic remain unchanged.

---

## What Does Not Change

- `review_agent.py` — unchanged
- `implement_agent.py` — unchanged (full file output is correct for new code)
- `llm_client.py` routing logic — only the one model string changes
- `fix_agent.yml` workflow — unchanged
- Label management (`fixing`, `reviewed`, `needs-human`)
- Cycle counting and human escalation
- Telegram notifications
- Cost ceilings

---

## File Changeset

| File | Change |
|------|--------|
| `.github/workflows/review_agent.yml` | Add `push` trigger on `foreman/**` |
| `llm_client.py` | Bump cheap `fix` model to `gemini-3-flash-preview` |
| `fix_agent.py` | Replace prompt + add `parse_json`, `apply_patches`, `check_scope` + validation loop |

---

## Estimated Complexity

- T-shirt size: S
- ~90 lines new, ~40 lines removed in `fix_agent.py`
- 1-line change in `llm_client.py`
- 3-line change in `review_agent.yml`
- Main risk: LLM wrapping JSON in markdown fences (handled by `parse_json`)
