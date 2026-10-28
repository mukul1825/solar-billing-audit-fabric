const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');

function hashBill(bill) {
  const canonical = JSON.stringify({
    billDate: bill.billDate,
    billId: bill.billId,
    consumerId: bill.consumerId,
    transactionId: bill.transactionId,
    unitsGenerated: bill.unitsGenerated,
    unitsConsumed: bill.unitsConsumed,
    amountPayable: bill.amountPayable,
    ratePerKWh: bill.ratePerKWh,
  });

  return crypto.createHash('sha256').update(canonical, 'utf8').digest('hex');
}

test('changing a bill amount causes its integrity hash check to fail', () => {
  const bill = {
    billDate: '18/10/2026',
    billId: 'TEST900001',
    consumerId: 'TESTCON900001',
    transactionId: 'TESTTX900001',
    unitsGenerated: '100.00',
    unitsConsumed: '120.00',
    amountPayable: '219.40',
    ratePerKWh: '10.97',
  };

  const originalHash = hashBill(bill);

  const tamperedBill = { ...bill, amountPayable: '999.99' };
  const tamperedHash = hashBill(tamperedBill);

  assert.notEqual(tamperedHash, originalHash);
});

test('an unchanged bill produces the same integrity hash', () => {
  const bill = {
    billDate: '18/10/2026',
    billId: 'TEST900001',
    consumerId: 'TESTCON900001',
    transactionId: 'TESTTX900001',
    unitsGenerated: '100.00',
    unitsConsumed: '120.00',
    amountPayable: '219.40',
    ratePerKWh: '10.97',
  };

  assert.equal(hashBill({ ...bill }), hashBill(bill));
});

const SolarBillContract = require('../lib/solarBillContract');

test('VerifyBill detects a changed amount through its integrity hash', async () => {
  const contract = new SolarBillContract();

  const bill = {
    billDate: '18/10/2026',
    billId: 'TEST900002',
    consumerId: 'TESTCON900002',
    transactionId: 'TESTTX900002',
    unitsGenerated: '100.00',
    unitsConsumed: '120.00',
    amountPayable: '219.40',
    ratePerKWh: '10.97',
  };

  bill.expectedAmountPayable = '219.40';
  bill.auditStatus = 'MATCH';
  bill.integrityHash = contract._hashBill(bill);
  bill.fabricTransactionId = 'TEST-FABRIC-TX';

  const ctx = {
    stub: {
      createCompositeKey: () => 'test-key',
      getState: async () => Buffer.from(JSON.stringify({
        ...bill,
        amountPayable: '999.99',
      })),
    },
  };

  const result = JSON.parse(await contract.VerifyBill(ctx, bill.billId));

  assert.equal(result.billingFormulaMatches, false);
  assert.equal(result.integrityHashMatches, false);
  assert.equal(result.auditStatus, 'MISMATCH');
});

// Mock ledger for CreateBill and ImportBills tests.
// These tests never connect to the real Fabric network.
function createMockContext(initialBills = {}) {
  const state = new Map(
    Object.entries(initialBills).map(([id, bill]) => [
      `solarBill:${id}`,
      Buffer.from(JSON.stringify(bill)),
    ])
  );
  let writes = 0;

  return {
    stub: {
      createCompositeKey: (objectType, attributes) =>
        `${objectType}:${attributes.join(':')}`,
      getState: async (key) => state.get(key) || Buffer.alloc(0),
      putState: async (key, value) => {
        state.set(key, Buffer.from(value));
        writes++;
      },
      getTxTimestamp: () => ({ seconds: { toString: () => '1792281600' } }),
      getTxID: () => 'MOCK-FABRIC-TX',
    },
    state,
    get writes() {
      return writes;
    },
  };
}

function makeTestBill(id) {
  return {
    billDate: '18/10/2026',
    billId: id,
    consumerId: `CON-${id}`,
    transactionId: `TX-${id}`,
    unitsGenerated: '100.00',
    unitsConsumed: '120.00',
    amountPayable: '219.40',
    ratePerKWh: '10.97',
  };
}

