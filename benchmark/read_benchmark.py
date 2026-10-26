
import csv
import json
import math
import os
import statistics
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

NETWORK = Path.home() / "fabric-project/fabric-samples/test-network"
BILL_ID = "112345"
REPEATS = 30
OUTPUT = Path.home() / "fabric-project/solar-billing-audit-fabric/benchmark/read_results.csv"


def percentile95(values):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def run_query(function):
    command = [
        "peer", "chaincode", "query",
        "-C", "mychannel",
        "-n", "solarbill",
        "-c", json.dumps({
            "function": function,
            "Args": [BILL_ID]
        })
    ]

    start = time.perf_counter_ns()
    result = subprocess.run(
        command,
        cwd=NETWORK,
        capture_output=True,
        text=True,
        timeout=60
    )
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000

    if result.returncode != 0:
        return elapsed_ms, False, "", result.stderr.strip()

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return elapsed_ms, False, result.stdout.strip(), "Invalid JSON response"

    return elapsed_ms, True, json.dumps(payload), ""


def main():
    if not OUTPUT.parent.exists():
        raise SystemExit(f"Missing benchmark directory: {OUTPUT.parent}")

    # One warm-up per function, excluded from measured results.
    for function in ("ReadBill", "VerifyBill"):
        elapsed, ok, response, error = run_query(function)
        if not ok:
            raise SystemExit(f"{function} warm-up failed: {error}")
        print(f"{function} warm-up succeeded ({elapsed:.2f} ms)")

    rows = []
    for function in ("ReadBill", "VerifyBill"):
        for run_number in range(1, REPEATS + 1):
            elapsed, ok, response, error = run_query(function)
            rows.append({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "function": function,
                "bill_id": BILL_ID,
                "run": run_number,
                "command_duration_ms": round(elapsed, 3),
                "success": ok,
                "response": response,
                "error": error
            })
            print(
                f"{function} {run_number}/{REPEATS}: "
                f"{elapsed:.2f} ms - {'OK' if ok else 'FAILED'}"
            )

    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print("\nSummary (successful calls only)")
    for function in ("ReadBill", "VerifyBill"):
        selected = [
            row["command_duration_ms"] for row in rows
            if row["function"] == function and row["success"]
        ]
        failures = sum(
            1 for row in rows
            if row["function"] == function and not row["success"]
        )
        print(f"\n{function}")
        print(f"  Successful: {len(selected)}/{REPEATS}")
        print(f"  Failures:   {failures}/{REPEATS}")
        if selected:
            print(f"  Mean:       {statistics.mean(selected):.3f} ms")
            print(f"  Median:     {statistics.median(selected):.3f} ms")
            print(f"  P95:        {percentile95(selected):.3f} ms")

    print(f"\nCSV saved to: {OUTPUT}")


if __name__ == "__main__":
    main()
