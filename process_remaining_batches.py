import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "fabric-project"
PROJECT = ROOT / "solar-billing-audit-fabric"
NETWORK = ROOT / "fabric-samples/test-network"
PEER = ROOT / "fabric-samples/bin/peer"
BATCH_DIR = PROJECT / "dataset/batches_40000_new_only_size250"
REPORT_DIR = PROJECT / "test-reports"

ORDERER_CA = NETWORK / (
    "organizations/ordererOrganizations/example.com/orderers/"
    "orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
)
ORG1_TLS = NETWORK / (
    "organizations/peerOrganizations/org1.example.com/peers/"
    "peer0.org1.example.com/tls/ca.crt"
)
ORG2_TLS = NETWORK / (
    "organizations/peerOrganizations/org2.example.com/peers/"
    "peer0.org2.example.com/tls/ca.crt"
)

def peer_query(bill_id):
    request = json.dumps({
        "function": "ReadBill",
        "Args": [str(bill_id)]
    })
    result = subprocess.run(
        [str(PEER), "chaincode", "query",
         "-C", "mychannel", "-n", "solarbill", "-c", request],
        capture_output=True, text=True, timeout=30
    )
    output = result.stdout.strip()
    combined = output + "\n" + result.stderr

    try:
        record = json.loads(output)
        if str(record.get("billId")) == str(bill_id):
            return "present"
        return "error"
    except (json.JSONDecodeError, AttributeError):
        if "does not exist" in combined.lower():
            return "missing"
        return "error"

def invoke_import(bills):
    bills_json = json.dumps(bills, separators=(",", ":"))
    request = json.dumps({
        "function": "ImportBills",
        "Args": [bills_json]
    }, separators=(",", ":"))

    command = [
        str(PEER), "chaincode", "invoke",
        "-o", "localhost:7050",
        "--ordererTLSHostnameOverride", "orderer.example.com",
        "--tls", "--cafile", str(ORDERER_CA),
        "-C", "mychannel", "-n", "solarbill",
        "--peerAddresses", "localhost:7051",
        "--tlsRootCertFiles", str(ORG1_TLS),
        "--peerAddresses", "localhost:9051",
        "--tlsRootCertFiles", str(ORG2_TLS),
        "-c", request
    ]
    return subprocess.run(
        command, capture_output=True, text=True, timeout=180
    )

