# Solar Bill Audit Using Blockchain with Hyperledger Fabric

## 1. Project Overview

This project uses Hyperledger Fabric to support the integrity and auditability of solar electricity billing records.

The system stores solar billing records on a permissioned blockchain, calculates cryptographic hashes to detect record changes, verifies billing calculations, and retrieves transaction history for auditing.

## 2. Current Features

- Create individual solar billing records.
- Import multiple billing records.
- Read a bill by its ID.
- Retrieve all stored bills.
- Verify a bill's integrity using a SHA-256 hash.
- Validate the bill amount against the implemented billing formula.
- Retrieve a bill's transaction history from the Fabric ledger.

## 3. Technology Stack

- Hyperledger Fabric 2.5
- JavaScript
- Node.js and npm
- Fabric Contract API
- SHA-256 cryptographic hashing
- Docker Desktop with WSL2
- JSON dataset

## 4. Dataset

The `dataset/` directory contains `sampleBills_100.json`, a sample dataset of 100 solar billing records.

The records contain the following fields:

- `billId`
- `consumerId`
- `billDate`
- `transactionId`
- `unitsGenerated`
- `unitsConsumed`
- `amountPayable`
- `ratePerKWh`

The dataset is intended for the project prototype and testing.

## 5. Billing Calculation

The implemented billing formula is:

Amount Payable = max(0, Units Consumed - Units Generated) × Rate per kWh

The calculated amount is rounded to two decimal places.

## 6. Integrity Verification

The chaincode calculates a SHA-256 hash from the core billing fields and stores it with the record.

The verification function recalculates the hash and compares it with the stored hash. It also checks the billing calculation.

A mismatch indicates that the record or its calculated amount does not match the expected values.

## 7. Project Structure

```text
solar-billing-audit-fabric/
├── dataset/
│   └── sampleBills_100.json
├── solar-bill-chaincode/
│   ├── index.js
│   ├── package.json
│   ├── package-lock.json
│   └── lib/
│       └── solarBillContract.js
├── docs/
├── gateway-client/
├── .gitignore
├── LICENSE
└── README.md

## 8. Verification and Testing

The Hyperledger Fabric test network was verified to be running, and the `solarbill` chaincode was confirmed as committed on `mychannel` (version 1.0, sequence 3).

### Ledger Verification Results

- Total solar billing records retrieved: 101.
- Original dataset records: 100.
- Additional test record: `TEST900001`.
- Original dataset records with unique bill IDs: 100.
- Audit status reported for all 100 dataset records: `MATCH`.
- `VerifyBill` returned `billingFormulaMatches: true` and `integrityHashMatches: true` for `TEST900001`.
- `GetBillHistory` successfully returned the transaction history for `TEST900001`.

### Automated Integrity Tests

The local Node.js test suite is located at `solar-bill-chaincode/test/integrity.test.js`.

Run the tests with:

```bash
cd solar-bill-chaincode
npm test
```

The current test suite contains two passing tests:

1. Changing a bill amount produces a different SHA-256 integrity hash.
2. An unchanged bill produces the same SHA-256 integrity hash.

**Testing limitation:** These automated tests simulate hash comparisons locally. They do not yet demonstrate tampering detection against an altered record in the deployed Fabric ledger. All ledger verification results above reflect the records and audit statuses returned by the current chaincode.
