import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "fabric-project/solar-billing-audit-fabric"
NETWORK = Path.home() / "fabric-project/fabric-samples/test-network"
PEER = Path.home() / "fabric-project/fabric-samples/bin/peer"
BATCH_DIR = ROOT / "dataset/batches_40000_new_only_size250"
REPORT_DIR = ROOT / "test-reports"
EXPECTED_BATCHES = 160
EXPECTED_PER_BATCH = 250
DRY_RUN = "--dry-run" in sys.argv

ORDERER_CA = NETWORK / "organizations/ordererOrganizations/example.com/tlsca/tlsca.example.com-cert.pem"
ORG1_TLS = NETWORK / "organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_TLS = NETWORK / "organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

def run_peer(args, timeout=180):
    return subprocess.run(
        [str(PEER)] + args,
        cwd=NETWORK,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout
    )

def check_bill(bill_id):
    result = run_peer([
        "chaincode", "query", "-C", "mychannel", "-n", "solarbill",
        "-c", json.dumps({"function": "ReadBill", "Args": [str(bill_id)]})
    ])

    if result.returncode == 0:
        try:
            data = json.loads(result.stdout)
            return "present" if str(data.get("billId")) == str(bill_id) else "error"
        except (json.JSONDecodeError, AttributeError):
            return "error"

    error_text = (result.stderr or "") + "\n" + (result.stdout or "")
    if f"Bill {bill_id} does not exist" in error_text:
        return "missing"

    return "error"

