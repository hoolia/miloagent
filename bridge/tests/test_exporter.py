from __future__ import annotations

import errno
import os
import sqlite3
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

import pytest

from miloagent_bridge import exporter
from miloagent_bridge.exporter import Collector, ExporterSettings, LogState, feed

NOW = datetime(2026, 11, 21, 14, 0, 0, tzinfo=timezone.utc).timestamp()

# lines as MiloAgent's RotatingFileHandler and APScheduler write them
LOG = """\
2026-11-21 13:38:45 [INFO] apscheduler.scheduler: Added job "Orchestrator._db_maintenance" to job store "default"
2026-11-21 13:38:45 [INFO] apscheduler.scheduler: Added job "Orchestrator.start.<locals>.<lambda>" to job store "default"
2026-11-21 13:38:45 [INFO] core.orchestrator: Milo started in server mode.
2026-11-21 13:40:45 [INFO] core.orchestrator: Starting scan cycle...
2026-11-21 13:40:45 [WARNING] platforms.reddit_web: Reddit blocked r/selfhosted (403 HTML) — skipping for 4h
2026-11-21 09:00:00 [WARNING] platforms.reddit_web: Reddit blocked r/oldsub (403 HTML) — skipping for 4h
2026-11-21 13:43:39 [INFO] core.orchestrator: Scan cycle complete
2026-11-21 13:43:39 [INFO] apscheduler.executors.default: Job "Orchestrator._scan_all_safe (trigger: interval[0:12:00], next run at: 2026-11-21 13:52:45 UTC)" executed successfully
2026-11-21 13:45:45 [ERROR] platforms.reddit_web: Cannot post: Reddit token_v2 expired for u/Some-User_1. Get a fresh token_v2 from your browser:
  1. Open reddit.com (logged in)
2026-11-21 13:48:45 [ERROR] apscheduler.executors.default: Job "Orchestrator._health_check (trigger: interval[1:00:00], next run at: 2026-11-21 14:48:45 UTC)" raised an exception
Traceback (most recent call last):
sqlite3.OperationalError: disk I/O error
2026-11-21 13:49:00 [ERROR] core.orchestrator: DB maintenance failed: attempt to write a readonly database
2026-11-21 13:50:00 [WARNING] apscheduler.executors.default: Run time of job "Orchestrator._act_on_best_safe (trigger: interval[0:08:00], next run at: 2026-11-21 13:58:00 UTC)" was missed by 0:00:05
"""


def make_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE actions (id INTEGER PRIMARY KEY, timestamp TEXT, platform TEXT, action_type TEXT,
          account TEXT, project TEXT, target_id TEXT, content TEXT, metadata TEXT, success INTEGER, error_message TEXT);
        CREATE TABLE opportunities (id INTEGER PRIMARY KEY, timestamp TEXT, platform TEXT, target_id TEXT,
          title TEXT, subreddit_or_query TEXT, score REAL, project TEXT, status TEXT, metadata TEXT);
        CREATE TABLE account_health (id INTEGER PRIMARY KEY, timestamp TEXT, platform TEXT, account TEXT,
          status TEXT, action_count_1h INTEGER, action_count_24h INTEGER, last_action TEXT, notes TEXT);
        INSERT INTO actions (timestamp, platform, account, success) VALUES ('2026-11-21 12:00:00', 'reddit', 'a', 1);
        INSERT INTO actions (timestamp, platform, account, success) VALUES ('2026-11-20 12:00:00', 'reddit', 'a', 0);
        INSERT INTO opportunities (timestamp, platform, target_id, status) VALUES ('2026-11-21 11:00:00', 'reddit', 't1', 'pending');
        INSERT INTO opportunities (timestamp, platform, target_id, status) VALUES ('2026-11-21 12:00:00', 'reddit', 't2', 'pending');
        INSERT INTO account_health (timestamp, platform, account, status) VALUES ('2026-11-12 18:00:00', 'reddit', 'a', 'healthy');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
def pod(tmp_path):
    volume = tmp_path / "volume"
    (volume / "data").mkdir(parents=True)
    make_db(str(volume / "data" / "miloagent.db"))
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "miloagent.log").write_text(LOG)
    return ExporterSettings(
        volume_dir=str(volume),
        db_path=str(volume / "data" / "miloagent.db"),
        log_path=str(logs / "miloagent.log"),
        health_url="http://unused",
        timeout=2,
    )


def samples(text: str) -> dict[str, float]:
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            out[name] = float(value)
    return out


def collect(settings, health=True) -> dict[str, float]:
    return samples(Collector(settings, clock=lambda: NOW, health=lambda url, t: health).collect())


def test_healthy_pod(pod):
    s = collect(pod)
    assert s["miloagent_up"] == 1
    assert s["miloagent_volume_writable"] == 1
    assert s["miloagent_volume_readonly"] == 0
    assert s["miloagent_db_readable"] == 1
    assert os.path.exists(os.path.join(pod.volume_dir, exporter.PROBE_FILE))


