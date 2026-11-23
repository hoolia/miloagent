"""Client for MiloAgent's dashboard API, limited to reading.

MiloAgent (FastAPI, dashboard/web.py) issues an in-memory session token from
POST /api/auth/login and forgets it on restart. The client logs in once, reuses the
token, and logs in again once on a 401. Besides the login it calls only the two CSV
export endpoints, both GET. There is no generic request method, so no path to the
approval queue, the control endpoints or settings exists here.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from typing import Any

import httpx

from .config import STATUSES, Settings

LOGIN_PATH = "/api/auth/login"
OPPORTUNITIES_PATH = "/api/export/opportunities"
ACTIONS_PATH = "/api/actions"
# GET /api/actions returns the newest actions of the last year, at most 200
MAX_ACTIONS = 200

_INT_FIELDS = ("id", "success")
_FLOAT_FIELDS = ("score",)


class MiloAgentError(RuntimeError):
    """MiloAgent refused or failed a request; the message never carries credentials."""


def parse_csv(text: str) -> list[dict[str, Any]]:
    """Rows of a MiloAgent CSV export, typed, with metadata JSON decoded."""
    return parse_rows(list(csv.DictReader(io.StringIO(text))))


def parse_rows(raws: Any) -> list[dict[str, Any]]:
    """MiloAgent rows (CSV strings or JSON values), typed, with metadata JSON decoded."""
    if not isinstance(raws, list):
        # MiloAgent answers {"error": ...} with HTTP 200 when its query fails
        raise MiloAgentError(f"MiloAgent returned no rows: {str(raws)[:200]}")
    rows: list[dict[str, Any]] = []
    for raw in raws:
        if not isinstance(raw, dict):
            continue
        row: dict[str, Any] = {k: (v if v not in ("", "None") else None) for k, v in raw.items()}
        for key in _INT_FIELDS:
            if row.get(key) is not None:
                try:
                    row[key] = int(row[key])
                except ValueError:
                    pass
        for key in _FLOAT_FIELDS:
            if row.get(key) is not None:
                try:
                    row[key] = float(row[key])
                except ValueError:
                    pass
        meta = row.get("metadata")
        try:
            decoded = json.loads(meta) if isinstance(meta, str) and meta else (meta or {})
        except json.JSONDecodeError:
            decoded = {}
        row["metadata"] = decoded if isinstance(decoded, dict) else {}
        rows.append(row)
    return rows


class MiloAgentClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._http = httpx.AsyncClient(base_url=settings.url, timeout=settings.timeout, transport=transport)
        self._token: str | None = None
        self._login_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _login(self) -> str:
        async with self._login_lock:
            if self._token:
                return self._token
            try:
                resp = await self._http.post(
                    LOGIN_PATH,
                    json={"username": self._settings.username, "password": self._settings.password},
                )
            except httpx.HTTPError as exc:
                raise MiloAgentError(f"MiloAgent login failed: {type(exc).__name__}") from exc
            if resp.status_code != 200:
                raise MiloAgentError(f"MiloAgent login failed: HTTP {resp.status_code}")
            try:
                body = resp.json()
            except ValueError:
                body = None
            token = body.get("token") if isinstance(body, dict) else None
            if not token or not isinstance(token, str):
                raise MiloAgentError("MiloAgent login returned no token")
            self._token = token
            return token

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        for attempt in (1, 2):
            token = await self._login()
            try:
                resp = await self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise MiloAgentError(f"MiloAgent {path} failed: {type(exc).__name__}") from exc
            if resp.status_code == 401 and attempt == 1:
                # MiloAgent restarted or the session expired; keep a newer token
                if self._token == token:
                    self._token = None
                continue
            if resp.status_code != 200:
                raise MiloAgentError(f"MiloAgent {path} failed: HTTP {resp.status_code}")
            return resp
        raise MiloAgentError(f"MiloAgent {path} failed: HTTP 401")

    async def _cached(self, key: str, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and now - hit[0] < self._settings.cache_seconds:
            return hit[1]
        resp = await self._get(path, params)
        if path == ACTIONS_PATH:
            rows = parse_rows(resp.json())
        else:
            rows = parse_csv(resp.text)
        self._cache[key] = (now, rows)
        return rows

    async def opportunities(self, statuses: tuple[str, ...] = STATUSES) -> list[dict[str, Any]]:
        """MiloAgent's findings (table opportunities) with the given statuses."""
        out: list[dict[str, Any]] = []
        for status in statuses:
            out.extend(await self._cached(f"opp:{status}", OPPORTUNITIES_PATH, {"status": status}))
        return out

    async def actions(self) -> list[dict[str, Any]]:
        """MiloAgent's newest 200 own actions (comments, posts) of the last year; callers filter."""
        return await self._cached("actions", ACTIONS_PATH, {"limit": MAX_ACTIONS})