test('CreateBill saves a valid bill with audit and integrity fields', async () => {
  const contract = new SolarBillContract();
  const ctx = createMockContext();

  const result = JSON.parse(
    await contract.CreateBill(ctx, JSON.stringify(makeTestBill('TEST-CREATE-1')))
  );

  assert.equal(result.billId, 'TEST-CREATE-1');
  assert.equal(result.expectedAmountPayable, '219.40');
  assert.equal(result.auditStatus, 'MATCH');
  assert.ok(result.integrityHash);
  assert.equal(result.fabricTransactionId, 'MOCK-FABRIC-TX');
  assert.equal(ctx.writes, 1);
});

test('CreateBill rejects an existing bill ID without overwriting it', async () => {
  const contract = new SolarBillContract();
  const original = { ...makeTestBill('TEST-CREATE-DUP'), marker: 'original' };
  const ctx = createMockContext({ 'TEST-CREATE-DUP': original });

  await assert.rejects(
    contract.CreateBill(ctx, JSON.stringify(makeTestBill('TEST-CREATE-DUP'))),
    /already exists/
  );

  assert.equal(ctx.writes, 0);
  assert.equal(
    JSON.parse((await ctx.stub.getState('solarBill:TEST-CREATE-DUP')).toString()).marker,
    'original'
  );
});

test('CreateBill rejects a bill with a missing required field', async () => {
  const contract = new SolarBillContract();
  const ctx = createMockContext();
  const bill = makeTestBill('TEST-CREATE-INVALID');
  delete bill.consumerId;

  await assert.rejects(
    contract.CreateBill(ctx, JSON.stringify(bill)),
    /Missing required field: consumerId/
  );

  assert.equal(ctx.writes, 0);
});

test('ImportBills imports a valid batch and reports its count', async () => {
  const contract = new SolarBillContract();
  const ctx = createMockContext();
  const bills = [
    makeTestBill('TEST-IMPORT-1'),
    makeTestBill('TEST-IMPORT-2'),
  ];

  const result = JSON.parse(
    await contract.ImportBills(ctx, JSON.stringify(bills))
  );

  assert.equal(result.imported, 2);
  assert.equal(result.bills.length, 2);
  assert.equal(ctx.writes, 2);
  assert.ok(ctx.state.has('solarBill:TEST-IMPORT-1'));
  assert.ok(ctx.state.has('solarBill:TEST-IMPORT-2'));
});

test('ImportBills rejects duplicate IDs within a batch before writing anything', async () => {
  const contract = new SolarBillContract();
  const ctx = createMockContext();
  const bills = [
    makeTestBill('TEST-IMPORT-DUP'),
    makeTestBill('TEST-IMPORT-DUP'),
  ];

  await assert.rejects(
    contract.ImportBills(ctx, JSON.stringify(bills)),
    /Duplicate billId in import/
  );

  assert.equal(ctx.writes, 0);
  assert.equal(ctx.state.size, 0);
});

test('ImportBills rejects an ID already in the ledger before writing the batch', async () => {
  const contract = new SolarBillContract();
  const existing = makeTestBill('TEST-IMPORT-EXISTING');
  const ctx = createMockContext({ 'TEST-IMPORT-EXISTING': existing });
  const bills = [
    makeTestBill('TEST-IMPORT-NEW'),
    makeTestBill('TEST-IMPORT-EXISTING'),
  ];

  await assert.rejects(
    contract.ImportBills(ctx, JSON.stringify(bills)),
    /already exists/
  );

  assert.equal(ctx.writes, 0);
  assert.equal(ctx.state.size, 1);
  assert.equal(ctx.state.has('solarBill:TEST-IMPORT-NEW'), false);
});

test('ImportBills rejects an invalid record before writing any record', async () => {
  const contract = new SolarBillContract();
  const ctx = createMockContext();
  const invalid = makeTestBill('TEST-IMPORT-INVALID');
  invalid.billDate = '31/02/2026';

  await assert.rejects(
    contract.ImportBills(
      ctx,
      JSON.stringify([makeTestBill('TEST-IMPORT-VALID'), invalid])
    ),
    /real date/
  );

  assert.equal(ctx.writes, 0);
  assert.equal(ctx.state.size, 0);
});
