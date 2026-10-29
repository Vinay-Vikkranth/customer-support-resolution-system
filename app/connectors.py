"""Read-only Zendesk connector. Imported tickets still require local verified identity mapping."""

import os
import re
import httpx


def fetch_zendesk_ticket(ticket_id: int, transport=None):
    subdomain = os.environ.get("ZENDESK_SUBDOMAIN", "")
    email = os.environ.get("ZENDESK_EMAIL", "")
    token = os.environ.get("ZENDESK_API_TOKEN", "")
    if (
        not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", subdomain)
        or not email
        or not token
    ):
        raise ValueError(
            "Configure Zendesk subdomain, email and API token on the server"
        )
    with httpx.Client(timeout=15, transport=transport) as client:
        response = client.get(
            f"https://{subdomain}.zendesk.com/api/v2/tickets/{ticket_id}.json",
            auth=(email + "/token", token),
        )
    response.raise_for_status()
    ticket = response.json()["ticket"]
    if ticket["id"] != ticket_id:
        raise ValueError("Unexpected ticket identity")
    return {
        "source": f"zendesk:{subdomain}:{ticket_id}",
        "title": str(ticket.get("subject") or "Imported support ticket")[:160],
        "body": str(ticket.get("description") or "No description provided")[:5000],
    }
