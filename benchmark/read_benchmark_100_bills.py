import csv, json, math, statistics, subprocess, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path.home() / "fabric-project/solar-billing-audit-fabric"
NETWORK = Path.home() / "fabric-project/fabric-samples/test-network"
DATASET = ROOT / "dataset/sampleBills_100.json"
CSV_OUT = ROOT / "benchmark/read_results_100_bills.csv"
JSON_OUT = ROOT / "test-reports/solarbill_read_benchmark_100_bills.json"
REPEATS = 3

def p95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]

def query(function, bill_id):
    cmd = [
        "peer", "chaincode", "query", "-C", "mychannel",
        "-n", "solarbill", "-c",
        json.dumps({"function": function, "Args": [str(bill_id)]})
    ]
    start = time.perf_counter_ns()
    result = subprocess.run(
        cmd, cwd=NETWORK, capture_output=True, text=True, timeout=60
    )
    elapsed = (time.perf_counter_ns() - start) / 1_000_000
    if result.returncode:
        return elapsed, False, "", result.stderr.strip()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return elapsed, False, result.stdout.strip(), "Invalid JSON"
    return elapsed, True, json.dumps(payload), ""

def main():
    bills = json.loads(DATASET.read_text())
    if len(bills) < 100:
        raise SystemExit(f"Expected at least 100 bills, found {len(bills)}")
    bills = bills[:100]
    rows = []

    for function in ("ReadBill", "VerifyBill"):
        elapsed, ok, _, error = query(function, bills[0]["billId"])
        if not ok:
            raise SystemExit(f"{function} warm-up failed: {error}")

    for i, bill in enumerate(bills, 1):
        for function in ("ReadBill", "VerifyBill"):
            for run in range(1, REPEATS + 1):
                elapsed, ok, response, error = query(function, bill["billId"])
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
        if i % 10 == 0:
            print(f"Completed {i}/100 bills", flush=True)

    with CSV_OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "dataset_bills_tested": 100,
        "repeats_per_function_per_bill": REPEATS,
        "ledger_size_during_test": 1006,
        "measurement": "CLI-observed query latency including process startup",
        "results": {}
    }

    for function in ("ReadBill", "VerifyBill"):
        group = [r for r in rows if r["function"] == function]
        successful = [r["command_duration_ms"] for r in group if r["success"]]
        failed = len(group) - len(successful)
        summary["results"][function] = {
            "total_calls": len(group),
            "successful_calls": len(successful),
            "failed_calls": failed,
            "failure_rate_percent": round(100 * failed / len(group), 2),
            "mean_ms": round(statistics.mean(successful), 3) if successful else None,
            "median_ms": round(statistics.median(successful), 3) if successful else None,
            "p95_ms": round(p95(successful), 3) if successful else None,
            "throughput_successful_calls_per_second": (
                round(1000 / statistics.mean(successful), 3) if successful else None
            )
        }

    JSON_OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print("\n=== 100-BILL QUERY BENCHMARK ===")
    print(json.dumps(summary, indent=2))
    print("CSV:", CSV_OUT)
    print("JSON:", JSON_OUT)

if __name__ == "__main__":
    main()
