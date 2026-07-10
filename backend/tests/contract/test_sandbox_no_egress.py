"""T067 [D1] — an evaluation runs with no network access.

Three layers, matched to what this environment can prove:
1. The docker container config the runner hands to the daemon disables
   networking, mounts read-only, and caps resources (always testable).
2. The in-sandbox job's RUNTIME assertion aborts when the network is
   reachable (the D1 no-network assertion, tested by simulation).
3. A live subprocess-sandbox run: egress attempted from inside fails.
"""

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from engine.sandbox import runner
from engine.sandbox.job import assert_no_egress

BACKEND = Path(__file__).resolve().parents[2]
SAMPLES = BACKEND.parent / "samples"


def test_docker_config_is_hardened(tmp_path):
    cfg = runner.docker_container_config(
        "stub",
        str(SAMPLES / "models" / "healthy_detector.stub.json"),
        "detection",
        str(SAMPLES / "golden" / "det-golden"),
        tmp_path,
    )
    assert cfg["network_disabled"] is True  # --network none
    assert cfg["network_mode"] == "none"
    assert cfg["read_only"] is True
    for mount, spec in cfg["volumes"].items():
        if spec["bind"] != "/mnt/out":
            assert spec["mode"] == "ro", f"{mount} must be read-only"
    assert cfg["nano_cpus"] > 0 and cfg["mem_limit"]  # resource caps
    assert cfg["pids_limit"] > 0


def test_runtime_assertion_aborts_when_network_reachable(monkeypatch):
    """D1: if an outbound connection SUCCEEDS inside the sandbox, the job must
    refuse to run inference."""

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: FakeConn())
    with pytest.raises(SystemExit, match="SANDBOX VIOLATION"):
        assert_no_egress()


def test_runtime_assertion_passes_when_network_unreachable(monkeypatch):
    def refuse(*a, **k):
        raise OSError("unreachable")

    monkeypatch.setattr(socket, "create_connection", refuse)
    assert_no_egress()  # no exception


def test_subprocess_guard_blocks_egress(tmp_path):
    """A process under the fallback guard cannot open outbound connections."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import socket, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from engine.sandbox.job import _install_socket_guard\n"
        "_install_socket_guard()\n"
        "try:\n"
        "    socket.create_connection(('93.184.216.34', 80), timeout=3)\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e); sys.exit(0)\n"
        "sys.exit(1)\n"
    )
    proc = subprocess.run(
        [sys.executable, str(probe), str(BACKEND)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"egress was NOT blocked: {proc.stdout}{proc.stderr}"
    assert "BLOCKED" in proc.stdout


def test_subprocess_guard_blocks_udp_egress(tmp_path):
    """Connectionless UDP (sendto — e.g. DNS tunneling) is blocked too; only
    loopback datagrams are allowed."""
    probe = tmp_path / "probe_udp.py"
    probe.write_text(
        "import socket, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from engine.sandbox.job import _install_socket_guard\n"
        "_install_socket_guard()\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
        "try:\n"
        "    s.sendto(b'exfil', ('8.8.8.8', 53))\n"
        "except OSError as e:\n"
        "    print('BLOCKED', e)\n"
        "else:\n"
        "    sys.exit(1)\n"
        "s.sendto(b'ok', ('127.0.0.1', 9))  # loopback still permitted\n"
        "print('LOOPBACK_OK')\n"
        "sys.exit(0)\n"
    )
    proc = subprocess.run(
        [sys.executable, str(probe), str(BACKEND)], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"UDP egress was NOT blocked: {proc.stdout}{proc.stderr}"
    assert "BLOCKED" in proc.stdout and "LOOPBACK_OK" in proc.stdout


def test_live_sandboxed_inference_asserts_no_egress(tmp_path, monkeypatch):
    """End-to-end: a real inference job through the runner records that the
    no-egress assertion ran."""
    monkeypatch.setenv("HARNESS_SANDBOX_MODE", "subprocess")
    result = runner.run_inference(
        framework="stub",
        artifact=str(SAMPLES / "models" / "healthy_detector.stub.json"),
        model_class="detection",
        dataset_root=str(SAMPLES / "golden" / "det-golden"),
    )
    assert result.ok
    assert result.raw.get("egress_asserted") is True
    assert json.dumps(result.predictions)  # serializable evidence
