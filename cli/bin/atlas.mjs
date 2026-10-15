#!/usr/bin/env node
import { run } from '../src/atlas-cli.mjs';
run().catch((err) => {
  if (err && err.envelope) {
    console.error(JSON.stringify(err.envelope));
  } else {
    console.error(err.message || err);
  }
  process.exit(err.exitCode || 1);
});
