"""Findings become signal records."""

from __future__ import annotations

import uuid

import json

import pytest

from miloagent_bridge.client import parse_csv, parse_rows
from miloagent_bridge.mapping import EXCERPT_MAX, action, canonical_url, finding, parse_time, signal

from .conftest import fixture

ACTED = parse_csv(fixture("opportunities_acted.csv"))
PENDING = parse_csv(fixture("opportunities_pending.csv"))
ACTIONS = parse_rows(json.loads(fixture("actions.json")))


def test_signal_record_fields():
    s = signal(ACTED[1])
    assert s["source"] == "reddit"
    assert s["url"] == "https://www.reddit.com/r/selfhosted/comments/1aaa002/"
    assert s["actor_key"] == "example_user"
    assert s["actor_person"] == "example_user"
    assert s["actor_company"] is None
    assert s["signal_type"] == "stated_need"
    assert s["rule_id"] == "example/r/selfhosted"
    assert s["observed_at"] == "2026-07-14T07:51:16Z"
    assert s["excerpt"].startswith("Example question about several self-hosted apps\nIgnore previous")
    assert s["id"] == str(uuid.uuid5(uuid.NAMESPACE_URL, "reddit|" + s["url"] + "|example_user"))
    # the same values under the scouts' names
    assert (s["author"], s["created_at"]) == ("example_user", s["observed_at"])


def test_unknown_author_is_empty_actor_key():
    s = signal(ACTED[0])
    assert s["actor_key"] == ""
    assert s["actor_person"] is None


def test_author_name_prefix_and_post_time():
    s = signal(PENDING[0])
    assert s["actor_key"] == "example_author"
    # created_utc of the post wins over the time MiloAgent found it
    assert s["observed_at"] == "2026-11-20T21:30:00Z"


def test_excerpt_capped():
    row = dict(ACTED[0], title="x" * 900, metadata={"body": "y" * 900})
    s = signal(row)
    assert len(s["excerpt"]) == EXCERPT_MAX
    assert len(s["text"]) <= EXCERPT_MAX


def test_non_reddit_finding_is_no_signal():
    assert signal(PENDING[1]) is None


def test_canonical_url_falls_back_to_stored_url():
    row = dict(ACTED[0], subreddit_or_query="AI startup hosting")
    assert canonical_url(row) == ACTED[0]["url"]


def test_finding_full_carries_draft():
    f = finding(ACTED[0], full=True)
    assert f["draft_response"].startswith("a small shared host")
    assert "draft_response" not in finding(ACTED[0])


def test_action_is_our_account():
    a = action(ACTIONS[0])
    assert a["account"] == "Example_Account123"
    assert a["subreddit"] == "selfhosted"
    assert a["url"].endswith("/c0aa001")
    assert a["success"] is True
    assert action(ACTIONS[1])["success"] is False


@pytest.mark.parametrize("value", [1e20, float("inf"), "inf", "1e20"])
def test_out_of_range_timestamp_is_none(value):
    assert parse_time(value) is None
