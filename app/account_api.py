"""Authenticated HTTP account integration. Remote execution is idempotent and state-conditional."""

import os
import httpx


class AccountGateway:
    def __init__(self, transport=None):
        self.url = os.environ.get("ACCOUNT_API_URL", "").rstrip("/")
        self.token = os.environ.get("ACCOUNT_API_TOKEN", "")
        self.transport = transport
        if not self.token:
            raise ValueError("ACCOUNT_API_TOKEN is required")
        if not self.url.startswith(
            (
                "https://",
                "http://127.0.0.1:",
                "http://localhost:",
                "http://account-service:",
            )
        ):
            raise ValueError(
                "Account API must use HTTPS, loopback, or the private compose service"
            )

    def request(self, method, path, **kwargs):
        with httpx.Client(
            timeout=httpx.Timeout(10, connect=3), transport=self.transport
        ) as client:
            response = client.request(
                method,
                self.url + path,
                headers={"Authorization": "Bearer " + self.token},
                **kwargs,
            )
        response.raise_for_status()
        return response.json()

    def snapshot(self, account_id, member_id):
        return self.request(
            "GET",
            "/v1/snapshot",
            params={"account_id": account_id, "member_id": member_id},
        )

    def lookup(self, key):
        return self.request("GET", "/v1/operation", params={"key": key})

    def restore(self, account_id, member_id, expected, key):
        return self.request(
            "POST",
            "/v1/restore",
            json={
                "account_id": account_id,
                "member_id": member_id,
                "expected": expected,
                "key": key,
            },
        )