def check_batch(bills, batch_name):
    present, missing, errors = [], [], []

    for i, bill in enumerate(bills, 1):
        bill_id = str(bill["billId"])
        try:
            status = peer_query(bill_id)
        except Exception as exc:
            print(f"Query exception for {bill_id}: {exc}", flush=True)
            status = "error"

        if status == "present":
            present.append(bill_id)
        elif status == "missing":
            missing.append(bill_id)
        else:
            errors.append(bill_id)

        if i % 50 == 0:
            print(f"  {batch_name}: checked {i}/{len(bills)}", flush=True)

    return present, missing, errors

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=7)
    parser.add_argument("--end", type=int, default=160)
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually submit missing records. Without this flag, no writes occur."
    )
    args = parser.parse_args()

    if not (7 <= args.start <= args.end <= 160):
        sys.exit("Invalid range. Choose batches 7 through 160.")
    if not PEER.exists():
        sys.exit(f"Peer CLI not found: {PEER}")
    if not all(p.exists() for p in (ORDERER_CA, ORG1_TLS, ORG2_TLS)):
        sys.exit("Required TLS certificate path missing. Nothing submitted.")
    if not os.environ.get("CORE_PEER_ADDRESS"):
        sys.exit(
            "Fabric environment is not loaded. Run source scripts/envVar.sh "
            "and setGlobals 1 from the test-network directory first."
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"remaining_batches_{args.start}_{args.end}_{stamp}.json"
    report = {
        "mode": "execute" if args.execute else "dry-run",
        "startBatch": args.start,
        "endBatch": args.end,
        "startedAt": datetime.now().isoformat(),
        "results": []
    }

    def save_report():
        report["updatedAt"] = datetime.now().isoformat()
        temp = report_path.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2))
        temp.replace(report_path)

    for number in range(args.start, args.end + 1):
        batch_name = f"batch_{number:03}.json"
        batch_path = BATCH_DIR / batch_name
        if not batch_path.exists():
            print(f"STOP: missing batch file {batch_path}")
            break

        try:
            bills = json.loads(batch_path.read_text())
            if not isinstance(bills, list) or not bills:
                raise ValueError("Batch must be a nonempty JSON array")
            if any("billId" not in b for b in bills):
                raise ValueError("A record has no billId")
            ids = [str(b["billId"]) for b in bills]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate billId inside the batch")
        except Exception as exc:
            print(f"STOP: cannot validate {batch_name}: {exc}")
            break

        print(f"\n=== {batch_name}: {len(bills)} records ===", flush=True)
        present, missing, errors = check_batch(bills, batch_name)

        entry = {
            "batch": number,
            "expected": len(bills),
            "alreadyPresentBefore": len(present),
            "missingBefore": len(missing),
            "queryErrorsBefore": len(errors),
            "submitted": 0,
            "verifiedPresentAfter": None,
            "missingAfter": None,
            "queryErrorsAfter": None,
            "status": "checking"
        }

        if errors:
            entry["status"] = "STOPPED_QUERY_ERRORS_BEFORE_SUBMISSION"
            report["results"].append(entry)
            save_report()
            print(f"STOP: query errors in {batch_name}; nothing submitted.")
            break

        if not missing:
            entry["verifiedPresentAfter"] = len(present)
            entry["missingAfter"] = 0
            entry["queryErrorsAfter"] = 0
            entry["status"] = "VERIFIED_ALREADY_PRESENT"
            report["results"].append(entry)
            save_report()
            print("All records already exist. Skipping invoke.")
            continue

        if not args.execute:
            entry["status"] = "DRY_RUN_WOULD_SUBMIT_MISSING"
            report["results"].append(entry)
            save_report()
            print(
                f"DRY RUN: {len(missing)} records missing; "
                "no blockchain writes were made."
            )
            continue

        missing_set = set(missing)
        missing_bills = [b for b in bills if str(b["billId"]) in missing_set]
        print(f"Submitting {len(missing_bills)} missing records once...", flush=True)

        try:
            result = invoke_import(missing_bills)
        except Exception as exc:
            entry["status"] = "STOPPED_INVOKE_EXCEPTION"
            entry["invokeError"] = str(exc)
            report["results"].append(entry)
            save_report()
            print("STOP: invoke outcome uncertain. Do not retry this batch blindly.")
            break

        entry["invokeExitCode"] = result.returncode
        entry["invokeStdout"] = result.stdout[-2000:]
        entry["invokeStderr"] = result.stderr[-2000:]
        entry["submitted"] = len(missing_bills) if result.returncode == 0 else 0

        # Even after a nonzero exit, check the ledger before deciding what happened.
        # Never automatically invoke this batch a second time.
        after_present, after_missing, after_errors = [], bills, []
        for attempt in range(3):
            time.sleep(3)
            after_present, after_missing, after_errors = check_batch(bills, batch_name)
            if not after_missing and not after_errors:
                break
            if attempt < 2:
                print(f"Verification retry {attempt + 1}/2...", flush=True)

        entry["verifiedPresentAfter"] = len(after_present)
        entry["missingAfter"] = len(after_missing)
        entry["queryErrorsAfter"] = len(after_errors)

        if not after_errors and not after_missing:
            entry["status"] = "VERIFIED_COMPLETE"
        elif after_errors:
            entry["status"] = "STOPPED_POSTCHECK_QUERY_ERRORS"
        else:
            entry["status"] = "STOPPED_RECORDS_STILL_MISSING"

        report["results"].append(entry)
        save_report()
        print(f"Batch status: {entry['status']}", flush=True)

        if entry["status"] != "VERIFIED_COMPLETE":
            print("Stopping safely. Review the report before taking further action.")
            break

    report["finishedAt"] = datetime.now().isoformat()
    save_report()
    print(f"\nReport saved to: {report_path}")
    print("No automatic retries were performed.")

if __name__ == "__main__":
    main()
