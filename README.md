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

