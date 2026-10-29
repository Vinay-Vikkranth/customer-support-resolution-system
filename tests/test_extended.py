import json
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import app, db
from app.security import create_user, password_matches
from app.intelligence import analyze
from app.connectors import fetch_zendesk_ticket
from app.engine import retrieve

client = TestClient(app)
OP = {"Authorization": "Bearer test-operator"}
RV = {"Authorization": "Bearer test-reviewer"}
STATE = {
    "account": {"id": "acme", "plan": "pro", "status": "active"},
    "member": {"id": "alex", "account_id": "acme", "status": "active", "reporting": 0},
    "incident": False,
}
TICKET = {
    "title": "Reports unavailable",
    "body": "My active Pro account cannot open reports",
    "feature": "reporting",
}


def case():
    with db() as c:
        c.execute("UPDATE members SET reporting=0 WHERE id='alex'")
        c.execute("UPDATE settings SET value='false' WHERE key='incident'")
    return client.post(
        "/api/tickets",
        headers=OP,
        json={**TICKET, "account_id": "acme", "member_id": "alex"},
    ).json()["id"]


def test_named_auth_revocation_and_audit():
    with db() as c:
        create_user(c, "casey", "Casey Reviewer", "reviewer", "test-password-long")
        saved = c.execute(
            "SELECT password FROM users WHERE username='casey'"
        ).fetchone()[0]
        assert saved != "test-password-long" and password_matches(
            "test-password-long", saved
        )
    result = client.post(
        "/api/auth/login", json={"username": "casey", "password": "test-password-long"}
    )
    assert result.status_code == 200
    headers = {"Authorization": "Bearer " + result.json()["token"]}
    assert (
        client.get("/api/bootstrap", headers=headers).json()["name"] == "Casey Reviewer"
    )
    tid = case()
    client.post(
        f"/api/tickets/{tid}/notes",
        headers=headers,
        json={"body": "Reviewed the customer context."},
    )
    assert (
        client.get(f"/api/tickets/{tid}", headers=headers).json()["notes"][0]["actor"]
        == "casey"
    )
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/tickets", headers=headers).status_code == 401


def test_login_rate_limit():
    for _ in range(10):
        assert (
            client.post(
                "/api/auth/login", json={"username": "unknown", "password": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/login", json={"username": "unknown", "password": "wrong"}
        ).status_code
        == 429
    )
    with db() as c:
        c.execute("DELETE FROM login_attempts")


def test_session_expiry():
    with db() as c:
        create_user(c, "expiry", "Expiry", "operator", "password-for-expiry")
    token = client.post(
        "/api/auth/login",
        json={"username": "expiry", "password": "password-for-expiry"},
    ).json()["token"]
    with db() as c:
        c.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    assert (
        client.get(
            "/api/tickets", headers={"Authorization": "Bearer " + token}
        ).status_code
        == 401
    )


def test_close_reopen_and_superseded_proposal():
    tid = case()
    run = client.post(f"/api/tickets/{tid}/investigate", headers=OP).json()
    assert (
        client.patch(
            f"/api/tickets/{tid}",
            headers=OP,
            json={"status": "closed", "reason": "Handled elsewhere"},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/tickets/{tid}",
            headers=RV,
            json={"status": "closed", "reason": "Handled elsewhere"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/investigations/{run['id']}/decision",
            headers=RV,
            json={"decision": "approve"},
        ).status_code
        == 409
    )
    assert client.post(f"/api/tickets/{tid}/investigate", headers=OP).status_code == 409
    client.patch(
        f"/api/tickets/{tid}",
        headers=RV,
        json={"status": "open", "reason": "Customer reports recurrence"},
    )
    assert client.post(f"/api/tickets/{tid}/investigate", headers=OP).status_code == 200


def test_conflicting_replay():
    tid = case()
    run = client.post(f"/api/tickets/{tid}/investigate", headers=OP).json()
    url = f"/api/investigations/{run['id']}/decision"
    assert client.post(url, headers=RV, json={"decision": "reject"}).status_code == 200
    assert client.post(url, headers=RV, json={"decision": "approve"}).status_code == 409


def test_export_formula_safety_and_permissions():
    client.post(
        "/api/tickets",
        headers=OP,
        json={
            **TICKET,
            "title": '=HYPERLINK("evil")',
            "account_id": "acme",
            "member_id": "alex",
        },
    )
    assert client.get("/api/export").status_code == 401
    output = client.get("/api/export", headers=OP)
    assert "'=HYPERLINK" in output.text
    assert client.get("/api/operations", headers=OP).status_code == 403
    assert client.get("/api/operations", headers=RV).json()["cost_usd"] is None


def model_payload(action="restore_reporting", citations=None):
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "diagnosis": "Active Pro membership with disabled permission.",
                            "proposed_action": action,
                            "policy_ids": citations or ["POL-001", "POL-002"],
                            "customer_reply": "We identified disabled reporting access. A reviewer will verify the proposed change.",
                            "next_steps": ["Request reviewer approval."],
                        }
                    )
                }
            }
        ],
        "usage": {"prompt_tokens": 350, "completion_tokens": 100},
    }


