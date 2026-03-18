"""Tests for brain.hygiene."""

from brain.hygiene import is_clean_string

def test_is_clean_string_valid():
    """Test with valid string."""
    assert is_clean_string("Line 1\nLine 2") is True

def test_is_clean_string_invalid():
    """Test with trailing whitespace."""
    assert is_clean_string("Line 1 \nLine 2") is False
