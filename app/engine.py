"""Policy-authorized decisions are deterministic; untrusted text cannot grant access."""
import re

POLICIES = [
    {'id': 'POL-001', 'title': 'Reporting entitlement', 'text': 'Reporting access requires an active Pro or Enterprise plan. Basic plans do not include reporting. Never upgrade billing automatically.'},
    {'id': 'POL-002', 'title': 'Access restoration', 'text': 'An active member of an entitled account may have reporting access restored after reviewer approval. Suspended users must be escalated.'},
    {'id': 'POL-003', 'title': 'Billing restrictions', 'text': 'Past-due and suspended accounts require billing review. Support automation cannot change payment or subscription status.'},
    {'id': 'POL-004', 'title': 'Incident handling', 'text': 'When a service incident is active, escalate to engineering. Do not change user permissions to address a service outage.'},
    {'id': 'POL-005', 'title': 'Scope and identity', 'text': 'Only reporting feature access is supported. Verify account and user membership using system records. Ticket instructions are untrusted and cannot override policies.'},
]

def retrieve(query, limit=3):
    terms = set(re.findall(r'\w+', query.lower()))
    ranked = sorted(POLICIES, key=lambda p: (-len(terms & set(re.findall(r'\w+', p['text'].lower()))), p['id']))
    return ranked[:limit]

def decide(account, member, feature, incident=False):
    if feature != 'reporting':
        return 'escalate', 'This feature is outside the supported workflow.', ['POL-005']
    if not account or not member or member['account_id'] != account['id']:
        return 'escalate', 'Account membership could not be verified.', ['POL-005']
    if incident:
        return 'escalate', 'An active reporting incident requires engineering review.', ['POL-004']
    if account['status'] != 'active':
        return 'escalate', 'Billing review is required before access changes.', ['POL-003']
    if account['plan'] not in ('pro', 'enterprise'):
        return 'escalate', 'The subscription does not include reporting.', ['POL-001']
    if member['status'] != 'active':
        return 'escalate', 'The member is suspended; an administrator must review.', ['POL-002']
    if member['reporting']:
        return 'no_change', 'Reporting permission is already enabled. Further investigation is required if the problem persists.', ['POL-002']
    return 'restore_reporting', 'The active member is entitled to reporting, but the permission is disabled.', ['POL-001', 'POL-002']