def test_structured_model_and_token_accounting(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")

    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"]["json_schema"]["strict"] is True
        return httpx.Response(200, json=model_payload())

    result = analyze(TICKET, STATE, httpx.MockTransport(handler))
    assert result["model_status"] == "openai_structured"
    assert result["usage"]["input_tokens"] == 350
    assert result["trace"][-1]["tool"] == "policy.authorize"


@pytest.mark.parametrize(
    "payload",
    [model_payload("escalate"), model_payload(citations=["FAKE-999"]), {"choices": []}],
)
def test_invalid_model_cannot_override_policy(monkeypatch, payload):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    result = analyze(
        TICKET, STATE, httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    assert result["model_status"] == "safe_fallback"
    assert result["action"] == "restore_reporting"


def test_provider_failure_safe_fallback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-test-key")
    result = analyze(
        TICKET,
        STATE,
        httpx.MockTransport(
            lambda _: httpx.Response(429, json={"error": "rate limited"})
        ),
    )
    assert result["model_status"] == "safe_fallback"


def test_retrieval():
    assert retrieve("past due payment billing restrictions", 1)[0]["id"] == "POL-003"
    assert retrieve("service outage incident engineering", 1)[0]["id"] == "POL-004"
    assert retrieve("zxqvwj") == []


def test_zendesk_adapter_contract(monkeypatch):
    for key, value in [
        ("ZENDESK_SUBDOMAIN", "example"),
        ("ZENDESK_EMAIL", "agent@example.com"),
        ("ZENDESK_API_TOKEN", "fake"),
    ]:
        monkeypatch.setenv(key, value)

    def handler(request):
        assert str(request.url) == "https://example.zendesk.com/api/v2/tickets/42.json"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(
            200,
            json={
                "ticket": {
                    "id": 42,
                    "subject": "Cannot see reports",
                    "description": "Please investigate this issue.",
                }
            },
        )

    result = fetch_zendesk_ticket(42, httpx.MockTransport(handler))
    assert result["source"] == "zendesk:example:42"


def test_zendesk_import_is_idempotent(monkeypatch):
    monkeypatch.setattr(
        "app.main.fetch_zendesk_ticket",
        lambda _: {
            "source": "zendesk:test:7",
            "title": "External case",
            "body": "Reports are unavailable.",
        },
    )
    body = {"ticket_id": 7, "account_id": "acme", "member_id": "alex"}
    assert (
        client.post(
            "/api/integrations/zendesk/import", headers=OP, json=body
        ).status_code
        == 403
    )
    first = client.post(
        "/api/integrations/zendesk/import", headers=RV, json=body
    ).json()
    second = client.post(
        "/api/integrations/zendesk/import", headers=RV, json=body
    ).json()
    assert first["id"] == second["id"] and second["replayed"]


def test_request_limits():
    assert (
        client.post("/api/tickets", headers=OP, content="x" * 66000).status_code == 413
    )
