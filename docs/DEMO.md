# Understand and demonstrate ResolveDesk

## What problem are we solving?

A customer says: **“I pay for reporting, but cannot open my reports.”** A support representative must check the customer's subscription, billing status, account membership, permission settings and service health before changing access. Guessing can grant access to the wrong person or hide an outage.

ResolveDesk brings those checks into one workspace. It explains the evidence, proposes a supported next step, asks a reviewer to approve, performs the allowed change, verifies the result and records the decision. The demonstration uses synthetic customers.

## How the pieces work together

| Piece | Plain-language purpose |
|---|---|
| Browser workspace | Where a support representative reads cases, investigates, writes notes and reviews actions. |
| FastAPI backend | Receives requests, checks identity/role and coordinates the workflow. |
| SQLite database | Remembers cases, users, proposals, notes and audit history between launches. |
| Policy retrieval | BM25 ranks relevant text from five versioned policies; required authorization references are added separately. |
| Optional AI analyzer | Uses the evidence to produce a structured diagnosis, citations, reply draft and next steps. A key is required for live calls. |
| Deterministic policy gate | Enforces the allowed action independently of model output. Invalid or conflicting output falls back safely. |
| Reviewer approval | A person accepts or rejects the proposal. The server checks that the evidence has not changed. |
| Account service | Applies the allowed permission change and verifies it. Optional HTTP mode uses a separate service/database. |
| Audit and tests | Make decisions inspectable and check success, refusal and recovery cases. |

The AI is a **bounded analyzer**, not a free-running agent choosing arbitrary tools. Default local mode works without a model. The trace shows evidence-collection stages; it should not be described as autonomous tool selection. Reply drafts are not sent automatically.

## Five-minute demonstration

1. **Open the workspace.** Start the local application first, then open its URL. `127.0.0.1` means this computer; the address works only while the local server runs. Show the searchable queue and case statuses.
2. **Investigate Acme / Alex.** The active Pro account is entitled to reporting, but permission is disabled. Expand the trace and policies. Show that investigation alone has not changed access.
3. **Approve and verify.** Review the proposal and confirmation dialog. Show the enabled permission, Resolved status and audit entry.
4. **Show a refusal.** Investigate Birch / Sam on the Basic plan. The system escalates instead of upgrading billing or granting access.
5. **Show a failure boundary.** Investigate an eligible case, then activate an incident before approval. The changed evidence blocks the old proposal. Re-investigate to obtain a current recommendation.
6. **Explain network recovery.** If the remote service commits a change but its response is lost, retry the same approval. Its operation ID retrieves the stored result rather than applying a duplicate change. `python scripts/network_smoke.py` demonstrates the network path; automated tests simulate lost responses.

For a repeat demo, create an appropriate new case or reopen with a reason. Already-enabled reporting is escalated for further diagnosis; it is not counted as a second successful repair.

## How this supports forward-deployed engineering

| FDE skill | Evidence in this project | What remains to demonstrate |
|---|---|---|
| Translate a business problem into software | A bounded support workflow with explicit approval and escalation rules | Actual customer discovery and feedback |
| Deliver across frontend/backend | Responsive case workspace, API and persistent storage | Vinay personally explaining and modifying the implementation |
| Integrate customer systems | Authenticated HTTP account API and Zendesk intake adapter | Real customer credentials and integration validation |
| Make systems reliable | State rechecks, verification, operation IDs and recovery | Operational evidence under realistic load |
| Evaluate and hand over | Tests, synthetic scenarios, CI, containers and runbook | Live-model quality evaluation, adoption and measurable customer outcomes |

Current official role benchmarks, reviewed October 28, 2026:

- [OpenAI FDE, San Francisco](https://openai.com/careers/forward-deployed-engineer-%28fde%29-sf-san-francisco/) emphasizes discovery, full-stack delivery, production rollout, adoption and evaluation feedback. It asks for 5+ years including customer-facing experience; this project does not replace that requirement.
- [Palantir New Grad FDE, Commercial](https://jobs.lever.co/palantir/2e6b0ac8-83e9-4be5-a3aa-cf319f751728) emphasizes customer ownership, custom applications and integration. This exact listing requires December 2026 or Spring 2027 graduation, which differs from Vinay's October 2026 graduation; it is a skills benchmark, not a confirmed eligible opening.
- [Anthropic Staff FDE, US](https://job-boards.greenhouse.io/anthropic/jobs/5449229008) emphasizes enterprise architecture, customer leadership, production ownership and systems customers can operate. It is a senior benchmark; a portfolio project does not establish staff-level experience.

**Assessment:** ResolveDesk is relevant evidence for early-career FDE applications. It becomes more persuasive when Vinay can demonstrate the decisions, debug a failure, and incorporate genuine support-user feedback. It does not yet prove production customer impact or live AI quality.

## Learn it in this order

- [ ] Explain the customer problem without naming technologies.
- [ ] Run the normal and refusal cases yourself; explain why each outcome is correct.
- [ ] Trace one request from `web/app.js` through `app/main.py`, `app/engine.py` and the account service.
- [ ] Explain why AI cannot override the policy gate and why a stale approval is blocked.
- [ ] Explain an operation ID and the lost-response recovery scenario in your own words.
- [ ] Make one small improvement, add a meaningful regression test and explain the diff.
- [ ] Ask a support practitioner to try three scenarios; record feedback and implement one resulting change.
- [ ] Before claiming AI quality, test a live model on separate labeled cases and report errors, citations, latency and tokens honestly.

## Resume wording after reviewing and understanding the implementation

- Built ResolveDesk, an AI-assisted support workflow using Python, FastAPI, SQLite and JavaScript, combining policy retrieval, structured analysis, reviewer approvals and verified reporting-access remediation.
- Implemented authenticated HTTP integration, state-conditional actions and idempotent recovery; validated the synthetic workflow with automated API/browser tests and container checks in GitHub Actions.

Present it as an AI-assisted personal portfolio project and be prepared to explain how the implementation was reviewed and tested. Use only the final verified test counts if adding metrics. Do not claim production customer deployment, live Zendesk validation, reduced support time, autonomous unrestricted repair or real-world AI accuracy. Software checks and developer-authored synthetic scenarios do not establish those outcomes.
