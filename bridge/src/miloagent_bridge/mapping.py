"""Map MiloAgent rows to findings, actions and signal records (README "GET /signals")."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

EXCERPT_MAX = 1000
CONTENT_MAX = 2000
# Metadata keys MiloAgent may carry the post author under (core/orchestrator.py)
_AUTHOR_KEYS = ("author", "author_name", "user")
_BODY_KEYS = ("body", "text")
_IGNORED_AUTHORS = ("", "[deleted]", "AutoModerator")


def _from_epoch(value: float) -> datetime | None:
    try:
        return datetime.fromtimestamp(float(value), UTC)
    except (ValueError, OverflowError, OSError):
        return None


def parse_time(value: Any) -> datetime | None:
    """A MiloAgent timestamp (SQLite datetime('now'), UTC) or ISO 8601 as aware UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return _from_epoch(value)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            return _from_epoch(float(text))
        except ValueError:
            return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def _author(meta: dict[str, Any]) -> str:
    for key in _AUTHOR_KEYS:
        value = str(meta.get(key) or "").strip()
        if value.startswith("u/"):
            value = value[2:]
        if value not in _IGNORED_AUTHORS:
            return value
    return ""


def _body(meta: dict[str, Any]) -> str:
    for key in _BODY_KEYS:
        if meta.get(key):
            return str(meta[key])
    return ""


def canonical_url(row: dict[str, Any]) -> str:
    """Stable Reddit post URL: MiloAgent's stored URL carries a truncated slug."""
    sub = row.get("subreddit_or_query") or ""
    target = row.get("target_id") or ""
    if row.get("platform") == "reddit" and sub and target and sub.isascii() and " " not in sub:
        return f"https://www.reddit.com/r/{sub}/comments/{target}/"
    return row.get("url") or ""


def finding(row: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
    meta = row.get("metadata") or {}
    out: dict[str, Any] = {
        "id": row.get("id"),
        "platform": row.get("platform"),
        "project": row.get("project"),
        "subreddit": row.get("subreddit_or_query"),
        "title": row.get("title") or "",
        "url": canonical_url(row),
        "author": _author(meta),
        "score": row.get("score"),
        "status": row.get("status"),
        "found_at": iso(parse_time(row.get("timestamp"))),
        "posted_at": iso(parse_time(meta.get("created_utc"))),
        "keyword": meta.get("keyword") or None,
        "post_score": meta.get("post_score"),
        "num_comments": meta.get("num_comments"),
    }
    if full:
        out["text"] = _body(meta)
        out["draft_response"] = row.get("draft_response")
        out["rejection_reason"] = row.get("rejection_reason")
        out["target_id"] = row.get("target_id")
    return out


def action(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("metadata") or {}
    return {
        "id": row.get("id"),
        "timestamp": iso(parse_time(row.get("timestamp"))),
        "platform": row.get("platform"),
        "action_type": row.get("action_type"),
        # our own Reddit account that acted, not the author of the post
        "account": row.get("account"),
        "project": row.get("project"),
        "target_id": row.get("target_id"),
        "subreddit": meta.get("subreddit"),
        "url": meta.get("comment_url") or meta.get("post_url"),
        "promotional": meta.get("promotional"),
        "success": bool(row.get("success")) if row.get("success") is not None else None,
        "error_message": row.get("error_message"),
        "content": (row.get("content") or "")[:CONTENT_MAX],
    }


def signal(row: dict[str, Any]) -> dict[str, Any] | None:
    """A signal record for a Reddit finding; None for other platforms.

    The keys author, title, text and created_at repeat the record under the names
    that scouts reading findings expect.
    """
    if row.get("platform") != "reddit":
        return None
    meta = row.get("metadata") or {}
    url = canonical_url(row)
    if not url:
        return None
    author = _author(meta)
    title = row.get("title") or ""
    body = _body(meta)
    observed = parse_time(meta.get("created_utc")) or parse_time(row.get("timestamp"))
    rule_id = f"{row.get('project') or 'unknown'}/r/{row.get('subreddit_or_query') or 'unknown'}"
    return {
        "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"reddit|{url}|{author}")),
        "source": "reddit",
        "url": url,
        "actor_key": author,
        "actor_person": author or None,
        "actor_company": None,
        "signal_type": "stated_need",
        "excerpt": f"{title}\n{body}".strip()[:EXCERPT_MAX],
        "observed_at": iso(observed),
        "rule_id": rule_id,
        "author": author,
        "title": title,
        "text": body[:EXCERPT_MAX],
        "created_at": iso(observed),
        "miloagent": {"id": row.get("id"), "status": row.get("status"), "score": row.get("score")},
    }
