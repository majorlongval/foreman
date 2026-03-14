# Fix Agent Overhaul Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fix agent's full-file LLM output with targeted search/replace JSON patches, add a re-review push trigger, and bump the cheap-profile fix model.

**Architecture:** Three independent changes. (1) A YAML trigger addition closes the review-fix-review gap. (2) A one-line model string change improves fix quality. (3) The core change: `fix_agent.py` gains three pure helper functions (`parse_json`, `apply_patches`, `check_scope`) and a per-file validation loop that generates and applies patches instead of overwriting whole files. The `fixing` label is removed before pushing so the push trigger can fire correctly.

**Tech Stack:** Python 3.11, pytest, difflib (stdlib), re (stdlib), ast (stdlib), json (stdlib)

**Spec:** `docs/superpowers/specs/2026-03-14-fix-agent-overhaul-design.md`

---

## Chunk 1: Config Changes

### Task 1: Add push trigger to review_agent.yml

**Files:**
- Modify: `.github/workflows/review_agent.yml:3-10` (the `on:` block)

- [ ] **Step 1: Add the push trigger**

Open `.github/workflows/review_agent.yml`. The current `on:` block is:

```yaml
on:
  pull_request:
    types: [opened, synchronize]  # Trigger on new PRs and updates
  workflow_dispatch:               # Manual trigger
```

Replace it with:

```yaml
on:
  push:
    branches:
      - 'foreman/**'              # Re-review after fix agent commits
  pull_request:
    types: [opened, synchronize]  # Trigger on new PRs and updates
  workflow_dispatch:               # Manual trigger
```

- [ ] **Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/review_agent.yml'))" && echo "OK"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/review_agent.yml
git commit -m "ci: trigger review agent on push to foreman/* branches"
```

---

### Task 2: Bump fix model in cheap profile

**Files:**
- Modify: `llm_client.py:219`

- [ ] **Step 1: Update the model string**

In `llm_client.py`, find line 219 inside `ROUTING_PROFILES["cheap"]`:

```python
        "fix": "gemini/gemini-3.1-flash-lite-preview",
```

Change it to:

```python
        "fix": "gemini/gemini-3-flash-preview",
