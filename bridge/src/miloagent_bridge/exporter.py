"""Prometheus exporter for MiloAgent, run as a sidecar in the MiloAgent pod.

MiloAgent stays unchanged. The exporter reads MiloAgent's log file and its SQLite
database read-only, calls the unauthenticated `GET /health`, and writes one probe file of
its own at the root of the data volume to prove the volume still takes writes. It never
writes MiloAgent's files and never calls an authenticated MiloAgent API.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
import http.client
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("miloagent_bridge.exporter")

PROBE_FILE = ".miloagent-exporter-probe"

LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[(\w+)\] ([\w.]+): (.*)$")
JOB_OK = re.compile(r'^Job "(?:[\w.]+\.)?(\w+) \(trigger.*" executed successfully$')
JOB_ERROR = re.compile(r'^Job "(?:[\w.]+\.)?(\w+) \(trigger.*" raised an exception$')
JOB_MISSED = re.compile(r'^Run time of job "(?:[\w.]+\.)?(\w+) \(trigger.*" was missed')
JOB_ADDED = re.compile(r'^Added job "(?:[\w.]+\.)?(\w+)" to job store')
JOB_RESULTS = ("success", "error", "missed")
BLOCKED = re.compile(r"^Reddit blocked r/([\w-]+) \((\d{3})[^)]*\) .*skipping for (\d+)h")
TOKEN_EXPIRED = re.compile(r"token_v2 expired for u/([\w-]+)")
SCAN_COMPLETE = "Scan cycle complete"
# SQLite error text (sqlite3.OperationalError / DatabaseError) per kind
DB_ERRORS = {
    "db_io": "disk I/O error",
    "db_readonly": "attempt to write a readonly database",
    "db_malformed": "database disk image is malformed",
    "db_full": "database or disk is full",
    "db_locked": "database is locked",
}
LEVELS = ("WARNING", "ERROR", "CRITICAL")


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{k}="{_esc(str(v))}"' for k, v in sorted(labels.items())) + "}"


class Metrics:
    """A family-ordered text exposition (Prometheus text format 0.0.4)."""

    def __init__(self) -> None:
        self._families: dict[str, tuple[str, str, list[tuple[dict[str, str], float]]]] = {}

    def add(self, name: str, kind: str, help_text: str, value: float, /, **labels: str) -> None:
        family = self._families.setdefault(name, (kind, help_text, []))
        family[2].append((labels, float(value)))

    def declare(self, name: str, kind: str, help_text: str) -> None:
        self._families.setdefault(name, (kind, help_text, []))

    def render(self) -> str:
        out: list[str] = []
        for name, (kind, help_text, samples) in self._families.items():
            out.append(f"# HELP {name} {help_text}")
            out.append(f"# TYPE {name} {kind}")
            for labels, value in samples:
                out.append(f"{name}{_labels(labels)} {value:.17g}")
        return "\n".join(out) + "\n"


@dataclass
class LogState:
    """What the log has said since the exporter started reading it."""

    lines: int = 0
    levels: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LEVELS, 0))
    db_errors: dict[str, int] = field(default_factory=lambda: dict.fromkeys(DB_ERRORS, 0))
    jobs: dict[tuple[str, str], int] = field(default_factory=dict)
    # jobs the scheduler registered at start ("Added job ... to job store")
    tasks: set[str] = field(default_factory=set)
    job_last: dict[tuple[str, str], float] = field(default_factory=dict)
    last_scan_complete: float = 0.0
    # subreddit -> (block time, block seconds, HTTP status)
    blocked: dict[str, tuple[float, float, str]] = field(default_factory=dict)
    token_expired: dict[str, float] = field(default_factory=dict)


def parse_time(text: str, tz: timezone = timezone.utc) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz).timestamp()


def feed(state: LogState, line: str, tz: timezone = timezone.utc) -> None:
    """Update the state with one log line. Continuation lines carry no timestamp."""
    state.lines += 1
    # an error text counts on a log line and on a traceback line alike
    for kind, text in DB_ERRORS.items():
        if text in line:
            state.db_errors[kind] += 1
    match = LINE.match(line.rstrip("\n"))
    if not match:
        return
    stamp, level, _logger, message = match.groups()
    ts = parse_time(stamp, tz)
    if level in state.levels:
        state.levels[level] += 1
    for pattern, result in ((JOB_OK, "success"), (JOB_ERROR, "error"), (JOB_MISSED, "missed")):
        job = pattern.match(message)
        if job:
            key = (job.group(1), result)
            state.jobs[key] = state.jobs.get(key, 0) + 1
            state.job_last[key] = ts
            return
    added = JOB_ADDED.match(message)
    if added:
        state.tasks.add(added.group(1))
        return
    if message == SCAN_COMPLETE:
        state.last_scan_complete = ts
        return
    blocked = BLOCKED.match(message)
    if blocked:
        state.blocked[blocked.group(1)] = (ts, int(blocked.group(3)) * 3600.0, blocked.group(2))
        return
    expired = TOKEN_EXPIRED.search(message)
    if expired:
        state.token_expired[expired.group(1)] = ts


class LogTail:
    """Reads a log file incrementally; starts over after rotation or truncation."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh = None
        self._inode: int | None = None
        self._partial = ""

    def read_lines(self) -> list[str]:
        """New complete lines. Raises FileNotFoundError when the log is missing."""
        st = os.stat(self.path)
        lines: list[str] = []
        if self._fh is None or st.st_ino != self._inode or st.st_size < self._fh.tell():
            if self._fh is not None:
                # after a rotation the old file may still hold lines written since the last read
                if st.st_ino != self._inode:
                    rest = self._partial + self._fh.read()
                    if rest:
                        lines = rest.rstrip("\n").split("\n")
                self._fh.close()
            self._fh = open(self.path, encoding="utf-8", errors="replace")  # noqa: SIM115
            self._inode = st.st_ino
            self._partial = ""
        data = self._partial + self._fh.read()
        new = data.split("\n")
        self._partial = new.pop()
        return lines + new


