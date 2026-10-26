import csv
import json
import math
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home() / "fabric-project/solar-billing-audit-fabric"
NETWORK = Path.home() / "fabric-project/fabric-samples/test-network"
PEER = Path.home() / "fabric-project/fabric-samples/bin/peer"
DATASET = ROOT / "dataset/sampleBills_10000.json"
CSV_OUT = ROOT / "benchmark/read_results_10000_bills.csv"
JSON_OUT = ROOT / "test-reports/solarbill_read_benchmark_10000_bills.json"
REPEATS = 3
EXPECTED_BILLS = 10000


def p95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


def query(function, bill_id):
    command = [
        "bash", "-c",
        'source scripts/envVar.sh >/dev/null 2>&1 && '
        'setGlobals 1 >/dev/null 2>&1 && '
        'export FABRIC_CFG_PATH="$HOME/fabric-project/fabric-samples/config" && '
        'exec "$@"',
        "_", str(PEER),
        "chaincode", "query",
        "-C", "mychannel",
        "-n", "solarbill",
        "-c", json.dumps({
            "function": function,
            "Args": [str(bill_id)]
        })
    ]

    start = time.perf_counter_ns()
    try:
        result = subprocess.run(
            command, cwd=NETWORK, capture_output=True,
            text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        elapsed = (time.perf_counter_ns() - start) / 1_000_000
        return elapsed, False, "", "Query timed out after 60 seconds"

    elapsed = (time.perf_counter_ns() - start) / 1_000_000

    if result.returncode:
        return elapsed, False, "", result.stderr.strip()

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return elapsed, False, result.stdout.strip(), "Invalid JSON response"

    return elapsed, True, json.dumps(payload), ""


def main():
    # Never overwrite previous benchmark results.
    if CSV_OUT.exists() or JSON_OUT.exists():
        raise SystemExit(
            "Output file already exists. Nothing was overwritten:\n"
            f"{CSV_OUT}\n{JSON_OUT}"
        )

    bills = json.loads(DATASET.read_text())
    if len(bills) != EXPECTED_BILLS:
        raise SystemExit(
            f"Expected exactly {EXPECTED_BILLS} bills; found {len(bills)}"
        )

    ids = [str(b["billId"]) for b in bills]
    if len(set(ids)) != EXPECTED_BILLS:
        raise SystemExit("Dataset contains duplicate bill IDs; stopping.")

    # Test both functions before starting the long benchmark.
    for function in ("ReadBill", "VerifyBill"):
        elapsed, ok, response, error = query(function, ids[0])
        if not ok:
            raise SystemExit(
                f"{function} preflight failed for {ids[0]}: {error}"
            )
        print(
            f"Preflight {function}: PASS ({elapsed:.1f} ms)",
            flush=True
        )

    rows = []
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()

    total = EXPECTED_BILLS * 2 * REPEATS
    print(f"Starting benchmark: {total:,} measured queries", flush=True)

    for i, bill in enumerate(bills, 1):
        for function in ("ReadBill", "VerifyBill"):
            for run in range(1, REPEATS + 1):
                elapsed, ok, response, error = query(
                    function, bill["billId"]
                )
                rows.append({
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "function": function,
                    "bill_id": str(bill["billId"]),
                    "run": run,
                    "command_duration_ms": round(elapsed, 3),
                    "success": ok,
                    "response": response,
                    "error": error
                })

        if i % 100 == 0:
            elapsed = time.monotonic() - started
            print(
                f"Completed {i:,}/{EXPECTED_BILLS} bills; "
                f"{len(rows):,}/{total:,} queries; "
                f"elapsed {elapsed / 60:.1f} min",
                flush=True
            )

    # Write the raw results only after the complete run.
    with CSV_OUT.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "started_at_utc": started_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_file": str(DATASET),
        "dataset_bills_tested": len(bills),
        "repeats_per_function_per_bill": REPEATS,
        "ledger_size_during_test": 10006,
        "total_measured_queries": total,
        "measurement": (
            "CLI-observed query latency including process startup; "
            "individual ReadBill and VerifyBill calls"
        ),
        "results": {}
    }

    for function in ("ReadBill", "VerifyBill"):
        group = [r for r in rows if r["function"] == function]
        successful = [
            r["command_duration_ms"] for r in group if r["success"]
        ]
        failed = len(group) - len(successful)

        summary["results"][function] = {
            "total_calls": len(group),
            "successful_calls": len(successful),
            "failed_calls": failed,
            "failure_rate_percent": round(
                100 * failed / len(group), 2
            ),
            "mean_ms": round(statistics.mean(successful), 3)
                if successful else None,
            "median_ms": round(statistics.median(successful), 3)
                if successful else None,
            "p95_ms": round(p95(successful), 3)
                if successful else None,
            "throughput_successful_calls_per_second": round(
                1000 / statistics.mean(successful), 3
            ) if successful else None
        }

    # Exclusive creation prevents overwriting an existing report.
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with JSON_OUT.open("x", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    print("\n=== 10,000-BILL QUERY BENCHMARK ===")
    print(json.dumps(summary, indent=2))
    print("CSV:", CSV_OUT)
    print("JSON:", JSON_OUT)


if __name__ == "__main__":
    main()