def test_probe_never_touches_miloagent_files(pod):
    data = os.path.join(pod.volume_dir, "data")
    before = {f: os.stat(os.path.join(data, f)).st_mtime_ns for f in os.listdir(data)}
    collect(pod)
    after = {f: os.stat(os.path.join(data, f)).st_mtime_ns for f in os.listdir(data)}
    assert set(after) - set(before) <= {"miloagent.db-shm", "miloagent.db-wal"}
    assert {f: after[f] for f in before} == before


def test_log_metrics(pod):
    s = collect(pod)
    assert s['miloagent_log_db_errors_total{kind="db_io"}'] == 1
    assert s['miloagent_log_db_errors_total{kind="db_readonly"}'] == 1
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_health_check"}'] == 1
    assert s['miloagent_scheduler_job_runs_total{result="success",task="_scan_all_safe"}'] == 1
    assert s['miloagent_scheduler_job_runs_total{result="missed",task="_act_on_best_safe"}'] == 1
    # every result of a known task exists from 0 on, so increase() sees the first error
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_scan_all_safe"}'] == 0
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_db_maintenance"}'] == 0
    assert not any("lambda" in k for k in s)
    assert s['miloagent_log_messages_total{level="ERROR"}'] == 3
    assert s["miloagent_last_scan_complete_timestamp_seconds"] == datetime(
        2026, 11, 21, 13, 43, 39, tzinfo=timezone.utc
    ).timestamp()
    # r/oldsub's 4 hours ended at 13:00, before NOW
    assert s["miloagent_reddit_blocked_subreddits"] == 1
    assert 'miloagent_reddit_subreddit_blocked_until_seconds{status="403",subreddit="selfhosted"}' in s
    assert 'miloagent_reddit_token_expired_timestamp_seconds{account="Some-User_1"}' in s


def test_database_metrics(pod):
    s = collect(pod)
    assert s['miloagent_opportunities{status="pending"}'] == 2
    assert s['miloagent_account_health_timestamp_seconds{account="a",platform="reddit",status="healthy"}'] == (
        datetime(2026, 11, 12, 18, 0, 0, tzinfo=timezone.utc).timestamp()
    )
    assert 'miloagent_last_action_timestamp_seconds{platform="reddit",result="failure"}' in s


def test_read_only_volume(pod, monkeypatch):
    real_open = os.open

    def erofs(path, *args, **kwargs):
        if path.endswith(exporter.PROBE_FILE):
            raise OSError(errno.EROFS, "Read-only file system")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(exporter.os, "open", erofs)
    s = collect(pod)
    assert s["miloagent_volume_writable"] == 0
    # reads still work on a read-only file system
    assert s["miloagent_db_readable"] == 1


def test_hung_probe_reports_stuck(pod, monkeypatch):
    release = threading.Event()

    def hang(directory):
        release.wait(5)
        return True, False, ""

    monkeypatch.setattr(exporter, "probe_volume", hang)
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.settings = ExporterSettings(**{**pod.__dict__, "timeout": 0.1})
    s = samples(collector.collect())
    assert s["miloagent_volume_writable"] == 0
    assert s["miloagent_volume_probe_stuck"] == 1
    s = samples(collector.collect())
    assert s["miloagent_volume_probe_stuck"] == 1
    release.set()


def test_failed_probe_releases_the_lock(pod, monkeypatch):
    def boom(directory):
        raise ValueError("unexpected")

    monkeypatch.setattr(exporter, "probe_volume", boom)
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    for _ in range(2):
        s = samples(collector.collect())
        assert s["miloagent_volume_writable"] == 0
        assert s["miloagent_volume_probe_stuck"] == 0


def test_null_rows_give_one_series_each(pod):
    conn = sqlite3.connect(pod.db_path)
    conn.executescript(
        """
        INSERT INTO actions (timestamp, platform, account, success) VALUES ('2026-11-19 12:00:00', 'reddit', 'a', NULL);
        INSERT INTO opportunities (timestamp, platform, target_id, status) VALUES ('2026-11-21 10:00:00', 'reddit', 't3', NULL);
        INSERT INTO opportunities (timestamp, platform, target_id, status) VALUES ('2026-11-21 10:30:00', 'reddit', 't4', '');
        """
    )
    conn.commit()
    conn.close()
    text = Collector(pod, clock=lambda: NOW, health=lambda url, t: True).collect()
    series = [line.rsplit(" ", 1)[0] for line in text.splitlines() if line and not line.startswith("#")]
    assert len(series) == len(set(series))
    s = samples(text)
    assert s['miloagent_opportunities{status=""}'] == 2
    assert s['miloagent_last_action_timestamp_seconds{platform="reddit",result="failure"}'] == (
        datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc).timestamp()
    )


def test_bad_timestamp_row_reports_unreadable_db(pod):
    conn = sqlite3.connect(pod.db_path)
    conn.execute("INSERT INTO actions (timestamp, platform, account, success) VALUES ('2026-11-22', 'reddit', 'a', 1)")
    conn.commit()
    conn.close()
    s = collect(pod)
    assert s["miloagent_db_readable"] == 0
    assert s["miloagent_volume_writable"] == 1


