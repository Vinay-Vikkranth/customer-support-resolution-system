"""Fixed labeled scenarios + retrieval baseline. No paid model calls are made."""

import json
import statistics
import time
from pathlib import Path
from app.engine import decide, retrieve, POLICIES
from evaluate import evaluate

cases = json.loads(
    (Path(__file__).parent / "cases.json").read_text(encoding="utf-8-sig")
)
results = []
for case in cases:
    start = time.perf_counter()
    account = {"id": "a", "plan": case["plan"], "status": case["billing"]}
    member = {"account_id": "a", "status": case["member"], "reporting": case["enabled"]}
    action, _, _ = decide(account, member, case["feature"], case["incident"])
    retrieved = [p["id"] for p in retrieve(case["query"])]
    results.append(
        {
            "id": case["id"],
            "expected": case["action"],
            "actual": action,
            "correct": action == case["action"],
            "retrieval_hit_at_3": case["policy"] in retrieved,
            "baseline_hit_at_3": case["policy"] in [p["id"] for p in POLICIES[:3]],
            "retrieved": retrieved,
            "latency_ms": round((time.perf_counter() - start) * 1000, 3),
        }
    )
report = {
    "fixture_count": len(cases),
    "action_accuracy": sum(r["correct"] for r in results) / len(results),
    "retrieval_hit_at_3": sum(r["retrieval_hit_at_3"] for r in results) / len(results),
    "fixed_order_baseline_hit_at_3": sum(r["baseline_hit_at_3"] for r in results)
    / len(results),
    "median_local_latency_ms": round(
        statistics.median(r["latency_ms"] for r in results), 3
    ),
    "policy_matrix": evaluate(),
    "results": results,
    "limitations": "Small developer-authored synthetic fixtures, not a held-out customer benchmark. Local mode only; no LLM quality, cloud latency, or business impact claim.",
}
output = Path(__file__).parent / "report.json"
output.write_text(json.dumps(report, indent=2))
print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
raise SystemExit(0 if all(r["correct"] for r in results) else 1)
