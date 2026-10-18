'use strict';

const { Contract } = require('fabric-contract-api');
const crypto = require('crypto');

class SolarBillContract extends Contract {
  _parseMoneyOrUnits(value, field) {
    const text = String(value ?? '').trim();
    if (!/^\d+(\.\d{1,2})?$/.test(text)) {
      throw new Error(`${field} must be a non-negative number with at most 2 decimal places`);
    }
    const [whole, fraction = ''] = text.split('.');
    return (BigInt(whole) * 100n) + BigInt((fraction + '00').slice(0, 2));
  }

  _formatCents(cents) {
    const value = BigInt(cents);
    return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`;
  }

  _validDate(value) {
    if (typeof value !== 'string' || !/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return false;
    const [dd, mm, yyyy] = value.split('/').map(Number);
    const date = new Date(Date.UTC(yyyy, mm - 1, dd));
    return date.getUTCFullYear() === yyyy && date.getUTCMonth() === mm - 1 && date.getUTCDate() === dd;
  }

  _normalizeBill(input) {
    const required = ['billDate', 'billId', 'consumerId', 'transactionId', 'unitsGenerated', 'unitsConsumed', 'amountPayable', 'ratePerKWh'];
    for (const field of required) {
      if (input[field] === undefined || input[field] === null || String(input[field]).trim() === '') {
        throw new Error(`Missing required field: ${field}`);
      }
    }
    if (!this._validDate(String(input.billDate))) {
      throw new Error('billDate must be a real date in DD/MM/YYYY format');
    }
    for (const field of ['billId', 'consumerId', 'transactionId']) {
      if (typeof input[field] !== 'string' && typeof input[field] !== 'number') {
        throw new Error(`${field} must be a string or number`);
      }
    }

    const normalized = {
      billDate: String(input.billDate),
      billId: String(input.billId).trim(),
      consumerId: String(input.consumerId).trim(),
      // This is the source-data transactionId, not the Fabric transaction ID.
      transactionId: String(input.transactionId).trim(),
      unitsGenerated: this._formatCents(this._parseMoneyOrUnits(input.unitsGenerated, 'unitsGenerated')),
      unitsConsumed: this._formatCents(this._parseMoneyOrUnits(input.unitsConsumed, 'unitsConsumed')),
      amountPayable: this._formatCents(this._parseMoneyOrUnits(input.amountPayable, 'amountPayable')),
      ratePerKWh: this._formatCents(this._parseMoneyOrUnits(input.ratePerKWh, 'ratePerKWh')),
    };
    if (!normalized.billId || !normalized.consumerId || !normalized.transactionId) {
      throw new Error('billId, consumerId, and transactionId cannot be empty');
    }
    return normalized;
  }

  _expectedAmountCents(bill) {
    const generated = this._parseMoneyOrUnits(bill.unitsGenerated, 'unitsGenerated');
    const consumed = this._parseMoneyOrUnits(bill.unitsConsumed, 'unitsConsumed');
    const rate = this._parseMoneyOrUnits(bill.ratePerKWh, 'ratePerKWh');
    const difference = consumed > generated ? consumed - generated : 0n;
    // Units and rate are both stored in hundredths. Convert the product to cents,
    // rounding half-up to the nearest paise.
    return (difference * rate + 50n) / 100n;
  }

  _hashBill(bill) {
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

  async _saveBill(ctx, input) {
    const bill = this._normalizeBill(input);
    const key = ctx.stub.createCompositeKey('solarBill', [bill.billId]);
    const existing = await ctx.stub.getState(key);
    if (existing && existing.length > 0) throw new Error(`Bill ${bill.billId} already exists`);

    const expected = this._expectedAmountCents(bill);
    const actual = this._parseMoneyOrUnits(bill.amountPayable, 'amountPayable');
    bill.expectedAmountPayable = this._formatCents(expected);
    bill.auditStatus = expected === actual ? 'MATCH' : 'MISMATCH';
    bill.integrityHash = this._hashBill(bill);
    bill.recordedAt = ctx.stub.getTxTimestamp().seconds.toString();
    bill.fabricTransactionId = ctx.stub.getTxID();

    await ctx.stub.putState(key, Buffer.from(JSON.stringify(bill)));
    return bill;
  }

  async CreateBill(ctx, billJson) {
    const bill = await this._saveBill(ctx, JSON.parse(billJson));
    return JSON.stringify(bill);
  }

  async ImportBills(ctx, billsJson) {
    const bills = JSON.parse(billsJson);
    if (!Array.isArray(bills) || bills.length === 0) {
      throw new Error('ImportBills expects a non-empty JSON array of bills');
    }
    // Validate and check all keys before writing any state.
    const normalizedBills = bills.map((bill) => this._normalizeBill(bill));
    const seen = new Set();
    for (const bill of normalizedBills) {
      if (seen.has(bill.billId)) throw new Error(`Duplicate billId in import: ${bill.billId}`);
      seen.add(bill.billId);
      const key = ctx.stub.createCompositeKey('solarBill', [bill.billId]);
      const existing = await ctx.stub.getState(key);
      if (existing && existing.length > 0) throw new Error(`Bill ${bill.billId} already exists`);
    }
    const saved = [];
    for (const bill of normalizedBills) {
      const expected = this._expectedAmountCents(bill);
      const actual = this._parseMoneyOrUnits(bill.amountPayable, 'amountPayable');
      bill.expectedAmountPayable = this._formatCents(expected);
      bill.auditStatus = expected === actual ? 'MATCH' : 'MISMATCH';
      bill.integrityHash = this._hashBill(bill);
      bill.recordedAt = ctx.stub.getTxTimestamp().seconds.toString();
      bill.fabricTransactionId = ctx.stub.getTxID();
      const key = ctx.stub.createCompositeKey('solarBill', [bill.billId]);
      await ctx.stub.putState(key, Buffer.from(JSON.stringify(bill)));
      saved.push(bill);
    }
    return JSON.stringify({ imported: saved.length, bills: saved });
  }

  async ReadBill(ctx, billId) {
    const key = ctx.stub.createCompositeKey('solarBill', [String(billId)]);
    const data = await ctx.stub.getState(key);
    if (!data || data.length === 0) throw new Error(`Bill ${billId} does not exist`);
    return data.toString('utf8');
  }

  async VerifyBill(ctx, billId) {
    const bill = JSON.parse(await this.ReadBill(ctx, billId));
    const expected = this._expectedAmountCents(bill);
    const actual = this._parseMoneyOrUnits(bill.amountPayable, 'amountPayable');
    const currentHash = this._hashBill(bill);
    return JSON.stringify({
      billId: bill.billId,
      billingFormulaMatches: expected === actual,
      expectedAmountPayable: this._formatCents(expected),
      recordedAmountPayable: bill.amountPayable,
      integrityHashMatches: currentHash === bill.integrityHash,
      auditStatus: expected === actual ? 'MATCH' : 'MISMATCH',
      fabricTransactionId: bill.fabricTransactionId,
    });
  }

  async GetAllBills(ctx) {
    const iterator = await ctx.stub.getStateByPartialCompositeKey('solarBill', []);
    const bills = [];
    try {
      let result = await iterator.next();
      while (!result.done) {
        if (result.value && result.value.value) bills.push(JSON.parse(result.value.value.toString('utf8')));
        result = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return JSON.stringify(bills);
  }

  async GetBillHistory(ctx, billId) {
    const key = ctx.stub.createCompositeKey('solarBill', [String(billId)]);
    const iterator = await ctx.stub.getHistoryForKey(key);
    const history = [];
    try {
      let result = await iterator.next();
      while (!result.done) {
        const item = result.value;
        history.push({
          transactionId: item.txId,
          timestamp: item.timestamp ? {
            seconds: item.timestamp.seconds.toString(),
            nanos: item.timestamp.nanos,
          } : null,
          isDelete: item.isDelete,
          value: item.value && item.value.length ? JSON.parse(item.value.toString('utf8')) : null,
        });
        result = await iterator.next();
      }
    } finally {
      await iterator.close();
    }
    return JSON.stringify(history);
  }
}

module.exports = SolarBillContract;
