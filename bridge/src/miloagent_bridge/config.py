"""Settings from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Every opportunity status MiloAgent writes (core/database.py, core/orchestrator.py)
STATUSES = ("pending", "awaiting_approval", "acted", "skipped", "failed", "rejected")
# Rejected findings were judged not worth a reply; they are no buying signal
DEFAULT_SIGNAL_STATUSES = ("pending", "awaiting_approval", "acted", "skipped", "failed")


class ConfigError(ValueError):
    """A required setting is missing or malformed."""


@dataclass(frozen=True)
class Settings:
    url: str
    username: str
    password: str
    signal_statuses: tuple[str, ...] = DEFAULT_SIGNAL_STATUSES
    timeout: float = 30.0
    cache_seconds: float = 60.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Settings:
        env = dict(os.environ if env is None else env)
        missing = [k for k in ("MILOAGENT_URL", "MILOAGENT_PASSWORD") if not env.get(k)]
        if missing:
            raise ConfigError(f"missing environment variables: {', '.join(missing)}")
        url = env["MILOAGENT_URL"].rstrip("/")
        if not url.startswith(("https://", "http://")):
            raise ConfigError("MILOAGENT_URL must start with https:// or http://")
        raw = env.get("MILOAGENT_SIGNAL_STATUSES", "")
        statuses = tuple(s.strip() for s in raw.split(",") if s.strip()) or DEFAULT_SIGNAL_STATUSES
        unknown = [s for s in statuses if s not in STATUSES]
        if unknown:
            raise ConfigError(f"MILOAGENT_SIGNAL_STATUSES has unknown statuses: {', '.join(unknown)}")
        try:
            timeout = float(env.get("MILOAGENT_TIMEOUT", "30"))
            cache = float(env.get("MILOAGENT_CACHE_SECONDS", "60"))
        except ValueError as exc:
            raise ConfigError("MILOAGENT_TIMEOUT and MILOAGENT_CACHE_SECONDS must be numbers") from exc
        return cls(
            url=url,
            username=env.get("MILOAGENT_USERNAME") or "admin",
            password=env["MILOAGENT_PASSWORD"],
            signal_statuses=statuses,
            timeout=timeout,
            cache_seconds=cache,
        )
