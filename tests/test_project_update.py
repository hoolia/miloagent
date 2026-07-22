import pytest
import yaml

from core.business_manager import BusinessManager, _deep_merge


def _mgr(tmp_path, doc):
    (tmp_path / "p.yaml").write_text(yaml.dump(doc, sort_keys=False))
    return BusinessManager(projects_dir=str(tmp_path))


def _base():
    return {
        "project": {
            "name": "P",
            "description": "old",
            "weight": 1.0,
            "keep_me": "X",
        },
        "reddit": {"keywords": ["a", "b"], "min_post_score": 3},
        "custom_unknown": {"deep": 1},
    }


def test_deep_merge_dicts_merge_lists_and_scalars_replace():
    base = {"d": {"x": 1, "y": 2}, "lst": [1, 2], "s": "old"}
    _deep_merge(base, {"d": {"y": 9, "z": 3}, "lst": [7], "s": "new"})
    assert base == {"d": {"x": 1, "y": 9, "z": 3}, "lst": [7], "s": "new"}


def test_update_preserves_untouched_and_unknown_keys(tmp_path):
    mgr = _mgr(tmp_path, _base())
    mgr.update_project("P", {"project": {"description": "new"}, "reddit": {"keywords": ["c"]}})
    data = yaml.safe_load((tmp_path / "p.yaml").read_text())
    # edited fields changed
    assert data["project"]["description"] == "new"
    assert data["reddit"]["keywords"] == ["c"]          # list replaced, not merged
    # untouched fields preserved
    assert data["project"]["weight"] == 1.0
    assert data["project"]["keep_me"] == "X"
    assert data["project"]["name"] == "P"
    assert data["reddit"]["min_post_score"] == 3
    # unknown top-level key preserved
    assert data["custom_unknown"] == {"deep": 1}


def test_update_adds_new_nested_field(tmp_path):
    mgr = _mgr(tmp_path, _base())
    mgr.update_project("P", {"reddit": {"relevance_terms": ["openshift", "k8s"]}})
    data = yaml.safe_load((tmp_path / "p.yaml").read_text())
    assert data["reddit"]["relevance_terms"] == ["openshift", "k8s"]
    assert data["reddit"]["keywords"] == ["a", "b"]     # sibling untouched


def test_update_rejects_empty_name(tmp_path):
    mgr = _mgr(tmp_path, _base())
    with pytest.raises(ValueError):
        mgr.update_project("P", {"project": {"name": ""}})


def test_update_missing_project_returns_none(tmp_path):
    mgr = _mgr(tmp_path, _base())
    assert mgr.update_project("does-not-exist", {"project": {"weight": 2.0}}) is None
