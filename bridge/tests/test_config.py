from __future__ import annotations

import pytest

from miloagent_bridge.config import DEFAULT_SIGNAL_STATUSES, ConfigError, Settings


def test_required():
    with pytest.raises(ConfigError, match="MILOAGENT_URL, MILOAGENT_PASSWORD"):
        Settings.from_env({})


def test_defaults():
    s = Settings.from_env({"MILOAGENT_URL": "http://miloagent:8420/", "MILOAGENT_PASSWORD": "pw"})
    assert s.url == "http://miloagent:8420"
    assert s.username == "admin"
    assert s.signal_statuses == DEFAULT_SIGNAL_STATUSES
    assert "rejected" not in s.signal_statuses


def test_signal_statuses():
    s = Settings.from_env({"MILOAGENT_URL": "http://m", "MILOAGENT_PASSWORD": "pw",
                           "MILOAGENT_SIGNAL_STATUSES": "acted, pending"})
    assert s.signal_statuses == ("acted", "pending")
    with pytest.raises(ConfigError, match="unknown"):
        Settings.from_env({"MILOAGENT_URL": "http://m", "MILOAGENT_PASSWORD": "pw",
                           "MILOAGENT_SIGNAL_STATUSES": "approved"})


def test_bad_url():
    with pytest.raises(ConfigError):
        Settings.from_env({"MILOAGENT_URL": "miloagent:8420", "MILOAGENT_PASSWORD": "pw"})
