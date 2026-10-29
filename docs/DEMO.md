# Five-minute presenter walkthrough

**Problem:** A support agent receives “my paid reporting feature stopped working.” They must check entitlement, membership, billing and service health before changing anything. A guessed fix can grant unauthorized access or hide an outage.

**What this system does:** It assembles evidence, retrieves policy references, optionally asks a model for structured analysis, and presents one bounded proposal. Human review is required. The execution service checks the current state again, applies the allowed fix once, verifies it and records the outcome.

1. **Queue:** Show searchable cases, statuses and metrics. All demonstration accounts are synthetic.
2. **Acme case:** Show disabled permission on an active Pro account. Investigate, then expand the trace and policies. Explain that no mutation has happened yet.
3. **Approval:** Read the draft and approve through the confirmation dialog. Show Resolved, enabled permission and named audit history. Copying a draft is separate from sending it.
4. **Counterexample:** Open Birch's Basic-plan request. The system escalates rather than upgrading the subscription or granting access.
5. **Reliability:** Explain stale-state rejection and the independent HTTP service's operation ledger. Run `python scripts/network_smoke.py` to demonstrate the network path; tests also simulate a lost response after remote commit.
6. **Evaluation:** Show `evals/report.json`: 12 labeled developer-authored scenarios, 96 policy combinations and retrieval against a fixed-order baseline. Explain the limits of synthetic evidence.

## What to say in an interview

“I built an end-to-end support resolution application with structured AI analysis, policy retrieval, reviewer approvals and verified account actions. I implemented a separate HTTP account service with conditional writes and idempotent recovery, a read-only Zendesk adapter, named-user authentication, evaluation fixtures and automated browser tests. The demo uses synthetic accounts; live customer impact has not been measured.”

Do not claim autonomous unrestricted repair, production customer deployment, live Zendesk validation, measured time savings or real-world AI accuracy. Model analysis is optional and requires an API account; local mode demonstrates the workflow without paid calls.
