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

**Loop bounding:** The `push` trigger creates a tight automated loop (fix → push → review → fix → ...). This is intentional and already bounded by two existing mechanisms:

1. `MAX_FIX_CYCLES` (set to `"5"` in `review_agent.yml`; Python default in `review_agent.py` is `"2"`) — `review_agent.py` counts FOREMAN review posts on the PR. After reaching the limit it adds `needs-human` and stops posting new reviews, which prevents the fix agent from triggering again.
2. `_already_reviewed_head()` — `review_agent.py` checks whether the current PR HEAD sha has already been reviewed. If the fix agent pushes no changes (e.g. all patches failed), the same sha won't be re-reviewed.

**`fixing` label timing:** `fix_agent.py` currently holds the `fixing` label throughout processing and removes it in the `finally` block *after* pushing. This creates a race: the push event fires `review_agent.yml` while `fixing` is still present, causing `get_review_queue()` to skip the PR — the re-review silently drops. To close the loop, the fix agent must **remove the `fixing` label immediately before pushing** (not in `finally`). This changes the label removal order in `fix_agent.py`: process all files → remove `fixing` → push → `[push event fires, fixing is gone]` → review agent picks up the PR. There is a brief window between removing `fixing` and pushing where a concurrent fix run could start, but this is bounded by `MAX_FIX_CYCLES` and is not a practical concern.

**Note:** `foreman/**` branches are also used by the implement agent for initial code generation — the push trigger will fire on those commits too. `_already_reviewed_head()` prevents double-reviews in that case.

---

## Change 2 — Model Bump (`llm_client.py`)

In `ROUTING_PROFILES["cheap"]` only, change `fix` from `gemini/gemini-3.1-flash-lite-preview` to `gemini/gemini-3-flash-preview`. The `balanced` and `quality` profiles already use Anthropic Sonnet for `fix` and are unchanged.

| Task | Before | After |
|------|--------|-------|
| fix (cheap) | gemini-3.1-flash-lite-preview ($0.075/M) | gemini-3-flash-preview ($0.15/M) |

This matches the model already used for `implement` and `brainstorm` in the cheap profile. Cost increase is negligible — fix outputs are short JSON patches, not full files.

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
Iterates patches using `enumerate(patches, 1)` (1-indexed for human-readable error messages). For each patch N:
- Count occurrences of `search` in `content`
- If 0: append error `"Patch 1: search string not found in file"`
- If >1: append error `"Patch 1: search string matches 3 locations (must be unique)"`
- If exactly 1: `content = content.replace(search, replace, 1)`

Returns `(patched_content, errors)`. Errors are fed back verbatim into the retry prompt.

**`check_scope(original, patched, review_body) -> list[str]`**
Uses `difflib.unified_diff` to identify which line numbers changed in `patched` vs `original`. Extracts line ranges from `review_body` using the pattern `filename:N-M` (same regex already used by `_parse_affected_files` in the existing fix agent). Returns warnings for changed lines that fall outside all referenced ranges.

Scope violations are **warnings only** — logged to stdout, never retried, never blocking. The search/replace approach already prevents out-of-scope changes structurally; this check provides observability for debugging. Expected noise: the review format does not guarantee a line range for every issue, so some spurious warnings are normal. The signal value is detecting *large* out-of-scope diffs, not precise line-level validation.

### Per-File Validation Loop

Maximum **2 LLM calls per file**. Each call may fail at a different stage; there is no per-stage retry budget — each attempt burns one of the two calls regardless of failure mode.

```
for attempt in range(2):
    call LLM with PATCH_SYSTEM
    patches = parse_json(response)
    if not patches:
        append "Your previous response was not valid JSON. Output ONLY a JSON array." to prompt
        continue

    patched, errors = apply_patches(content, patches)
    if errors:
        append errors to prompt
        continue

    warnings = check_scope(content, patched, review_body)
    if warnings:
        log warnings (do not retry, do not block)

    if filepath.endswith(".py"):
        try ast.parse(patched)
        except SyntaxError as e:
            append f"Patched file has syntax error: {e}. Fix it." to prompt
            continue

    # all checks passed
    return patched

# both attempts exhausted
log error; return None  # file skipped, others continue
```

If a file is skipped (both attempts exhausted), the fix agent continues to other files in the PR and posts a PR comment noting the skip. Cycle counting and escalation logic remain unchanged.

---

## What Does Not Change

- `review_agent.py` — unchanged
- `implement_agent.py` — unchanged (full file output is correct for new code)
- `llm_client.py` routing logic — only the one model string in the cheap profile changes
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
