#!/usr/bin/env node
'use strict';

process.env.WS_MOCK_GPIO = process.env.WS_MOCK_GPIO || '1';

const path = require('node:path');
const wm = require(path.join(__dirname, '..', 'nodes', 'worker-manager.js'));
const workerManager = wm.workerManager || wm.default || wm;

async function bench(drate, seconds) {
  return new Promise(async (resolve, reject) => {
    try {
      workerManager.addRef();
      const ok = await workerManager.ping();
      if (!ok) return reject(new Error('ping failed'));
      let count = 0;
      const subId = `bench-${drate}`;
      const start = Date.now();
      const handler = () => { count++; };
      workerManager.subscribeAD(subId, { ch: 0, gain: 1, drate, differential: false, buffered: false }, handler);
      setTimeout(() => {
        try { workerManager.unsubscribeAD(subId); } catch {}
        try { workerManager.removeRef(); } catch {}
        const elapsed = (Date.now() - start) / 1000;
        resolve({ drate, count, elapsed, sps: count / elapsed });
      }, Math.max(1000, seconds * 1000));
    } catch (e) {
      reject(e);
    }
  });
}

async function main() {
  const drates = [10, 25, 50, 100];
  const results = [];
  for (const d of drates) {
    // 1 second per rate under mock
    const r = await bench(d, 1);
    results.push(r);
  }
  console.log(JSON.stringify(results, null, 2));
}

main().catch((e) => { console.error(e?.message || e); process.exit(1); });


