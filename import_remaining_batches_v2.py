import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path.home() / "fabric-project/solar-billing-audit-fabric"
NETWORK = Path.home() / "fabric-project/fabric-samples/test-network"
PEER = str(Path.home() / "fabric-project/fabric-samples/bin/peer")
BATCH_DIR = ROOT / "dataset/batches_10000_size250"
REPORT_DIR = ROOT / "test-reports"

REPORT_DIR.mkdir(parents=True, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT = REPORT_DIR / f"import_remaining_{stamp}.json"
LOG = REPORT_DIR / f"import_remaining_{stamp}.log"

ORDERER_CA = NETWORK / "organizations/ordererOrganizations/example.com/tlsca/tlsca.example.com-cert.pem"
ORG1_TLS = NETWORK / "organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_TLS = NETWORK / "organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

env = os.environ.copy()
report = {"startedAt": datetime.now().isoformat(), "batches": [], "status": "running"}

def log(message):
    print(message, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(message + "\n")

def save_report():
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

def run_peer(args, timeout=180):
    return subprocess.run(
        [PEER] + args, cwd=NETWORK, env=env,
        capture_output=True, text=True, timeout=timeout
    )

def check_bill(bill_id):
    for attempt in range(3):
        try:
            result = run_peer([
                "chaincode", "query", "-C", "mychannel", "-n", "solarbill",
                "-c", json.dumps({"function": "ReadBill", "Args": [str(bill_id)]})
            ])
        except subprocess.TimeoutExpired:
            log(f"  Query timed out for {bill_id} (attempt {attempt + 1}/3)")
            continue

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if str(data.get("billId")) == str(bill_id):
                    return "present"
                log(f"  Unexpected bill response for {bill_id}")
                continue
            except (json.JSONDecodeError, AttributeError):
                log(f"  Invalid JSON response for {bill_id} (attempt {attempt + 1}/3)")
                continue

        error_text = (result.stderr or "") + "\\n" + (result.stdout or "")
        if f"Bill {bill_id} does not exist" in error_text:
            return "missing"

        log(f"  Query error for {bill_id} (attempt {attempt + 1}/3): {error_text[-300:]}")

    return "error"

def verify_ids(bills):
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
        if i % 50 == 0 or i == len(bills):
            log(f"  Verified {i}/{len(bills)} records")
    return present, missing, errors

try:
    if not all(p.is_file() for p in [ORDERER_CA, ORG1_TLS, ORG2_TLS]):
        raise RuntimeError("A required TLS certificate is missing.")
    if not Path(PEER).is_file():
        raise RuntimeError(f"Peer CLI not found: {PEER}")
    if not env.get("CORE_PEER_ADDRESS") or not env.get("CORE_PEER_LOCALMSPID"):
        raise RuntimeError(
            "Fabric environment is not loaded. Run source scripts/envVar.sh "
            "and setGlobals 1 from the test-network directory first."
        )

    # Confirm the network works before touching any batch.
    probe = run_peer([
        "chaincode", "query", "-C", "mychannel", "-n", "solarbill",
        "-c", '{"function":"org.hyperledger.fabric:GetMetadata","Args":[]}'
    ])
    if probe.returncode != 0:
        raise RuntimeError("Chaincode metadata query failed: " + probe.stderr[-1500:])

    for batch_number in range(4, 37):
        path = BATCH_DIR / f"batch_{batch_number:02d}.json"
        if not path.is_file():
            raise RuntimeError(f"Missing batch file: {path}")

        bills = json.loads(path.read_text(encoding="utf-8"))
        if not bills or len(bills) > 250:
            raise RuntimeError(f"Unexpected batch size in {path.name}")

        ids = [str(b["billId"]) for b in bills]
        if len(set(ids)) != len(ids):
            raise RuntimeError(f"Duplicate bill IDs inside {path.name}")

        log(f"\n=== Batch {batch_number}/36: {len(bills)} bills ===")

        present, missing, errors = verify_ids(bills)
        if errors:
            raise RuntimeError(
                f"Unexpected ledger query errors in {path.name}: {errors[:10]}"
            )

        imported_now = 0
        if missing:
            to_import = [b for b in bills if str(b["billId"]) in set(missing)]
            request = json.dumps({
                "function": "ImportBills",
                "Args": [json.dumps(to_import, separators=(",", ":"))]
            }, separators=(",", ":"))

            log(f"Submitting {len(to_import)} missing bills from {path.name}...")
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
                ], timeout=180)
                invoke_ok = result.returncode == 0
                if invoke_ok:
                    log("Invoke command returned success.")
                else:
                    log("Invoke returned an error; checking ledger before deciding.")
                    log((result.stderr or result.stdout)[-2000:])
            except subprocess.TimeoutExpired:
                invoke_ok = False
                log("Invoke timed out; checking ledger before deciding.")

            # Never blindly retry an uncertain transaction.
            present, missing, errors = verify_ids(bills)
            if errors:
                raise RuntimeError(
                    f"Verification query errors after invoke: {errors[:10]}"
                )
            if missing:
                raise RuntimeError(
                    f"{len(missing)} bills remain missing after the attempt. "
                    "Stopped without retrying. First IDs: " + ", ".join(missing[:10])
                )
            imported_now = len(to_import)
            log("All bills in this batch are present after the import attempt.")
        else:
            log("All bills in this batch were already present; no import needed.")

        entry = {
            "batch": batch_number,
            "expected": len(bills),
            "present": len(present),
            "missing": len(missing),
            "queryErrors": len(errors),
            "newlySubmitted": imported_now,
            "status": "verified"
        }
        report["batches"].append(entry)
        save_report()
        log(f"Batch {batch_number} verified: {len(present)}/{len(bills)}")

    report["status"] = "completed"
    report["completedAt"] = datetime.now().isoformat()
    save_report()
    log("\nALL REMAINING BATCHES VERIFIED.")

except Exception as exc:
    report["status"] = "stopped_with_error"
    report["error"] = str(exc)
    report["stoppedAt"] = datetime.now().isoformat()
    save_report()
    log(f"\nSTOPPED SAFELY: {exc}")
    log(f"Progress report: {REPORT}")
    log(f"Log file: {LOG}")
    raise SystemExit(1)

log(f"\nProgress report: {REPORT}")
log(f"Log file: {LOG}")
