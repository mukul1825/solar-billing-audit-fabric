'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const grpc = require('@grpc/grpc-js');
const { connect, hash, signers } = require('@hyperledger/fabric-gateway');

const root = path.resolve(__dirname, '..');
const datasetPath = path.join(
  root, 'dataset/uploaded_datasets/sampleBills_100000.json'
);
const reportsDir = path.join(root, 'test-reports');
const concurrency = 5;

function csvCell(value) {
  const s = value == null ? '' : String(value);
  return `"${s.replace(/"/g, '""')}"`;
}

async function main() {
  const parsed = JSON.parse(fs.readFileSync(datasetPath, 'utf8'));
  const bills = Array.isArray(parsed)
    ? parsed
    : (parsed.bills ?? parsed.records ?? []);

  const ids = bills.map(b => String(b.billId ?? '').trim());
  if (ids.length !== 100000 || ids.some(id => !id) ||
      new Set(ids).size !== ids.length) {
    throw new Error(
      `Dataset validation failed: ${ids.length} records; ` +
      `${new Set(ids).size} unique IDs. Expected 100000 unique IDs.`
    );
  }

  fs.mkdirSync(reportsDir, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  const csvPath = path.join(
    reportsDir, `gateway_integrity_audit_100000_${stamp}.csv`
  );
  const jsonPath = path.join(
    reportsDir, `gateway_integrity_audit_100000_${stamp}.json`
  );

  const csvFd = fs.openSync(csvPath, 'wx');
  fs.writeSync(
    csvFd,
    'billId,billingFormulaMatches,integrityHashMatches,' +
    'auditStatus,expectedAmountPayable,recordedAmountPayable,' +
    'fabricTransactionId,error\n'
  );
  fs.closeSync(csvFd);

  const networkPath = path.join(
    process.env.HOME, 'fabric-project/fabric-samples/test-network'
  );
  const orgPath = path.join(
    networkPath, 'organizations/peerOrganizations/org1.example.com'
  );
  const userPath = path.join(
    orgPath, 'users/User1@org1.example.com/msp'
  );

  const tlsCert = fs.readFileSync(
    path.join(orgPath, 'peers/peer0.org1.example.com/tls/ca.crt')
  );
  const cert = fs.readFileSync(
    path.join(userPath, 'signcerts/User1@org1.example.com-cert.pem')
  );
  const privateKey = crypto.createPrivateKey(
    fs.readFileSync(path.join(userPath, 'keystore/priv_sk'))
  );

  const client = new grpc.Client(
    'localhost:7051',
    grpc.credentials.createSsl(tlsCert),
    {
      'grpc.ssl_target_name_override': 'peer0.org1.example.com',
      'grpc.default_authority': 'peer0.org1.example.com'
    }
  );

  let gateway;
  let completed = 0;
  let passed = 0;
  let formulaMismatches = 0;
  let hashMismatches = 0;
  let statusMismatches = 0;
  let queryErrors = 0;
  let idMismatches = 0;
  let csvBuffer = [];

  function flushCsv() {
    if (!csvBuffer.length) return;
    fs.appendFileSync(csvPath, csvBuffer.join(''));
    csvBuffer = [];
  }

  function recordRow(values) {
    csvBuffer.push(values.map(csvCell).join(',') + '\n');
    if (csvBuffer.length >= 500) flushCsv();
  }

  try {
    gateway = connect({
      client,
      identity: { mspId: 'Org1MSP', credentials: cert },
      signer: signers.newPrivateKeySigner(privateKey),
      hash: hash.sha256
    });

    const contract = gateway
      .getNetwork('mychannel')
      .getContract('solarbill');

    let nextIndex = 0;

    async function worker() {
      while (true) {
        const index = nextIndex++;
        if (index >= ids.length) return;

        const billId = ids[index];

        try {
          const bytes = await contract.evaluateTransaction(
            'VerifyBill', billId
          );
          const result = JSON.parse(Buffer.from(bytes).toString('utf8'));

          const formulaOK = result.billingFormulaMatches === true;
          const hashOK = result.integrityHashMatches === true;
          const statusOK = result.auditStatus === 'MATCH';
          const idOK = String(result.billId) === billId;

          if (!formulaOK) formulaMismatches++;
          if (!hashOK) hashMismatches++;
          if (!statusOK) statusMismatches++;
          if (!idOK) idMismatches++;

          if (formulaOK && hashOK && statusOK && idOK) passed++;

          recordRow([
            billId,
            result.billingFormulaMatches,
            result.integrityHashMatches,
            result.auditStatus,
            result.expectedAmountPayable,
            result.recordedAmountPayable,
            result.fabricTransactionId,
            idOK ? '' : `Returned billId ${result.billId}`
          ]);
        } catch (error) {
          queryErrors++;
          recordRow([billId, '', '', '', '', '', '', error.message]);
        }

        completed++;
        if (completed % 1000 === 0 || completed === ids.length) {
          flushCsv();
          console.log(
            `Progress: ${completed}/${ids.length}; ` +
            `passed=${passed}; queryErrors=${queryErrors}; ` +
            `formulaMismatches=${formulaMismatches}; ` +
            `hashMismatches=${hashMismatches}`
          );
        }
      }
    }

    await Promise.all(
      Array.from({ length: concurrency }, () => worker())
    );
    flushCsv();

    const report = {
      startedAt: stamp,
      completedAt: new Date().toISOString(),
      datasetPath,
      datasetRecords: bills.length,
      uniqueBillIds: new Set(ids).size,
      concurrency,
      completed,
      passed,
      formulaMismatches,
      hashMismatches,
      statusMismatches,
      idMismatches,
      queryErrors,
      overallStatus:
        completed === 100000 &&
        passed === 100000 &&
        queryErrors === 0
          ? 'PASS'
          : 'REVIEW_REQUIRED',
      csvReport: csvPath
    };

    fs.writeFileSync(jsonPath, JSON.stringify(report, null, 2), {
      flag: 'wx'
    });
    console.log('\nAudit summary:');
    console.log(JSON.stringify(report, null, 2));
    console.log(`JSON report: ${jsonPath}`);

    if (report.overallStatus !== 'PASS') process.exitCode = 1;
  } finally {
    if (gateway) gateway.close();
    client.close();
  }
}

main().catch(error => {
  console.error('Audit setup failed:', error);
  process.exitCode = 1;
});