```

- [ ] **Step 2: Verify no other cheap-profile entries changed**

```bash
grep -n "gemini-3.1-flash-lite-preview\|gemini-3-flash-preview" llm_client.py
```

Expected output (only cheap `fix` and `implement`/`brainstorm`/`refine` use `gemini-3-flash-preview`; `title_gen` and `commit_msg` still use `flash-lite`):
```
215:        "refine": "gemini/gemini-3-flash-preview",
216:        "brainstorm": "gemini/gemini-3-flash-preview",
217:        "review": "gemini/gemini-3.1-pro-preview",
218:        "review_confirm": "gemini/gemini-3.1-pro-preview",
219:        "fix": "gemini/gemini-3-flash-preview",
220:        "title_gen": "gemini/gemini-3.1-flash-lite-preview",
221:        "commit_msg": "gemini/gemini-3.1-flash-lite-preview",
222:        "implement": "gemini/gemini-3-flash-preview",
```

- [ ] **Step 3: Commit**

```bash
git add llm_client.py
git commit -m "config: bump cheap-profile fix model to gemini-3-flash-preview"
```

---

## Chunk 2: Helper Functions + Tests

### Task 3: Write failing tests for parse_json

**Files:**
- Create: `tests/test_fix_patches.py`

- [ ] **Step 0: Create the tests directory**

```bash
mkdir -p /home/jordan/code/foreman/tests
```

- [ ] **Step 1: Create the test file with failing tests for parse_json**

```python
# tests/test_fix_patches.py
"""Tests for fix_agent patch helper functions."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fix_agent import parse_json, apply_patches, check_scope


class TestParseJson:
    def test_clean_json_array(self):
        text = '[{"search": "foo", "replace": "bar", "issue": "x"}]'
        result = parse_json(text)
        assert result == [{"search": "foo", "replace": "bar", "issue": "x"}]

    def test_json_in_backtick_fence(self):
        text = '```json\n[{"search": "a", "replace": "b", "issue": "y"}]\n```'
        result = parse_json(text)
        assert result == [{"search": "a", "replace": "b", "issue": "y"}]

    def test_json_in_plain_fence(self):
        text = '```\n[{"search": "a", "replace": "b", "issue": "y"}]\n```'
        result = parse_json(text)
        assert result == [{"search": "a", "replace": "b", "issue": "y"}]

    def test_invalid_json_returns_none(self):
        assert parse_json("not json at all") is None

    def test_empty_string_returns_none(self):
        assert parse_json("") is None

    def test_json_object_not_list_returns_none(self):
        assert parse_json('{"search": "foo"}') is None

    def test_empty_array(self):
        result = parse_json("[]")
        assert result == []


class TestApplyPatches:
    def test_single_patch_applied(self):
        content = "line one\nline two\nline three\n"
        patches = [{"search": "line two", "replace": "LINE TWO", "issue": "test"}]
        result, errors = apply_patches(content, patches)
        assert result == "line one\nLINE TWO\nline three\n"
        assert errors == []

    def test_search_not_found_returns_error(self):
        content = "line one\nline two\n"
        patches = [{"search": "line missing", "replace": "x", "issue": "test"}]
        result, errors = apply_patches(content, patches)
        assert result == content  # unchanged
        assert len(errors) == 1
        assert "Patch 1" in errors[0]
        assert "not found" in errors[0]

    def test_search_multiple_matches_returns_error(self):
        content = "foo\nfoo\n"
        patches = [{"search": "foo", "replace": "bar", "issue": "test"}]
        result, errors = apply_patches(content, patches)
        assert result == content  # unchanged
        assert len(errors) == 1
        assert "Patch 1" in errors[0]
        assert "matches 2" in errors[0]

    def test_multiple_patches_all_succeed(self):
        content = "alpha\nbeta\ngamma\n"
        patches = [
            {"search": "alpha", "replace": "ALPHA", "issue": "a"},
            {"search": "gamma", "replace": "GAMMA", "issue": "b"},
        ]
        result, errors = apply_patches(content, patches)
        assert result == "ALPHA\nbeta\nGAMMA\n"
        assert errors == []

    def test_mixed_success_and_failure(self):
        content = "alpha\nbeta\n"
        patches = [
            {"search": "alpha", "replace": "ALPHA", "issue": "a"},
            {"search": "missing", "replace": "x", "issue": "b"},
        ]
        result, errors = apply_patches(content, patches)
        assert "ALPHA" in result
        assert len(errors) == 1
        assert "Patch 2" in errors[0]

    def test_empty_patches_list(self):
        content = "hello\n"
        result, errors = apply_patches(content, [])
        assert result == content
        assert errors == []

    def test_multiline_search(self):
        content = "def foo():\n    return 1\n\ndef bar():\n    return 2\n"
        patches = [{"search": "def foo():\n    return 1", "replace": "def foo():\n    return 42", "issue": "x"}]
        result, errors = apply_patches(content, patches)
        assert "return 42" in result
        assert errors == []


class TestCheckScope:
    def test_no_ranges_in_review_returns_empty(self):
        original = "line1\nline2\nline3\n"
        patched = "line1\nLINE2\nline3\n"
        review_body = "Some review with no line references"
        warnings = check_scope(original, patched, review_body)
        assert warnings == []

    def test_change_within_range_no_warning(self):
        original = "line1\nline2\nline3\n"
        patched = "line1\nLINE2\nline3\n"
        # line 2 changed, review mentions file.py:2-3
        review_body = "Fix issue in `file.py:2-3` — description"
        warnings = check_scope(original, patched, review_body)
        assert warnings == []

    def test_change_outside_range_returns_warning(self):
        original = "line1\nline2\nline3\nline4\nline5\n"
        patched = "line1\nline2\nline3\nline4\nLINE5\n"
        # line 5 changed, review only mentions lines 1-2
        review_body = "Fix issue in `file.py:1-2` — description"
        warnings = check_scope(original, patched, review_body)
        assert len(warnings) >= 1

    def test_no_changes_returns_empty(self):
        content = "line1\nline2\n"
        warnings = check_scope(content, content, "`file.py:1-5` review")
        assert warnings == []
```

- [ ] **Step 2: Run tests — they must fail with ImportError**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/test_fix_patches.py -v 2>&1 | head -20
```

Expected: `ImportError: cannot import name 'parse_json' from 'fix_agent'`

---

### Task 4: Implement parse_json

**Files:**
- Modify: `fix_agent.py` — add `parse_json` after the `FIX_SYSTEM` block (around line 70)

- [ ] **Step 1: Add parse_json as a module-level function**

In `fix_agent.py`, add `import json` to the imports at the top. Insert it after `import re` (line 16) to keep stdlib imports grouped:

```python
import json
```

Then after the `FIX_SYSTEM` string (after line 68), add:

```python
# ─── Patch Helpers ───────────────────────────────────────────

def parse_json(text: str) -> list | None:
    """Strip markdown fences and parse JSON. Returns list or None."""
    if not text or not text.strip():
        return None
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.splitlines()
        # Remove opening fence (```json or ```)
        lines = lines[1:]
        # Remove closing fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
        if not isinstance(result, list):
            return None
        return result
    except (json.JSONDecodeError, ValueError):
        return None
```

- [ ] **Step 2: Run parse_json tests only**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/test_fix_patches.py::TestParseJson -v
```

Expected: all 7 `TestParseJson` tests pass.

---

### Task 5: Implement apply_patches

**Files:**
- Modify: `fix_agent.py` — add `apply_patches` after `parse_json`

- [ ] **Step 1: Add apply_patches**

Immediately after `parse_json`, add:

```python
def apply_patches(content: str, patches: list) -> tuple[str, list[str]]:
    """Apply search/replace patches. Returns (patched_content, errors).

    Each patch must have 'search' appearing exactly once in content.
    Errors are 1-indexed human-readable strings suitable for LLM retry prompts.
    """
    errors = []
    for i, patch in enumerate(patches, 1):
        search = patch.get("search", "")
        replace = patch.get("replace", "")
        count = content.count(search)
        if count == 0:
            errors.append(f"Patch {i}: search string not found in file")
            continue
        if count > 1:
            errors.append(f"Patch {i}: search string matches {count} locations (must be unique)")
            continue
        content = content.replace(search, replace, 1)
    return content, errors
```

- [ ] **Step 2: Run apply_patches tests only**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/test_fix_patches.py::TestApplyPatches -v
```

Expected: all 7 `TestApplyPatches` tests pass.

---

### Task 6: Implement check_scope

**Files:**
- Modify: `fix_agent.py` — add `check_scope` after `apply_patches`

- [ ] **Step 1: Add check_scope**

Add `import difflib` to the imports at the top of `fix_agent.py` (after `import re`):

```python
import difflib
```

Then immediately after `apply_patches`, add:

```python
def check_scope(original: str, patched: str, review_body: str) -> list[str]:
    """Warn if patches touch lines not mentioned in the review.

    Returns a list of warning strings. Warnings are informational only —
    callers should log them but not retry or block on them.
    Expected noise: the review format doesn't guarantee line ranges for all
    issues, so some spurious warnings are normal.
    """
    # Extract mentioned line ranges from review body: `filename.py:10-20` or `filename.py:10`
    mentioned_ranges = []
    for match in re.finditer(r'`[^`]+\.\w+:(\d+)(?:-(\d+))?`', review_body):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        mentioned_ranges.append((start, end))

    if not mentioned_ranges:
        return []  # No ranges to check against

    # Find changed line numbers (1-indexed, in original numbering)
    changed_lines = set()
    orig_line = 0
    for line in difflib.unified_diff(original.splitlines(), patched.splitlines(), lineterm=""):
        if line.startswith("@@"):
            m = re.search(r"@@ -(\d+)", line)
            if m:
                orig_line = int(m.group(1)) - 1
        elif line.startswith("---") or line.startswith("+++"):
            pass  # file header lines — don't advance the line counter
        elif line.startswith("-"):
            orig_line += 1
            changed_lines.add(orig_line)
        elif not line.startswith("+"):
            orig_line += 1

    warnings = []
    for ln in sorted(changed_lines):
        if not any(start <= ln <= end for start, end in mentioned_ranges):
            warnings.append(
                f"Line {ln} changed but not within any reviewed range {mentioned_ranges}"
            )
    return warnings
```

- [ ] **Step 2: Run all patch helper tests**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/test_fix_patches.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add fix_agent.py tests/test_fix_patches.py
git commit -m "feat: add parse_json, apply_patches, check_scope helpers to fix_agent"
```

---

## Chunk 3: Fix Loop Replacement

### Task 7: Replace the prompt and the per-file fix loop

**Files:**
- Modify: `fix_agent.py`

This task replaces three things in `fix_agent.py`:
1. `FIX_SYSTEM` → `PATCH_SYSTEM`
2. The per-file fix generation block inside `fix_pr()` (lines ~214–265)
3. The `fixing` label removal — moved from `finally` to before the push

- [ ] **Step 1: Replace FIX_SYSTEM with PATCH_SYSTEM**

Find and replace the entire `FIX_SYSTEM` string (lines 55–68):

```python
FIX_SYSTEM = """You are FOREMAN's code patcher. You receive a file and a review history
containing issues with suggested fixes written by a senior reviewer.

