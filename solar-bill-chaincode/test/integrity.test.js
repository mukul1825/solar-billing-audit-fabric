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
