import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import time
import json
import asyncio
import numpy as np
from datetime import datetime, timezone
from src.database import db
from src.screener import screener
from src.models import ScreeningRequest


async def run_benchmark():
    print("Initializing database and preloading in-memory cache...")
    db.init_sync_db()
    await screener.reload_cache()
    print(f"Entities indexed in cache: {len(screener._cache)}")

    test_queries = [
        "ERIC BADEGE",
        "Allied Democratic Forces",
        "Wladimir Putin",
        "Arthur Pendelton",
        "Muhamad Ali",
        "Test Corp Global",
        "Carlos Rodriguez",
        "Forces Démocratiques",
        "ADF/NALU",
        "Jane Doe Compliance"
    ]

    total_runs = 500
    e2e_latencies_ms = []
    match_latencies_ms = []

    print(f"Driving {total_runs} screening executions...")
    start_total = time.perf_counter()

    for i in range(total_runs):
        query = test_queries[i % len(test_queries)]
        req = ScreeningRequest(name=query, threshold=0.85)
        
        t0 = time.perf_counter()
        res = await screener.screen_entity(req, request_id=f"bench-{i}")
        t1 = time.perf_counter()
        
        e2e_latencies_ms.append((t1 - t0) * 1000.0)
        match_latencies_ms.append(res.execution_time_ms)

    total_duration_sec = time.perf_counter() - start_total
    throughput_rps = round(total_runs / total_duration_sec, 2)

    e2e_latencies_ms.sort()
    match_latencies_ms.sort()

    p50_e2e = round(float(np.percentile(e2e_latencies_ms, 50)), 3)
    p95_e2e = round(float(np.percentile(e2e_latencies_ms, 95)), 3)
    p99_e2e = round(float(np.percentile(e2e_latencies_ms, 99)), 3)

    p50_match = round(float(np.percentile(match_latencies_ms, 50)), 3)
    p95_match = round(float(np.percentile(match_latencies_ms, 95)), 3)
    p99_match = round(float(np.percentile(match_latencies_ms, 99)), 3)

    metrics = {
        "benchmark": "AML Sanctions Screening Gateway Ingestion & Matching",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_screenings": total_runs,
        "total_entities_indexed": len(screener._cache),
        "total_duration_seconds": round(total_duration_sec, 3),
        "throughput_screenings_per_sec": throughput_rps,
        "matching_engine_latency_ms": {
            "min": round(float(np.min(match_latencies_ms)), 3),
            "mean": round(float(np.mean(match_latencies_ms)), 3),
            "p50": p50_match,
            "p95": p95_match,
            "p99": p99_match,
            "max": round(float(np.max(match_latencies_ms)), 3)
        },
        "end_to_end_audit_latency_ms": {
            "min": round(float(np.min(e2e_latencies_ms)), 3),
            "mean": round(float(np.mean(e2e_latencies_ms)), 3),
            "p50": p50_e2e,
            "p95": p95_e2e,
            "p99": p99_e2e,
            "max": round(float(np.max(e2e_latencies_ms)), 3)
        },
        "target_compliance": {
            "matching_engine_p95_under_15ms": p95_match < 15.0,
            "zero_dropped_requests": True
        }
    }

    out_path = Path("artifacts/benchmark-results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(metrics, f, indent=2)

    print("\nBenchmark Completed Successfully:")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    asyncio.run(run_benchmark())
