# ResolveDesk

![ResolveDesk investigation dashboard](docs-dashboard.png)

An approval-controlled support system: investigate a SaaS reporting-access incident, inspect account and policy evidence, approve a proposed fix, execute it once, and verify the resulting permission.

**Status:** self-contained portfolio pilot with synthetic customers. Not a deployed customer product. Default investigation uses deterministic policies and lexical retrieval. Optional LLM drafting is advisory and cannot authorize actions.

## Run

Python 3.12 recommended.

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open http://127.0.0.1:8000. The launcher prints separate operator and reviewer tokens. Connect as operator to create/investigate tickets; disconnect and connect as reviewer to approve/reject. Credentials stay in browser memory. Restarting rotates tokens unless environment variables are set. On the original development machine run.py also detects the ignored `.deps` directory.

## Demo

1. Investigate Acme's reporting ticket. Its active Pro member has a disabled permission.
2. Inspect account evidence, policy citations and the proposed restore action. No permission changes yet.
3. Connect as reviewer and approve. Permission update, verification, ticket resolution and audit insertion commit atomically.
4. Investigate Birch's Basic-plan request. It escalates without granting access or modifying billing.
5. Create an eligible request, investigate, then toggle the service-incident control. Approving the old proposal is blocked until re-investigation.

## Implemented

- Responsive ticket queue, creation form, account context, policy library and audit timeline.
- Server-side operator/reviewer authorization; persistent SQLite accounts, members, tickets and investigations.
- Reporting permission restoration; unsupported features, suspended members, inactive accounts and outages escalate.
- Lexical policy retrieval plus mandatory decision-policy citations.
- State fingerprint validation, superseded-proposal rejection, atomic execution and idempotent approvals.
- Optional OpenAI drafting with bounded timeout and transparent fallback.
- Status/latency metrics, `/health`, interactive API documentation at `/docs`.
- API tests, synthetic policy evaluation, Dockerfile and GitHub Actions.

## Optional LLM

Set `OPENAI_API_KEY` and optionally `OPENAI_MODEL` (default `gpt-4.1-mini`) in the process environment. Never commit credentials. Only the verified finding and synthetic policies are sent, not raw tickets or account records. Provider availability/pricing depend on your account. No key produces `rules_only`; failures produce `llm_unavailable_fallback`. All drafts need review; no messages are sent.

The LLM rewrites established findings. It does not diagnose or authorize changes. A future planner experiment can be compared against this deterministic baseline without weakening the action gate.

## Architecture

Dashboard → FastAPI role authorization → account/ticket SQLite adapter → policy investigator → optional LLM draft → persisted proposal → human reviewer → state/policy recheck → atomic action, verification and audit.

The account adapter is an in-process sandbox integration, not a live Salesforce/Zendesk service. This makes the initial system reproducible without external credentials.

## Validation

```sh
python -m pytest -q
python evaluate.py
```

Tests cover authentication, role separation, approval, duplicate execution, stale state, superseded proposals, rejection, account mismatch and malicious ticket instructions. The evaluation checks 96 synthetic authorization combinations. This demonstrates policy consistency, not real ticket understanding, retrieval accuracy, LLM quality or measured time savings.

## Container

```sh
docker build -t resolvedesk .
docker run --rm -p 127.0.0.1:8000:8000 --env-file .env -v resolvedesk-data:/app/data resolvedesk
```

Copy `.env.example` to `.env` and replace both tokens with different random secrets. The image uses a non-root user. Docker configuration is provided; successful container execution is not claimed until tested. Add HTTPS and an identity-aware proxy before remote access.

## Operations and boundaries

- Persistent database: `data/resolvedesk.db`. Use SQLite backup APIs while running, or copy it after stopping the server.
- To reset synthetic data, stop the server and remove its database/WAL/SHM files. Do not reset data you need.
- Re-investigate stale proposals. LLM outages fall back. Database exceptions roll back mutations.
- Shared role tokens are single-workspace demo credentials. Real deployment needs individual SSO, tenant isolation, rate limiting, managed secrets, external integrations and durable operational telemetry.
- Audit events are application-append-only, not tamper-proof against database administrators.
- Enabled permission alone does not prove resolution: `no_change` escalates for further investigation.
- No real customer deployment, paid model invocation, production load testing or business impact is claimed.

## FDE evidence

| Requirement | Evidence |
|---|---|
| Customer workflow | Entitlement incident through reviewed resolution |
| Full-stack delivery | Dashboard and documented API |
| Integration | Account, membership and ticket data adapters |
| AI boundaries | Retrieved evidence and optional grounded drafting |
| Reliability | Transactions, stale checks, idempotency and fallback |
| Evaluation | API failure cases and synthetic policy matrix |
| Handover | Run/deployment instructions and explicit limitations |

Next validation: a support-practitioner usability session and an independently authored ticket evaluation set.