def verify_bills(bills, log):
    present, missing, errors = [], [], []

    for i, bill in enumerate(bills, 1):
        bill_id = str(bill["billId"])
        status = check_bill(bill_id)

        if status == "present":
            present.append(bill_id)
        elif status == "missing":
            missing.append(bill_id)
        else:
            errors.append(bill_id)

        if i % 25 == 0 or i == len(bills):
            log(f"  Verified {i}/{len(bills)} bills")

    return present, missing, errors

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "_dry_run" if DRY_RUN else ""
    report_path = REPORT_DIR / f"import_40000_new_only_{stamp}{suffix}.json"
    log_path = REPORT_DIR / f"import_40000_new_only_{stamp}{suffix}.log"

    report = {
        "startedAt": datetime.now().isoformat(),
        "batchDirectory": str(BATCH_DIR),
        "expectedBatches": EXPECTED_BATCHES,
        "expectedRecords": EXPECTED_BATCHES * EXPECTED_PER_BATCH,
        "dryRun": DRY_RUN,
        "status": "running",
        "batches": []
    }

    def log(message):
        print(message, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(message + "\n")

    def save_report():
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    try:
        if not all(p.is_file() for p in [ORDERER_CA, ORG1_TLS, ORG2_TLS]):
            raise RuntimeError("Required TLS certificate missing.")
        if not PEER.is_file():
            raise RuntimeError(f"Peer CLI not found: {PEER}")
        if not os.environ.get("CORE_PEER_ADDRESS") or not os.environ.get("CORE_PEER_LOCALMSPID"):
            raise RuntimeError(
                "Fabric environment not loaded. In test-network, run "
                "'source scripts/envVar.sh' and 'setGlobals 1' first."
            )
        if not BATCH_DIR.is_dir():
            raise RuntimeError(f"Batch directory not found: {BATCH_DIR}")

        paths = [BATCH_DIR / f"batch_{n:03d}.json"
                 for n in range(1, EXPECTED_BATCHES + 1)]

        all_ids = set()
        total = 0

        log("Checking all batch files before import...")
        for n, path in enumerate(paths, 1):
            if not path.is_file():
                raise RuntimeError(f"Missing batch file: {path.name}")

            bills = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(bills, list) or len(bills) != EXPECTED_PER_BATCH:
                raise RuntimeError(f"Unexpected record count in {path.name}")

            batch_ids = []
            for bill in bills:
                if not isinstance(bill, dict) or not bill.get("billId"):
                    raise RuntimeError(f"Invalid bill or missing billId in {path.name}")
                if not bill.get("transactionId"):
                    raise RuntimeError(f"Missing transactionId in {path.name}")
                batch_ids.append(str(bill["billId"]))

            if len(batch_ids) != len(set(batch_ids)):
                raise RuntimeError(f"Duplicate billId within {path.name}")

            overlap = all_ids.intersection(batch_ids)
            if overlap:
                raise RuntimeError(f"Duplicate billId across batches: {list(overlap)[:5]}")

            all_ids.update(batch_ids)
            total += len(bills)

            if n % 20 == 0 or n == EXPECTED_BATCHES:
                log(f"  Checked {n}/{EXPECTED_BATCHES} batch files")

        if total != 40000 or len(all_ids) != 40000:
            raise RuntimeError(f"Expected 40,000 unique bills; found {total} records and {len(all_ids)} IDs.")

        probe = run_peer([
            "chaincode", "query", "-C", "mychannel", "-n", "solarbill",
            "-c", '{"function":"org.hyperledger.fabric:GetMetadata","Args":[]}'
        ])
        if probe.returncode != 0:
            raise RuntimeError("Fabric metadata query failed: " + (probe.stderr or probe.stdout)[-1500:])

        log("PASS: Fabric connection and all 160 batch files verified.")
        log(f"Unique bill IDs: {len(all_ids)}")

        if DRY_RUN:
            report["status"] = "dry_run_passed"
            report["validatedRecords"] = total
            report["completedAt"] = datetime.now().isoformat()
            save_report()
            log("DRY RUN ONLY: no bills were queried or imported.")
            return

        for n, path in enumerate(paths, 1):
            bills = json.loads(path.read_text(encoding="utf-8"))
            log(f"\n=== Batch {n}/{EXPECTED_BATCHES}: {len(bills)} bills ===")

            present, missing, errors = verify_bills(bills, log)
            if errors:
                raise RuntimeError(f"Query errors before import in {path.name}: {errors[:10]}")

            submitted = 0
            if missing:
                missing_set = set(missing)
                to_import = [b for b in bills if str(b["billId"]) in missing_set]

                request = json.dumps({
                    "function": "ImportBills",
                    "Args": [json.dumps(to_import, separators=(",", ":"))]
                }, separators=(",", ":"))

                log(f"Submitting {len(to_import)} missing bills...")
                try:
                    result = run_peer([
                        "chaincode", "invoke",
                        "-o", "localhost:7050",
                        "--ordererTLSHostnameOverride", "orderer.example.com",
                        "--tls", "--cafile", str(ORDERER_CA),
                        "-C", "mychannel", "-n", "solarbill",
                        "--peerAddresses", "localhost:7051",
                        "--tlsRootCertFiles", str(ORG1_TLS),
                        "--peerAddresses", "localhost:9051",
                        "--tlsRootCertFiles", str(ORG2_TLS),
                        "-c", request
                    ], timeout=300)

                    if result.returncode == 0:
                        log("Invoke returned success; verifying ledger state.")
                    else:
                        log("Invoke returned an error; verifying ledger state before deciding.")
                        log((result.stderr or result.stdout)[-2000:])

                except subprocess.TimeoutExpired:
                    log("Invoke timed out; verifying ledger state before deciding.")

                # Never blindly retry an uncertain transaction.
                present, missing, errors = verify_bills(bills, log)
                if errors:
                    raise RuntimeError(
                        f"Verification queries failed after invoke for {path.name}: {errors[:10]}"
                    )
                if missing:
                    raise RuntimeError(
                        f"{len(missing)} bills remain missing after one attempt in {path.name}. "
                        "Stopped without retrying. First missing IDs: " + ", ".join(missing[:10])
                    )

                submitted = len(to_import)
            else:
                log("All bills in this batch already exist; no import needed.")

            entry = {
                "batch": n,
                "file": path.name,
                "expected": len(bills),
                "presentAfterVerification": len(present),
                "missingAfterVerification": len(missing),
                "queryErrors": len(errors),
                "newlySubmitted": submitted,
                "status": "verified"
            }
            report["batches"].append(entry)
            save_report()
            log(f"PASS: Batch {n} verified ({len(present)}/{len(bills)}).")

        report["status"] = "completed"
        report["completedAt"] = datetime.now().isoformat()
        save_report()
        log("\nALL 160 BATCHES VERIFIED SUCCESSFULLY.")

    except Exception as exc:
        report["status"] = "stopped_with_error"
        report["error"] = str(exc)
        report["stoppedAt"] = datetime.now().isoformat()
        save_report()
        log(f"\nSTOPPED SAFELY: {exc}")
        log(f"Report: {report_path}")
        log(f"Log: {log_path}")
        raise SystemExit(1)

    log(f"\nReport: {report_path}")
    log(f"Log: {log_path}")

if __name__ == "__main__":
    main()