def test_failed_collection_serves_503(pod, monkeypatch):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.refresh()
    assert collector.text()

    def boom():
        raise RuntimeError("collection broke")

    monkeypatch.setattr(collector, "collect", boom)
    collector.refresh()
    assert collector.text() == ""


def test_hung_collection_goes_stale(pod, monkeypatch):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.refresh()
    assert collector.text()
    # a collection that never returns: the last result ages past stale_after
    real = exporter.time.monotonic
    monkeypatch.setattr(exporter.time, "monotonic", lambda: real() + collector.stale_after() + 1)
    assert collector.text() == ""


def test_truncated_log_is_read_from_its_start(pod):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.collect()
    with open(pod.log_path, "w") as fh:
        fh.write(
            '2026-11-21 13:59:00 [ERROR] apscheduler.executors.default: Job "Orchestrator._health_check '
            '(trigger: interval[1:00:00], next run at: x)" raised an exception\n'
        )
    s = samples(collector.collect())
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_health_check"}'] == 2


def test_missing_log_is_not_readable(pod):
    os.remove(pod.log_path)
    assert collect(pod)["miloagent_exporter_log_readable"] == 0


def test_rotation_keeps_the_old_files_last_lines(pod):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.collect()
    with open(pod.log_path, "a") as fh:
        fh.write(
            '2026-11-21 13:58:00 [ERROR] apscheduler.executors.default: Job "Orchestrator._health_check '
            '(trigger: interval[1:00:00], next run at: x)" raised an exception\n'
        )
    os.rename(pod.log_path, pod.log_path + ".1")
    with open(pod.log_path, "w") as fh:
        fh.write("")
    s = samples(collector.collect())
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_health_check"}'] == 2


def test_job_names_with_a_module_path():
    state = LogState()
    feed(state, '2026-11-21 13:43:39 [INFO] apscheduler.executors.default: Job "core.orchestrator.Orchestrator._scan_all_safe '
                '(trigger: interval[0:12:00], next run at: x)" executed successfully')
    assert state.jobs[("_scan_all_safe", "success")] == 1


def test_probe_does_not_follow_a_symlink(pod, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    os.symlink(victim, os.path.join(pod.volume_dir, exporter.PROBE_FILE))
    assert collect(pod)["miloagent_volume_writable"] == 0
    assert victim.read_text() == "keep"


def test_missing_database_and_down_app(pod):
    os.remove(pod.db_path)
    s = collect(pod, health=False)
    assert s["miloagent_up"] == 0
    assert s["miloagent_db_readable"] == 0


def test_no_scan_yet_reports_start_time(pod):
    with open(pod.log_path, "w") as fh:
        fh.write("2026-11-21 13:38:45 [INFO] core.orchestrator: Milo started in server mode.\n")
    assert collect(pod)["miloagent_last_scan_complete_timestamp_seconds"] == NOW


def test_log_rotation_starts_over(pod):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    collector.collect()
    os.rename(pod.log_path, pod.log_path + ".1")
    with open(pod.log_path, "w") as fh:
        fh.write(
            '2026-11-21 13:59:00 [ERROR] apscheduler.executors.default: Job "Orchestrator._health_check '
            '(trigger: interval[1:00:00], next run at: x)" raised an exception\n'
        )
    s = samples(collector.collect())
    assert s['miloagent_scheduler_job_runs_total{result="error",task="_health_check"}'] == 2


def test_partial_line_waits_for_newline(tmp_path):
    path = tmp_path / "miloagent.log"
    path.write_text("2026-11-21 13:43:39 [INFO] core.orchestrator: Scan cycle")
    tail = exporter.LogTail(str(path))
    state = LogState()
    assert tail.read_lines() == []
    with open(path, "a") as fh:
        fh.write(" complete\n")
    for line in tail.read_lines():
        feed(state, line)
    assert state.last_scan_complete > 0


def test_label_values_are_escaped():
    m = exporter.Metrics()
    m.add("x", "gauge", "h", 1, a='q"\\\n')
    assert 'x{a="q\\"\\\\\\n"} 1' in m.render()


def test_http_endpoints(pod):
    collector = Collector(pod, clock=lambda: NOW, health=lambda url, t: True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), exporter.make_handler(collector))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(base + "/metrics")
        assert err.value.code == 503
        collector.refresh()
        with urllib.request.urlopen(base + "/metrics") as resp:
            body = resp.read().decode()
        assert "# TYPE miloagent_volume_writable gauge" in body
        with urllib.request.urlopen(base + "/healthz") as resp:
            assert resp.status == 200
    finally:
        server.shutdown()


def test_settings_from_env():
    s = ExporterSettings.from_env({"EXPORTER_PORT": "9999", "EXPORTER_VOLUME_DIR": "/v"})
    assert s.port == 9999
    assert s.volume_dir == "/v"
    assert s.db_path == "/volume/data/miloagent.db"
