"""T068 (US6): the docker sandbox config carries the full hardening posture.

Asserted as data (no daemon needed): non-root user, cap_drop ALL,
no-new-privileges, the pinned seccomp profile, a bounded noexec tmpfs, and
read-only input mounts. The live runtime probes (T069) run on a docker host.
"""

from pathlib import Path

from engine.sandbox import runner

BACKEND = Path(__file__).resolve().parents[2]
SAMPLES = BACKEND.parent / "samples"


def _cfg(tmp_path):
    return runner.docker_container_config(
        "stub",
        str(SAMPLES / "models" / "healthy_detector.stub.json"),
        "detection",
        str(SAMPLES / "golden" / "det-golden"),
        tmp_path,
    )


def test_runs_as_non_root(tmp_path):
    assert _cfg(tmp_path)["user"] == "65532:65532"


def test_drops_all_capabilities(tmp_path):
    assert _cfg(tmp_path)["cap_drop"] == ["ALL"]


def test_no_new_privileges_and_seccomp(tmp_path):
    opts = _cfg(tmp_path)["security_opt"]
    assert "no-new-privileges:true" in opts
    # the pinned seccomp profile is applied (block-list of host-manipulation syscalls)
    seccomp = [o for o in opts if o.startswith("seccomp=")]
    assert seccomp, "the pinned seccomp profile must be applied"
    assert "SCMP_ACT_ERRNO" in seccomp[0] and "ptrace" in seccomp[0]


def test_tmpfs_is_bounded_and_noexec(tmp_path):
    tmpfs = _cfg(tmp_path)["tmpfs"]["/tmp"]
    for flag in ("noexec", "nosuid", "nodev", "size="):
        assert flag in tmpfs


def test_only_output_mount_is_writable(tmp_path):
    volumes = _cfg(tmp_path)["volumes"]
    for spec in volumes.values():
        if spec["bind"] == "/mnt/out":
            assert spec["mode"] == "rw"
        else:
            assert spec["mode"] == "ro"
