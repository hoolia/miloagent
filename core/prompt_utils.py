"""Helpers for validating str.format prompt templates (no heavy deps)."""

import string
from typing import Set


def extract_placeholders(text: str) -> Set[str]:
    """Return the set of {named} placeholders in a str.format template.

    Raises ValueError on malformed braces or positional {} placeholders.
    """
    names = set()
    for _literal, field, _spec, _conv in string.Formatter().parse(text):
        if field is None:
            continue
        if field == "":
            raise ValueError("positional {} placeholders are not allowed")
        names.add(field.split(".")[0].split("[")[0])
    return names


def placeholders_subset(override: str, default: str) -> bool:
    """True if override's placeholders are a subset of the default template's."""
    try:
        return extract_placeholders(override) <= extract_placeholders(default)
    except (ValueError, IndexError):
        return False
