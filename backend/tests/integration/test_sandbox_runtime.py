"""T069 [US6] — LIVE sandbox runtime probes.

These exercise the hardening against a real Docker daemon: the model process
runs as the non-root UID, cannot reach the network, cannot write outside its
bounded output mount, and runs under a dropped-capability / no-new-privileges
profile. They are skipped where no daemon (or the sandbox image) is available —
CI has no Docker service, so the config-as-data assertions in
tests/contract/test_sandbox_hardening.py are the always-on backstop and these
run on a Docker host.

The probes reuse the EXACT ``docker_container_config`` the runner ships, only
overriding the command, so they test the posture that production actually uses.
"""

import pytest

from engine.sandbox import runner


def _client_or_skip():
    if not runner._docker_available():
        pytest.skip("no Docker daemon — live sandbox runtime probes require a Docker host (T069)")
    import docker

    client = docker.from_env()
    try:
        client.images.get(runner.DOCKER_IMAGE)
    except Exception:
        pytest.skip(f"sandbox image {runner.DOCKER_IMAGE} not built — skipping live probes")
    return client


def _probe(client, tmp_path, command: list[str]) -> tuple[int, str]:
    from pathlib import Path

    samples = Path(__file__).resolve().parents[2].parent / "samples"
    cfg = runner.docker_container_config(
        "stub",
        str(samples / "models" / "healthy_detector.stub.json"),
        "detection",
        str(samples / "golden" / "det-golden"),
        tmp_path,
    )
    cfg["command"] = command
    container = client.containers.run(**cfg)
    try:
        status = container.wait(timeout=60)
        logs = container.logs().decode(errors="replace")
    finally:
        container.remove(force=True)
    return status.get("StatusCode", 1), logs


def test_runs_as_non_root_uid(tmp_path):
    client = _client_or_skip()
    _code, logs = _probe(client, tmp_path, ["python", "-c", "import os;print('UID', os.getuid())"])
    assert "UID 65532" in logs


def test_network_is_unreachable(tmp_path):
    client = _client_or_skip()
    probe = (
        "import socket\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 443), timeout=3)\n"
        "    print('NET_OPEN')\n"
        "except OSError:\n"
        "    print('NET_BLOCKED')\n"
    )
    _code, logs = _probe(client, tmp_path, ["python", "-c", probe])
    assert "NET_BLOCKED" in logs and "NET_OPEN" not in logs


def test_root_filesystem_is_read_only(tmp_path):
    client = _client_or_skip()
    probe = (
        "try:\n"
        "    open('/should_not_write', 'w').write('x')\n"
        "    print('WROTE_ROOT')\n"
        "except OSError:\n"
        "    print('ROOT_READONLY')\n"
    )
    _code, logs = _probe(client, tmp_path, ["python", "-c", probe])
    assert "ROOT_READONLY" in logs and "WROTE_ROOT" not in logs


def test_output_mount_is_writable(tmp_path):
    client = _client_or_skip()
    probe = "open('/mnt/out/probe.txt', 'w').write('ok'); print('WROTE_OUT')"
    _code, logs = _probe(client, tmp_path, ["python", "-c", probe])
    assert "WROTE_OUT" in logs
