"""T023 (US1): submitters read only their own registrations; auditors read all.

The recorded identity is the token's principal_key, so a different submitter is
denied (403) and an auditor is allowed.
"""

from tests.conftest import HEALTHY_DET, bearer, det_manifest


def _submit_as(client, header, name):
    register = client.post("/golden-sets", json=det_manifest(), headers=bearer("g", ["governance"]))
    assert register.status_code in (201, 422)  # 422 if a prior test already registered it
    with open(HEALTHY_DET, "rb") as f:
        r = client.post(
            "/models",
            data={"name": name, "model_class": "detection", "framework": "stub", "version": "v1"},
            files={"weights": (HEALTHY_DET.name, f, "application/json")},
            headers=header,
        )
    assert r.status_code == 201, r.text
    return r.json()


def test_submitter_reads_own_but_not_others(client):
    alice = bearer("alice@example.com", ["submitter"])
    bob = bearer("bob@example.com", ["submitter"])
    mv = _submit_as(client, alice, "alice-model")

    assert client.get(f"/models/{mv['id']}", headers=alice).status_code == 200
    # bob is a valid submitter but does not own alice's model
    assert client.get(f"/models/{mv['id']}", headers=bob).status_code == 403
    assert client.get(f"/models/{mv['id']}/history", headers=bob).status_code == 403


def test_auditor_reads_any_model(client):
    alice = bearer("alice@example.com", ["submitter"])
    mv = _submit_as(client, alice, "alice-audited")
    auditor = bearer("audit@example.com", ["auditor"])
    assert client.get(f"/models/{mv['id']}", headers=auditor).status_code == 200
    assert client.get(f"/models/{mv['id']}/history", headers=auditor).status_code == 200