def probe_volume(directory: str) -> tuple[bool, bool, str]:
    """Write and fsync a probe file. Returns (writable, readonly flag, error text)."""
    readonly = False
    try:
        readonly = bool(os.statvfs(directory).f_flag & os.ST_RDONLY)
    except OSError as exc:
        return False, readonly, exc.strerror or str(exc)
    path = os.path.join(directory, PROBE_FILE)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
        try:
            os.write(fd, str(time.time()).encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        return False, readonly, exc.strerror or str(exc)
    return True, readonly, ""


def _ts(text: str | None) -> float:
    """SQLite datetime('now') text (UTC) to a Unix time; 0 when empty."""
    if not text:
        return 0.0
    return parse_time(text[:19].replace("T", " "))


def read_database(path: str) -> dict:
    """Read MiloAgent's SQLite database read-only (mode=ro, no write lock)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    try:
        health = [
            (platform, account, status or "", _ts(stamp))
            for platform, account, status, stamp in conn.execute(
                "SELECT platform, account, status, max(timestamp) FROM account_health GROUP BY platform, account"
            )
        ]
        actions = [
            (platform, "success" if success else "failure", _ts(stamp))
            # grouped by the label value, so a NULL success or status adds no second series
            for platform, success, stamp in conn.execute(
                "SELECT platform, coalesce(success, 0) != 0 AS ok, max(timestamp) FROM actions GROUP BY platform, ok"
            )
        ]
        opportunities = [
            (status, count, _ts(stamp))
            for status, count, stamp in conn.execute(
                "SELECT coalesce(status, '') AS st, count(*), max(timestamp) FROM opportunities GROUP BY st"
            )
        ]
    finally:
        conn.close()
    return {"health": health, "actions": actions, "opportunities": opportunities}


def check_health(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - fixed in-pod URL
            return resp.status == 200
    except (OSError, http.client.HTTPException):
        return False


@dataclass(frozen=True)
class ExporterSettings:
    volume_dir: str = "/volume"
    db_path: str = "/volume/data/miloagent.db"
    log_path: str = "/app/logs/miloagent.log"
    health_url: str = "http://127.0.0.1:8420/health"
    port: int = 9420
    interval: float = 30.0
    timeout: float = 10.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> ExporterSettings:
        env = dict(os.environ if env is None else env)
        d = cls()
        return cls(
            volume_dir=env.get("EXPORTER_VOLUME_DIR", d.volume_dir),
            db_path=env.get("EXPORTER_DB_PATH", d.db_path),
            log_path=env.get("EXPORTER_LOG_PATH", d.log_path),
            health_url=env.get("EXPORTER_HEALTH_URL", d.health_url),
            port=int(env.get("EXPORTER_PORT", d.port)),
            interval=float(env.get("EXPORTER_INTERVAL_SECONDS", d.interval)),
            timeout=float(env.get("EXPORTER_TIMEOUT_SECONDS", d.timeout)),
        )


class Collector:
    """Collects every `interval` seconds; scrapes read the last result."""

    def __init__(
        self,
        settings: ExporterSettings,
        clock: Callable[[], float] = time.time,
        health: Callable[[str, float], bool] = check_health,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.health = health
        self.started = clock()
        self.state = LogState()
        self.tail = LogTail(settings.log_path)
        self._probe_lock = threading.Lock()
        self._probe_result: tuple[bool, bool, str, float] | None = None
        self._probe_started = 0.0
        self._text = ""
        self._done = 0.0
        self._lock = threading.Lock()

    def _probe(self) -> None:
        start = time.monotonic()
        try:
            writable, readonly, error = probe_volume(self.settings.volume_dir)
            self._probe_result = (writable, readonly, error, time.monotonic() - start)
        except Exception as exc:  # noqa: BLE001 - a failed probe reports, it never keeps the lock
            self._probe_result = (False, False, str(exc), time.monotonic() - start)
        finally:
            self._probe_lock.release()

    def _volume(self) -> tuple[bool, bool, str, float, bool]:
        """Probe in a thread: a hung fsync on a dead block device reports stuck, not hangs."""
        if self._probe_lock.acquire(blocking=False):
            self._probe_started = time.monotonic()
            thread = threading.Thread(target=self._probe, daemon=True)
            try:
                thread.start()
            except RuntimeError as exc:
                self._probe_lock.release()
                return False, False, str(exc), 0.0, False
            thread.join(self.settings.timeout)
        if self._probe_lock.locked():
            stuck_for = time.monotonic() - self._probe_started
            return False, False, "probe did not finish", stuck_for, True
        writable, readonly, error, duration = self._probe_result or (False, False, "no probe", 0.0)
        return writable, readonly, error, duration, False

    def collect(self) -> str:
        now = self.clock()
        m = Metrics()
        m.add("miloagent_exporter_start_time_seconds", "gauge", "Start time of the exporter.", self.started)

        up = self.health(self.settings.health_url, self.settings.timeout)
        m.add("miloagent_up", "gauge", "1 when MiloAgent answers GET /health with 200.", 1 if up else 0)

        writable, readonly, error, duration, stuck = self._volume()
        m.add(
            "miloagent_volume_writable",
            "gauge",
            "1 when a probe file at the data volume root was written and fsynced.",
            1 if writable else 0,
        )
        m.add("miloagent_volume_readonly", "gauge", "1 when the data volume file system is read-only.", 1 if readonly else 0)
        m.add("miloagent_volume_probe_stuck", "gauge", "1 while a volume probe has not returned.", 1 if stuck else 0)
        m.add("miloagent_volume_probe_duration_seconds", "gauge", "Duration of the last volume probe.", duration)
        if error:
            log.warning("volume probe failed: %s", error)

        try:
            m.add("miloagent_db_size_bytes", "gauge", "Size of the SQLite main file.", os.path.getsize(self.settings.db_path))
            db = read_database(self.settings.db_path)
            m.add("miloagent_db_readable", "gauge", "1 when the SQLite database answered a read-only query.", 1)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            log.warning("database read failed: %s", exc)
            db = None
            m.add("miloagent_db_readable", "gauge", "1 when the SQLite database answered a read-only query.", 0)
        m.declare("miloagent_account_health_timestamp_seconds", "gauge", "Last account health row MiloAgent wrote.")
        m.declare("miloagent_last_action_timestamp_seconds", "gauge", "Last action MiloAgent stored.")
        m.declare("miloagent_opportunities", "gauge", "Stored opportunities by status.")
        m.declare("miloagent_last_opportunity_timestamp_seconds", "gauge", "Last opportunity stored, by status.")
        if db:
            for platform, account, status, stamp in db["health"]:
                m.add("miloagent_account_health_timestamp_seconds", "gauge", "", stamp,
                      platform=platform, account=account, status=status)
            for platform, result, stamp in db["actions"]:
                m.add("miloagent_last_action_timestamp_seconds", "gauge", "", stamp, platform=platform, result=result)
            for status, count, stamp in db["opportunities"]:
                m.add("miloagent_opportunities", "gauge", "", count, status=status)
                m.add("miloagent_last_opportunity_timestamp_seconds", "gauge", "", stamp, status=status)

        try:
            for line in self.tail.read_lines():
                feed(self.state, line)
            log_ok = 1
        except OSError as exc:
            log.warning("log read failed: %s", exc)
            log_ok = 0
        s = self.state
        m.add("miloagent_exporter_log_readable", "gauge", "1 when the MiloAgent log file was read.", log_ok)
        m.add("miloagent_exporter_log_lines_total", "counter", "Log lines read.", s.lines)
        for level, count in s.levels.items():
            m.add("miloagent_log_messages_total", "counter", "Log messages by level.", count, level=level)
        for kind, count in s.db_errors.items():
            m.add("miloagent_log_db_errors_total", "counter", "Logged SQLite errors by kind.", count, kind=kind)
        m.declare("miloagent_scheduler_job_runs_total", "counter", "Scheduled job runs by result.")
        m.declare("miloagent_scheduler_job_last_timestamp_seconds", "gauge", "Last scheduled job run by result.")
        # every result of a seen task starts at 0, so increase() sees the first error
        # (a counter series that is born at 1 shows no increase)
        tasks = sorted({job for job, _ in s.jobs} | s.tasks)
        for job in tasks:
            for result in JOB_RESULTS:
                m.add("miloagent_scheduler_job_runs_total", "counter", "", s.jobs.get((job, result), 0),
                      task=job, result=result)
        for (job, result), stamp in sorted(s.job_last.items()):
            m.add("miloagent_scheduler_job_last_timestamp_seconds", "gauge", "", stamp, task=job, result=result)
        # before the first scan after a start, the start counts: no alert for a fresh pod
        m.add(
            "miloagent_last_scan_complete_timestamp_seconds",
            "gauge",
            "Last 'Scan cycle complete' in the log, else the exporter start.",
            s.last_scan_complete or self.started,
        )
        active = {sub: v for sub, v in s.blocked.items() if v[0] + v[1] > now}
        m.add("miloagent_reddit_blocked_subreddits", "gauge", "Subreddits Reddit currently blocks for MiloAgent.", len(active))
        m.declare("miloagent_reddit_subreddit_blocked_until_seconds", "gauge", "End of the skip time of a blocked subreddit.")
        for sub, (ts, seconds, status) in sorted(active.items()):
            m.add("miloagent_reddit_subreddit_blocked_until_seconds", "gauge", "", ts + seconds,
                  subreddit=sub, status=status)
        m.declare("miloagent_reddit_token_expired_timestamp_seconds", "gauge", "Last 'token_v2 expired' per account.")
        for account, ts in sorted(s.token_expired.items()):
            m.add("miloagent_reddit_token_expired_timestamp_seconds", "gauge", "", ts, account=account)
        return m.render()

    def refresh(self) -> None:
        try:
            text = self.collect()
        except Exception:  # noqa: BLE001 - never crash the sidecar
            # no stale values: /metrics answers 503 until a collection succeeds again
            log.exception("collection failed")
            text = ""
        with self._lock:
            self._text = text
            self._done = time.monotonic()

    def stale_after(self) -> float:
        """Age after which the last result is stale: three intervals plus the timeouts."""
        return 3 * self.settings.interval + 3 * self.settings.timeout

    def text(self) -> str:
        """The last result; empty while none exists or once a collection hangs past stale_after."""
        with self._lock:
            if time.monotonic() - self._done > self.stale_after():
                return ""
            return self._text

    def run_forever(self, stop: threading.Event) -> None:
        while not stop.is_set():
            self.refresh()
            stop.wait(self.settings.interval)


def make_handler(collector: Collector) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            if self.path.split("?")[0] == "/metrics":
                body, ctype, code = collector.text().encode(), "text/plain; version=0.0.4; charset=utf-8", 200
                if not body:
                    body, ctype, code = b"no collection yet\n", "text/plain", 503
            elif self.path == "/healthz":
                body, ctype, code = b'{"status": "ok"}', "application/json", 200
            else:
                body, ctype, code = b"not found\n", "text/plain", 404
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: Iterable) -> None:
            return

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = ExporterSettings.from_env()
    collector = Collector(settings)
    collector.refresh()
    stop = threading.Event()
    threading.Thread(target=collector.run_forever, args=(stop,), daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", settings.port), make_handler(collector))  # noqa: S104 - pod network
    log.info("serving /metrics on port %d", settings.port)
    try:
        server.serve_forever()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
