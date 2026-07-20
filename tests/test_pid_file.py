import os
import tempfile

from core.orchestrator import Orchestrator


def _orch(pid_file):
    # _write_pid only needs .settings; skip the heavy __init__.
    o = Orchestrator.__new__(Orchestrator)
    o.settings = {"process": {"pid_file": pid_file}}
    return o


def _pid_path(tmpdir):
    return os.path.join(tmpdir, "data", "miloagent.pid")


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(str(value))


def test_own_pid_is_stale_not_another_instance():
    # The container case: the pid file survives on the PVC and holds the pid the
    # new process itself now has (1). It must not be read as another instance.
    with tempfile.TemporaryDirectory() as d:
        p = _pid_path(d)
        _write(p, os.getpid())
        _orch(p)._write_pid()  # must not raise
        assert open(p).read().strip() == str(os.getpid())


def test_dead_pid_is_stale():
    with tempfile.TemporaryDirectory() as d:
        p = _pid_path(d)
        _write(p, 4194303)  # above default pid_max; not running
        _orch(p)._write_pid()  # must not raise
        assert open(p).read().strip() == str(os.getpid())


def test_garbage_pid_file_is_stale():
    with tempfile.TemporaryDirectory() as d:
        p = _pid_path(d)
        _write(p, "not-a-pid")
        _orch(p)._write_pid()  # must not raise
        assert open(p).read().strip() == str(os.getpid())


def test_no_pid_file_writes_one():
    with tempfile.TemporaryDirectory() as d:
        p = _pid_path(d)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _orch(p)._write_pid()
        assert open(p).read().strip() == str(os.getpid())


def test_dead_pid_is_not_reported_as_miloagent():
    assert Orchestrator._pid_is_miloagent(4194303) is False


def test_non_miloagent_live_process_is_not_a_second_instance():
    # This test process is alive but is not miloagent, so a pid file naming it
    # must be treated as stale rather than blocking startup.
    if os.path.exists(f"/proc/{os.getpid()}/cmdline"):
        assert Orchestrator._pid_is_miloagent(os.getpid()) is False
