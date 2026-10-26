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
SNAPSHOT = Path("/tmp/solar_bills_check.json")
CSV_OUT = ROOT / "benchmark/read_results_50006_ledger_bills.csv"
JSON_OUT = ROOT / "test-reports/solarbill_read_benchmark_50006_ledger_bills.json"
PROGRESS_OUT = ROOT / "test-reports/solarbill_read_benchmark_50006_progress.json"
REPEATS = 3
EXPECTED_BILLS = 50006


def p95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)]


def query(function, bill_id):
    command = [
        "bash", "-c",
        'source scripts/envVar.sh >/dev/null 2>&1 && '
        'setGlobals 1 >/dev/null 2>&1 && '
        'export FABRIC_CFG_PATH="$HOME/fabric-project/fabric-samples/config" && '
        'exec "$@"',
        "_", str(PEER), "chaincode", "query",
        "-C", "mychannel", "-n", "solarbill",
        "-c", json.dumps({"function": function, "Args": [str(bill_id)]})
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
    for path in (CSV_OUT, JSON_OUT, PROGRESS_OUT):
        if path.exists():
            raise SystemExit(f"Output already exists; nothing overwritten: {path}")

    if not SNAPSHOT.exists():
        raise SystemExit(f"Ledger snapshot not found: {SNAPSHOT}")

    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    bills = data if isinstance(data, list) else data.get("bills", [])
    if len(bills) != EXPECTED_BILLS:
        raise SystemExit(f"Expected {EXPECTED_BILLS} bills; found {len(bills)}")

    ids = [str(b["billId"]) for b in bills]
    if len(set(ids)) != EXPECTED_BILLS or any(not x for x in ids):
        raise SystemExit("Bill IDs are missing or duplicated; stopping.")

    for function in ("ReadBill", "VerifyBill"):
        elapsed, ok, response, error = query(function, ids[0])
        if not ok:
            raise SystemExit(f"{function} preflight failed: {error}")
        print(f"Preflight {function}: PASS ({elapsed:.1f} ms)", flush=True)

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    total = EXPECTED_BILLS * 2 * REPEATS
    completed_bills = 0
    rows_written = 0
    columns = [
        "timestamp_utc", "function", "bill_id", "run",
        "command_duration_ms", "success", "response", "error"
    ]

    print(f"Starting benchmark: {total:,} measured queries", flush=True)
    print("Progress will be saved every 100 bills.", flush=True)

    with CSV_OUT.open("x", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        f.flush()

        for i, bill in enumerate(bills, 1):
            for function in ("ReadBill", "VerifyBill"):
                for run in range(1, REPEATS + 1):
                    elapsed, ok, response, error = query(function, bill["billId"])
                    writer.writerow({
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "function": function,
                        "bill_id": str(bill["billId"]),
                        "run": run,
                        "command_duration_ms": round(elapsed, 3),
                        "success": ok,
                        "response": response,
                        "error": error
                    })
                    rows_written += 1

            if i % 100 == 0 or i == EXPECTED_BILLS:
                f.flush()
                completed_bills = i
                progress = {
                    "status": "running",
                    "started_at_utc": started_utc,
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "bills_completed": i,
                    "expected_bills": EXPECTED_BILLS,
                    "queries_written": rows_written,
                    "expected_queries": total,
                    "elapsed_minutes": round((time.monotonic() - started) / 60, 2),
                    "csv_file": str(CSV_OUT)
                }
                PROGRESS_OUT.write_text(json.dumps(progress, indent=2) + "\n")
                print(
                    f"Completed {i:,}/{EXPECTED_BILLS} bills; "
                    f"{rows_written:,}/{total:,} queries; "
                    f"elapsed {progress['elapsed_minutes']:.1f} min",
                    flush=True
                )

    # Summarize the persisted CSV, including any failed calls.
    results = {}
    with CSV_OUT.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))

    for function in ("ReadBill", "VerifyBill"):
        group = [r for r in all_rows if r["function"] == function]
        successful = [
            float(r["command_duration_ms"]) for r in group
            if r["success"].lower() == "true"
        ]
        failed = len(group) - len(successful)
        results[function] = {
            "total_calls": len(group),
            "successful_calls": len(successful),
            "failed_calls": failed,
            "failure_rate_percent": round(100 * failed / len(group), 2),
            "mean_ms": round(statistics.mean(successful), 3) if successful else None,
            "median_ms": round(statistics.median(successful), 3) if successful else None,
            "p95_ms": round(p95(successful), 3) if successful else None,
            "throughput_successful_calls_per_second": round(
                1000 / statistics.mean(successful), 3
            ) if successful else None
        }

    summary = {
        "started_at_utc": started_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_file": str(SNAPSHOT),
        "dataset_bills_tested": EXPECTED_BILLS,
        "unique_bill_ids": len(set(ids)),
        "repeats_per_function_per_bill": REPEATS,
        "ledger_size_during_test": EXPECTED_BILLS,
        "total_measured_queries": len(all_rows),
        "measurement": (
            "CLI-observed query wall-clock latency including process startup; "
            "individual ReadBill and VerifyBill calls. Throughput is the "
            "reciprocal of mean successful-call latency, as in the baseline."
        ),
        "results": results,
        "csv_file": str(CSV_OUT)
    }

    with JSON_OUT.open("x", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
        f.write("\n")

    PROGRESS_OUT.write_text(json.dumps({
        "status": "completed",
        "finished_at_utc": summary["finished_at_utc"],
        "bills_completed": EXPECTED_BILLS,
        "queries_written": len(all_rows),
        "json_file": str(JSON_OUT),
        "csv_file": str(CSV_OUT)
    }, indent=2) + "\n")

    print("\n=== 50,006-BILL LEDGER QUERY BENCHMARK ===")
    print(json.dumps(summary, indent=2))
    print("CSV:", CSV_OUT)
    print("JSON:", JSON_OUT)


if __name__ == "__main__":
    main()
