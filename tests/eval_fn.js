#!/usr/bin/env node
// Node bridge: extracts the JISOO compute block from ui-sample.html between
// BEGIN COMPUTE / END COMPUTE markers, then evaluates a compute function on
// a fixture profile. Invoked by tests/test_financial_model.py.
//
// Usage:
//   node eval_fn.js <fixtures.json> <profile_key> <fn_name> [case]
//
// fn_name ∈ {computeProfile, computeCashFlow, computeRevenueCashFlow}

const fs = require('fs');
const path = require('path');

const [fixturesPath, profileKey, fnName, caseName] = process.argv.slice(2);
if (!fixturesPath || !profileKey || !fnName) {
  console.error('Usage: eval_fn.js <fixtures.json> <profile_key> <fn_name> [case]');
  process.exit(2);
}

const fixtures = JSON.parse(fs.readFileSync(fixturesPath, 'utf8'));
if (!(profileKey in fixtures)) {
  console.error(`Profile "${profileKey}" not in fixtures`);
  process.exit(2);
}
const profile = JSON.parse(JSON.stringify(fixtures[profileKey]));

const htmlPath = path.join(__dirname, '..', 'ui-sample.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const m = html.match(/\/\/ ── BEGIN COMPUTE ──([\s\S]*?)\/\/ ── END COMPUTE ──/);
if (!m) { console.error('COMPUTE markers missing in ui-sample.html'); process.exit(1); }

// Shim browser globals the compute block relies on
if (typeof global.crypto === 'undefined') {
  global.crypto = { randomUUID: () => 'tc_' + Math.random().toString(36).slice(2, 10) };
}

// Extract TICKETING_CO_PRESETS + VENUE_PRESETS + fdMigrateProfile from the HTML.
function extractBlock(pattern) {
  const mm = html.match(pattern);
  return mm ? mm[0] : null;
}
const presetsBlock = extractBlock(/const VENUE_PRESETS = \{[\s\S]*?^\};/m);
const ticketingBlock = extractBlock(/const TICKETING_CO_PRESETS = \{[\s\S]*?^\};/m);
const migrateBlock = extractBlock(/function fdMigrateProfile\(p\) \{[\s\S]*?\n\}\n/);

// Each eval() has its own scope, so `const` declarations don't leak.
// Rewrite `const X =` to `global.X =` so they become globally visible.
function asGlobal(block) {
  return block ? block.replace(/^const (\w+) =/m, 'global.$1 =') : null;
}
const migrateAsGlobal = migrateBlock
  ? migrateBlock.replace(/^function fdMigrateProfile/, 'global.fdMigrateProfile = function')
              .replace(/\n\}\n$/, '\n};\n')
  : null;

if (presetsBlock)   eval(asGlobal(presetsBlock));
if (ticketingBlock) eval(asGlobal(ticketingBlock));
if (migrateAsGlobal) eval(migrateAsGlobal);

// Also rewrite compute block so top-level `function` declarations become globals
const computeAsGlobal = m[1]
  .replace(/^function (\w+)\(/gm, 'global.$1 = function (');
// balance closers (we turned `function X(...) { ... }` into `global.X = function (...) { ... }`
// — closers already match the original `}` — but we need to add `;` after.
// Simpler: keep original, then export the names we need into global.
eval(m[1]);
global.fdMonthKey = fdMonthKey;
global.fdMonthAdd = fdMonthAdd;
global.fdMonthsBetween = fdMonthsBetween;
global.fdMonthFromDateStr = fdMonthFromDateStr;
global.fdMmyyFromMonth = fdMmyyFromMonth;
global.computeProfile = computeProfile;
global.computeCashFlow = computeCashFlow;
global.computeRevenueCashFlow = computeRevenueCashFlow;
global.fdComputeCashFlowEvents = fdComputeCashFlowEvents;

if (typeof global.fdMigrateProfile === 'function') {
  global.fdMigrateProfile(profile);
}

const opts = caseName ? { case: caseName } : {};
const pResult = computeProfile(profile, opts);

let out;
if (fnName === 'computeProfile') {
  out = pResult;
} else if (fnName === 'computeCashFlow') {
  out = computeCashFlow(profile, pResult, opts);
} else if (fnName === 'computeRevenueCashFlow') {
  out = computeRevenueCashFlow(profile, pResult, opts);
} else {
  console.error('Unknown fn: ' + fnName);
  process.exit(2);
}

// Serialize, omitting non-JSON (functions, undefined) and trimming large arrays is fine —
// tests assert on specific values, not the full dump.
console.log(JSON.stringify(out, (key, value) => {
  if (typeof value === 'function') return undefined;
  if (typeof value === 'number' && !Number.isFinite(value)) return null;
  return value;
}));
