import os
import tempfile
import httpx
from fastapi.testclient import TestClient

os.environ["ACCOUNT_API_TOKEN"] = "test-account-service-token"
os.environ["ACCOUNT_DB"] = tempfile.mktemp(suffix=".db")
from app.account_service import app as service, database, fingerprint
from app.main import app

remote = TestClient(service)
client = TestClient(app)
AUTH = {"Authorization": "Bearer test-account-service-token"}
OP = {"Authorization": "Bearer test-operator"}
RV = {"Authorization": "Bearer test-reviewer"}


def reset():
    with database() as c:
        c.execute("UPDATE members SET reporting=0 WHERE id='alex'")


def test_remote_transaction_and_replay():
    reset()
    assert (
        remote.get(
            "/v1/snapshot", params={"account_id": "acme", "member_id": "alex"}
        ).status_code
        == 401
    )
    state = remote.get(
        "/v1/snapshot", params={"account_id": "acme", "member_id": "alex"}, headers=AUTH
    ).json()
    body = {
        "account_id": "acme",
        "member_id": "alex",
        "expected": fingerprint(state),
        "key": "test-operation-one",
    }
    first = remote.post("/v1/restore", headers=AUTH, json=body)
    assert first.json()["verified"]
    assert remote.post("/v1/restore", headers=AUTH, json=body).json() == first.json()
    assert (
        remote.post(
            "/v1/restore", headers=AUTH, json={**body, "member_id": "jules"}
        ).status_code
        == 409
    )


def test_remote_stale_state():
    reset()
    body = {
        "account_id": "acme",
        "member_id": "alex",
        "expected": "0" * 64,
        "key": "test-operation-stale",
    }
    assert remote.post("/v1/restore", headers=AUTH, json=body).status_code == 409


def test_lost_response_reconciliation(monkeypatch):
    reset()
    monkeypatch.setenv("ACCOUNT_API_URL", "http://localhost:8001")

    class Gateway:
        def snapshot(self, account_id, member_id):
            return remote.get(
                "/v1/snapshot",
                headers=AUTH,
                params={"account_id": account_id, "member_id": member_id},
            ).json()

        def lookup(self, key):
            return remote.get("/v1/operation", headers=AUTH, params={"key": key}).json()

        def restore(self, account_id, member_id, expected, key):
            response = remote.post(
                "/v1/restore", headers=AUTH, json=locals_without_self(locals())
            )
            assert response.status_code == 200
            raise httpx.ReadTimeout("Simulated lost response after commit")

    monkeypatch.setattr("app.main.AccountGateway", Gateway)
    tid = client.post(
        "/api/tickets",
        headers=OP,
        json={
            "title": "Network recovery",
            "body": "Cannot open reports",
            "account_id": "acme",
            "member_id": "alex",
        },
    ).json()["id"]
    run = client.post(f"/api/tickets/{tid}/investigate", headers=OP).json()
    url = f"/api/investigations/{run['id']}/decision"
    assert client.post(url, headers=RV, json={"decision": "approve"}).status_code == 503
    assert client.post(f"/api/tickets/{tid}/investigate", headers=OP).status_code == 409
    assert (
        client.patch(
            f"/api/tickets/{tid}",
            headers=RV,
            json={"status": "closed", "reason": "Cannot bypass reconciliation"},
        ).status_code
        == 409
    )
    result = client.post(url, headers=RV, json={"decision": "approve"})
    assert result.json()["reconciled"] and result.json()["verified"]
    assert (
        client.get(f"/api/tickets/{tid}", headers=OP).json()["ticket"]["status"]
        == "resolved"
    )


def locals_without_self(values):
    return {
        k: v
        for k, v in values.items()
        if k in ("account_id", "member_id", "expected", "key")
    }