Your ONLY job is to apply the suggested fixes exactly as specified.

Rules:
- Apply every "Suggested fix" from CRITICAL and IMPORTANT issues.
- Do NOT change anything not covered by a suggested fix.
- Do NOT refactor, rename, or "improve" anything not mentioned.
- Do NOT add features, comments, or documentation not requested.
- If a suggested fix conflicts with the current code, apply the intent of the fix.
- Output ONLY the complete patched file content. No markdown fences. No explanation.
  The raw file content starts at character 0.
"""
```

Replace with:

```python
PATCH_SYSTEM = """You are FOREMAN's code patcher. You receive a file and review issues with suggested fixes.

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
"""
```

- [ ] **Step 2: Replace the per-file fix generation block**

Inside `fix_pr()`, find the `try:` block starting at line 193. The section to replace is from "Generate fix" (line 214) through the push and the `fixes_applied.append` (line 265). The full replacement restructures the loop into two phases: (1) collect patches for all files, (2) remove `fixing` label, (3) push.

Replace the entire `try:` block (lines 193–292, from `fixes_applied = []` through `return True`) with:

```python
        fixes_applied = []
        fixes_ready = []  # (filepath, patched_content, file_sha) — collected before push

        try:
            for filepath in affected_files:
                if not self.cost.check_ceiling():
                    break

                # Get current file content from PR branch
                try:
                    contents = self.repo.get_contents(filepath, ref=branch)
                    current_content = contents.decoded_content.decode("utf-8")
                    file_sha = contents.sha
                except Exception as e:
                    log.warning(f"  Could not read {filepath} from branch {branch}: {e}")
                    continue

                # Build full review history for this file
                history_parts = []
                for i, rev in enumerate(all_reviews):
                    issues = self._extract_issues_for_file(rev, filepath)
                    history_parts.append(f"**Round {i+1}:**\n{issues}")
                review_history = "\n\n---\n".join(history_parts)

                # Generate patches — up to 2 attempts
                model = self.router.get("fix")
                log.info(f"  Generating patches for {filepath} ({len(all_reviews)} review round(s) of context)")
                prompt = (
                    f"## Review History\n\n{review_history}\n\n"
                    f"## Current File: {filepath}\n\n{current_content}"
                )

                patched = None
                for attempt in range(2):
                    response = self.llm.complete(
                        model=model,
                        system=PATCH_SYSTEM,
                        message=prompt,
                        max_tokens=None,
                    )
                    self.cost.record(model, response, agent="fixer", action="fix")

                    patches = parse_json(response.text)
                    if not patches:
                        log.warning(f"  Attempt {attempt+1}: invalid JSON response for {filepath}")
                        prompt += "\n\nYour previous response was not valid JSON. Output ONLY a JSON array."
                        continue

                    patched_content, errors = apply_patches(current_content, patches)
                    if errors:
                        log.warning(f"  Attempt {attempt+1}: patch errors for {filepath}: {errors}")
                        prompt += f"\n\nPatch application failed:\n" + "\n".join(errors) + "\nFix your search strings."
                        continue

                    warnings = check_scope(current_content, patched_content, review_body)
                    if warnings:
                        log.warning(f"  Scope warnings for {filepath}: {warnings}")

                    if filepath.endswith(".py"):
                        import ast
                        try:
                            ast.parse(patched_content)
                        except SyntaxError as e:
                            log.warning(f"  Attempt {attempt+1}: syntax error in patched {filepath}: {e}")
                            prompt += f"\n\nPatched file has syntax error: {e}. Fix it."
                            continue

                    patched = patched_content
                    break

                if patched is None:
                    log.error(f"  All patch attempts failed for {filepath} — skipping")
                    self.stats["failed"] += 1
                    continue

                if patched.strip() == current_content.strip():
                    log.info(f"  No changes needed for {filepath}")
                    continue

                fixes_ready.append((filepath, patched, file_sha))

            # Release fixing label BEFORE pushing so push-triggered review can run
            if not self.dry_run:
                try:
                    pr.remove_from_labels(self.repo.get_label(LABEL_FIXING))
                except Exception:
                    pass

            # Push all collected fixes
            for filepath, patched, file_sha in fixes_ready:
                if not self.dry_run:
                    self.repo.update_file(
                        filepath,
                        f"fix: address review comments in {filepath}",
                        patched,
                        file_sha,
                        branch=branch,
                    )
                    log.info(f"  Pushed fix for {filepath}")
                else:
                    log.info(f"  [DRY RUN] Would push fix for {filepath}")
                fixes_applied.append(filepath)

            # Post summary comment
            if fixes_applied:
                summary = "Applied fixes for:\n" + "\n".join(
                    f"- `{f}`" for f in fixes_applied
                )
                if not self.dry_run:
                    pr.create_issue_comment(summary + FIX_SIGNATURE)
                    try:
                        pr.remove_from_labels(self.repo.get_label(LABEL_REVIEWED))
                    except Exception:
                        pass
                    tg(f"🔧 Fix agent pushed fixes to PR #{pr.number}: {', '.join(fixes_applied)}\n{pr.html_url}")
                log.info(f"  Fixed {len(fixes_applied)} files")
                self.stats["fixed"] += 1
            else:
                log.info(f"  No fixes were applied")
                self.stats["skipped"] += 1

            return True

        except Exception as e:
            log.error(f"  Fix failed for PR #{pr.number}: {e}", exc_info=True)
            self.stats["failed"] += 1
            tg(f"❌ Fix agent failed on PR #{pr.number}: {e}\n{pr.html_url}")
            return False

        finally:
            # Ensure fixing label is removed even on exception
            # (normal path removes it before pushing; this is the safety net)
            if not self.dry_run:
                try:
                    pr.remove_from_labels(self.repo.get_label(LABEL_FIXING))
                except Exception:
                    pass
```

- [ ] **Step 3: Verify the file parses cleanly**

```bash
cd /home/jordan/code/foreman && python -c "import ast; ast.parse(open('fix_agent.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Run all patch helper tests to confirm nothing regressed**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/test_fix_patches.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Smoke-test the module imports**

```bash
cd /home/jordan/code/foreman && python -c "
from fix_agent import parse_json, apply_patches, check_scope, PATCH_SYSTEM, FixAgent
print('PATCH_SYSTEM defined:', bool(PATCH_SYSTEM))
print('Helpers importable: OK')
"
```

Expected:
```
PATCH_SYSTEM defined: True
Helpers importable: OK
```

- [ ] **Step 6: Commit**

```bash
git add fix_agent.py
git commit -m "feat: replace full-file fix with search/replace patch loop in fix_agent"
```

---

## Final Verification

- [ ] **Verify all three commits are present**

```bash
git log --oneline -5
```

Expected to see (most recent first):
```
<sha> feat: replace full-file fix with search/replace patch loop in fix_agent
<sha> feat: add parse_json, apply_patches, check_scope helpers to fix_agent
<sha> config: bump cheap-profile fix model to gemini-3-flash-preview
<sha> ci: trigger review agent on push to foreman/* branches
```

- [ ] **Run full test suite**

```bash
cd /home/jordan/code/foreman && python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Confirm FIX_SYSTEM no longer exists in the codebase**

```bash
grep -n "FIX_SYSTEM" fix_agent.py
```

Expected: no output.

- [ ] **Confirm PATCH_SYSTEM is in place**

```bash
grep -n "PATCH_SYSTEM" fix_agent.py | head -5
```

Expected: at least 2 lines (definition + usage in the loop).
