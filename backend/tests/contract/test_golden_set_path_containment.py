"""T020a: Golden Set data_ref must resolve beneath a configured data root.

Enforced at registration (422), not only in the runner, so an authenticated
governance caller cannot point the harness at arbitrary host paths.
"""

import shutil
import tempfile
from pathlib import Path

from tests.conftest import DET_GOLDEN, det_manifest


def test_data_ref_outside_roots_is_422(client):
    # a valid dataset, but placed OUTSIDE every configured data root
    outside = Path(tempfile.mkdtemp(prefix="harness-escape-"))
    try:
        shutil.copytree(DET_GOLDEN, outside / "golden")
        r = client.post("/golden-sets", json=det_manifest(data_ref=str(outside / "golden")))
        assert r.status_code == 422
        assert "path containment" in r.text
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_data_ref_traversal_is_rejected(client, tmp_path):
    # tmp_path IS an allowed root, but a `..` escape out of it is not
    escape = tmp_path / "sub" / ".." / ".." / "somewhere-else"
    r = client.post("/golden-sets", json=det_manifest(data_ref=str(escape)))
    assert r.status_code == 422


def test_contained_data_ref_is_accepted(client, tmp_path):
    # a dataset under the allowed tmp root registers normally
    dest = tmp_path / "contained-golden"
    shutil.copytree(DET_GOLDEN, dest)
    r = client.post("/golden-sets", json=det_manifest(data_ref=str(dest)))
    assert r.status_code == 201, r.text
