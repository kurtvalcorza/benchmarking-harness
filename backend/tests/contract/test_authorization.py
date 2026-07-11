"""T017/T020b: endpoint 401/403 role-matrix contract.

A request with no token is 401 (WWW-Authenticate: Bearer); a valid token missing
the required role is 403, never 401 (security-boundary.md Failure semantics).
"""

from tests.conftest import bearer, det_manifest


def test_no_token_is_401_with_bearer_challenge(client):
    # strip the fixture's default auth header
    r = client.post("/golden-sets", json=det_manifest(), headers={"Authorization": ""})
    assert r.status_code == 401
    assert "bearer" in r.headers.get("WWW-Authenticate", "").lower()


def test_healthz_is_public(client):
    assert client.get("/healthz", headers={"Authorization": ""}).status_code == 200


def test_readyz_requires_auditor(client):
    ok = client.get("/readyz", headers=bearer("a", ["auditor"]))
    assert ok.status_code == 200
    forbidden = client.get("/readyz", headers=bearer("s", ["submitter"]))
    assert forbidden.status_code == 403


def test_golden_set_registration_requires_governance_not_submitter(client):
    # a valid submitter token authenticates, then is denied at authorization
    r = client.post(
        "/golden-sets", json=det_manifest(), headers=bearer("s", ["submitter"])
    )
    assert r.status_code == 403  # not 401
    # governance succeeds
    ok = client.post(
        "/golden-sets", json=det_manifest(), headers=bearer("g", ["governance"])
    )
    assert ok.status_code == 201


def test_adjudication_queue_requires_adjudicator_or_auditor(client):
    assert client.get("/adjudication/queue", headers=bearer("s", ["submitter"])).status_code == 403
    assert client.get("/adjudication/queue", headers=bearer("a", ["adjudicator"])).status_code == 200
    assert client.get("/adjudication/queue", headers=bearer("u", ["auditor"])).status_code == 200


def test_submit_requires_submitter(client):
    # governance-only token cannot submit a model
    files = {"weights": ("w.json", b"{}", "application/json")}
    data = {"name": "x", "model_class": "detection", "framework": "stub", "version": "v1"}
    r = client.post("/models", data=data, files=files, headers=bearer("g", ["governance"]))
    assert r.status_code == 403


def test_golden_set_status_object_scope(client):
    # governance owner registers; a different governance principal is denied,
    # the owner and any auditor are allowed (T020b)
    owner = bearer("owner@example.com", ["governance"])
    created = client.post("/golden-sets", json=det_manifest(), headers=owner).json()
    gid = created["id"]
    assert client.get(f"/golden-sets/{gid}", headers=owner).status_code == 200
    assert client.get(f"/golden-sets/{gid}", headers=bearer("u", ["auditor"])).status_code == 200
    other = bearer("other@example.com", ["governance"])
    assert client.get(f"/golden-sets/{gid}", headers=other).status_code == 403
