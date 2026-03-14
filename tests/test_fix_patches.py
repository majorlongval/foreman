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
