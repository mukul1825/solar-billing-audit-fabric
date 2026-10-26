'use strict';

const fs = require('node:fs');
const crypto = require('node:crypto');
const grpc = require('@grpc/grpc-js');
const { connect, hash, signers } = require('@hyperledger/fabric-gateway');

const networkPath = `${process.env.HOME}/fabric-project/fabric-samples/test-network`;
const orgPath = `${networkPath}/organizations/peerOrganizations/org1.example.com`;
const userPath = `${orgPath}/users/User1@org1.example.com/msp`;

async function main() {
  const action = process.argv[2];
  const billId = process.argv[3];

  if (!['read', 'verify', 'history'].includes(action) || !billId) {
    throw new Error('Usage: node index.js <read|verify|history> <existing-billId>');
  }

  const tlsCert = fs.readFileSync(
    `${orgPath}/peers/peer0.org1.example.com/tls/ca.crt`
  );
  const cert = fs.readFileSync(
    `${userPath}/signcerts/User1@org1.example.com-cert.pem`
  );
  const privateKeyPem = fs.readFileSync(
    `${userPath}/keystore/priv_sk`
  );
  const privateKey = crypto.createPrivateKey(privateKeyPem);

  const client = new grpc.Client(
    'localhost:7051',
    grpc.credentials.createSsl(tlsCert),
    {
      'grpc.ssl_target_name_override': 'peer0.org1.example.com',
      'grpc.default_authority': 'peer0.org1.example.com'
    }
  );

  let gateway;

  try {
    gateway = connect({
      client,
      identity: {
        mspId: 'Org1MSP',
        credentials: cert
      },
      signer: signers.newPrivateKeySigner(privateKey),
      hash: hash.sha256
    });

    const network = gateway.getNetwork('mychannel');
    const contract = network.getContract('solarbill');

    const functionName = {
      read: 'ReadBill',
      verify: 'VerifyBill',
      history: 'GetBillHistory'
    }[action];
    const result = await contract.evaluateTransaction(functionName, billId);

    console.log('ReadBill query succeeded.');
    console.log(Buffer.from(result).toString('utf8'));
  } finally {
    if (gateway) gateway.close();
    client.close();
  }
}

main().catch(error => {
  console.error('Gateway query failed:', error.message);
  process.exitCode = 1;
});
