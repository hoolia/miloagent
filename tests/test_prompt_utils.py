import pytest

from core.prompt_utils import extract_placeholders, placeholders_subset


def test_extract_named():
    assert extract_placeholders("Hi {a} and {b.x} and {c[0]}") == {"a", "b", "c"}


def test_extract_none():
    assert extract_placeholders("no placeholders here") == set()


def test_extract_positional_raises():
    with pytest.raises(ValueError):
        extract_placeholders("bad {} positional")


def test_extract_malformed_raises():
    with pytest.raises(ValueError):
        extract_placeholders("unbalanced {brace")


def test_subset_ok():
    assert placeholders_subset("uses {a}", "has {a} and {b}") is True


def test_subset_equal():
    assert placeholders_subset("has {a} {b}", "has {a} {b}") is True


def test_subset_unknown_placeholder():
    assert placeholders_subset("uses {z}", "has {a}") is False


def test_subset_malformed_override():
    assert placeholders_subset("bad {", "has {a}") is False
