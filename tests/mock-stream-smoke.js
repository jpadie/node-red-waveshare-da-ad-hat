#!/usr/bin/env node
'use strict';

// Ensure Python worker uses mock GPIO/SPI
process.env.WS_MOCK_GPIO = process.env.WS_MOCK_GPIO || '1';

const path = require('node:path');
const wm = require(path.join(__dirname, '..', 'nodes', 'worker-manager.js'));
const workerManager = wm.workerManager || wm.default || wm;

async function main() {
  workerManager.addRef();
  const ok = await workerManager.ping();
  console.log('ping', ok);
  if (!ok) throw new Error('Worker did not respond to ping');

  let got = 0;
  const max = 5;

  const handler = (s) => {
    if (s && !s.error) {
      console.log(`sample ch=${s.channel} raw=${s.raw} mv=${(s.voltage_mv||0).toFixed ? s.voltage_mv.toFixed(2) : s.voltage_mv}`);
      if (++got >= max) finish();
    }
  };

  const subId = 'mock-smoke';
  workerManager.subscribeAD(subId, { ch: 0, differential: false, neg: 8, gain: 1, drate: 10.0, buffered: false }, handler);
  // Give stream a moment to start and samples to arrive
  setTimeout(() => { if (got === 0) { console.log('waiting...'); } }, 250);

  setTimeout(() => finish(new Error('Timeout waiting for samples')), 4000);

  function finish(err) {
    try { workerManager.unsubscribeAD(subId); } catch {}
    try { workerManager.removeRef(); } catch {}
    if (err) {
      console.error(String(err.message || err));
      process.exit(1);
    } else {
      console.log('ok');
      process.exit(0);
    }
  }
}

main().catch((e) => { console.error(e?.message || e); process.exit(1); });


