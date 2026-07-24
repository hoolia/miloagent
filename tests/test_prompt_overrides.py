import json

from core.database import Database


def _db(tmp_path):
    return Database(db_path=str(tmp_path / "t.db"))


def test_prompt_override_roundtrip(tmp_path):
    db = _db(tmp_path)
    assert db.get_evolved_prompt("P", "reddit_comment") is None
    db.set_prompt_override("P", "reddit_comment", "custom text")
    assert db.get_evolved_prompt("P", "reddit_comment") == "custom text"
    # set replaces (delete-then-insert), does not accumulate
    db.set_prompt_override("P", "reddit_comment", "newer text")
    assert db.get_evolved_prompt("P", "reddit_comment") == "newer text"
    db.revert_prompt_evolution("P", "reddit_comment")
    assert db.get_evolved_prompt("P", "reddit_comment") is None


def test_prompt_override_scoped_per_project(tmp_path):
    db = _db(tmp_path)
    db.set_prompt_override("A", "reddit_comment", "for-A")
    assert db.get_evolved_prompt("A", "reddit_comment") == "for-A"
    assert db.get_evolved_prompt("B", "reddit_comment") is None


def test_persona_override_roundtrip(tmp_path):
    db = _db(tmp_path)
    assert db.get_persona_override("P", "dev_tech") is None
    db.set_persona_override("P", "dev_tech", json.dumps({"description": "custom"}))
    assert json.loads(db.get_persona_override("P", "dev_tech")) == {"description": "custom"}
    db.set_persona_override("P", "dev_tech", json.dumps({"description": "v2"}))
    assert json.loads(db.get_persona_override("P", "dev_tech")) == {"description": "v2"}
    db.revert_persona_override("P", "dev_tech")
    assert db.get_persona_override("P", "dev_tech") is None
