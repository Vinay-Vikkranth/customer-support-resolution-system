"""Authenticated HTTP account integration. Remote execution is idempotent and state-conditional."""

import os
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt


class Account(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    plan: str
    status: str


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    account_id: str
    name: str
    status: str
    reporting: StrictInt = Field(ge=0, le=1)


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account: Account
    member: Member
    incident: StrictBool


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    found: StrictBool
    verified: StrictBool | None = None
    account_id: str | None = None
    member_id: str | None = None
    expected: str | None = None
    key: str | None = None


def verified_operation(value, key):
    result = Operation.model_validate(value).model_dump(exclude_none=True)
    if result["found"] and (
        result.get("verified") is not True
        or result.get("key") != key
        or not all(
            result.get(field) for field in ("account_id", "member_id", "expected")
        )
    ):
        raise ValueError("Invalid account operation result")
    return result


class AccountGateway:
    def __init__(self, transport=None):
        self.url = os.environ.get("ACCOUNT_API_URL", "").rstrip("/")
        self.token = os.environ.get("ACCOUNT_API_TOKEN", "")
        self.transport = transport
        if not self.token:
            raise ValueError("ACCOUNT_API_TOKEN is required")
        parsed = urlsplit(self.url)
        if (
            parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or not (
                parsed.scheme == "https"
                or (
                    parsed.scheme == "http"
                    and parsed.hostname in ("127.0.0.1", "localhost", "account-service")
                )
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
        raw = self.request(
            "GET",
            "/v1/snapshot",
            params={"account_id": account_id, "member_id": member_id},
        )
        state = Snapshot.model_validate(raw).model_dump()
        if (
            state["account"]["id"] != account_id
            or state["member"]["id"] != member_id
            or state["member"]["account_id"] != account_id
        ):
            raise ValueError("Account API returned a different account or member")
        return state

    def lookup(self, key):
        return verified_operation(
            self.request("GET", "/v1/operation", params={"key": key}), key
        )

    def restore(self, account_id, member_id, expected, key):
        raw = self.request(
            "POST",
            "/v1/restore",
            json={
                "account_id": account_id,
                "member_id": member_id,
                "expected": expected,
                "key": key,
            },
        )
        result = verified_operation(raw, key)
        if (
            not result["found"]
            or result.get("account_id") != account_id
            or result.get("member_id") != member_id
            or result.get("expected") != expected
        ):
            raise ValueError("Account API did not verify the requested operation")
        return result
