"""Module for repository hygiene checks."""

def is_clean_string(text: str) -> bool:
    """Checks if a string has no trailing whitespace on lines."""
    lines = text.splitlines()
    return all(line == line.rstrip() for line in lines)
