/**
 * Run: node src/utils/manageTestSetArgs.test.mjs
 */
import { argMapsEqual, buildTsUpdates, extractCanonicalArgs, parseArgsObject, patchArgMap } from './manageTestSetArgs.js';

let failed = 0;
function assert(cond, msg) {
  if (!cond) {
    failed += 1;
    console.error('FAIL:', msg);
  } else {
    console.log('OK:', msg);
  }
}

assert(JSON.stringify(parseArgsObject("{'a': 1}")) === JSON.stringify({ a: 1 }), 'parse python-ish dict');
assert(argMapsEqual({ b: 1, a: 2 }, { a: 2, b: 1 }), 'argMapsEqual ignores key order');

const canonical = extractCanonicalArgs({
  args_map: { a1: 1, c1: 1 },
  test_args: '{"abc":"stale","hello":"stale"}',
  testArgs: '{"xyz":"stale"}',
  agave_options: { z1: 1 },
  framework_args: '{"abc":"stale"}',
}, 'test');
assert(JSON.stringify(canonical) === JSON.stringify({ a1: 1, c1: 1 }), 'display uses args_map, not stale test_args strings');
assert(JSON.stringify(extractCanonicalArgs({
  agave_options: { z1: 1 },
  framework_args: '{"abc":"stale"}',
}, 'framework')) === JSON.stringify({ z1: 1 }), 'display uses agave_options, not stale framework_args');

const fallback = extractCanonicalArgs({
  args_map: {},
  test_args: '{"seed":"1"}',
}, 'test');
assert(fallback.seed === '1', 'fall back to test_args when args_map is empty');

const patchedEdit = patchArgMap({ seed: '1' }, { seed: '2', extra: 'nope' }, []);
assert(patchedEdit.seed === '2', 'edit updates existing key');
assert(!Object.prototype.hasOwnProperty.call(patchedEdit, 'extra'), 'edit does not add missing key');

const patchedNew = patchArgMap({ seed: '1' }, {}, [
  { key: 'flag', value: 'on', overwrite_existing: false },
]);
assert(patchedNew.flag === 'on' && patchedNew.seed === '1', 'add new key keeps original keys');

const skipCollision = patchArgMap({ seed: '1' }, {}, [
  { key: 'seed', value: '9', overwrite_existing: false },
]);
assert(skipCollision.seed === '1', 'add new skips existing without overwrite');

const tsA = {
  test_args: '{"timeout":"10"}',
  args_map: {},
  agave_options: { env: 'prod' },
};
const tsB = {
  test_args: '',
  args_map: { other: 'x' },
  agave_options: {},
};

const editTimeout = {
  edit_framework_args: {},
  edit_test_args: { timeout: '20' },
  new_arguments: [],
};

const updatesA = buildTsUpdates(tsA, editTimeout);
assert(updatesA.test_args === '{"timeout":"20"}', `TS-A test_args updated, got ${updatesA.test_args}`);
assert(updatesA.args_map === undefined, 'TS-A empty args_map is not populated from other keys');
assert(updatesA.testArgs === undefined, 'TS-A missing testArgs is not created');

const updatesB = buildTsUpdates(tsB, editTimeout);
assert(updatesB.args_map === undefined, 'TS-B does not receive timeout from TS-A');
assert(updatesB.test_args === undefined, 'TS-B empty test_args is not populated from union');
assert(JSON.stringify(updatesB) === '{}', `TS-B checkbox edits must be a no-op, got ${JSON.stringify(updatesB)}`);

const disjoint = {
  test_args: '{"only_in_string":"1"}',
  args_map: { only_in_map: '2' },
};
const editStringOnly = {
  edit_test_args: { only_in_string: '9', only_in_map: '9' },
  edit_framework_args: {},
  new_arguments: [],
};
const disjointUpdates = buildTsUpdates(disjoint, editStringOnly);
assert(disjointUpdates.test_args === undefined, 'do not patch stale test_args when args_map is populated');
assert(disjointUpdates.args_map.only_in_map === '9', 'map field patched in place');
assert(!Object.prototype.hasOwnProperty.call(disjointUpdates.args_map, 'only_in_string'), 'do not copy string key into args_map');

const leftoverOnly = buildTsUpdates(
  { args_map: { a1: 1 }, test_args: '{"abc":"stale"}' },
  { edit_framework_args: {}, edit_test_args: { abc: 'nope' }, new_arguments: [] }
);
assert(JSON.stringify(leftoverOnly) === '{}', 'leftover string-only keys are not editable when args_map exists');

const emptyTs = { test_args: '', args_map: {}, framework_args: '' };
const addNew = {
  edit_framework_args: {},
  edit_test_args: { timeout: '20' },
  new_arguments: [{ key: 'new_flag', value: '1', category: 'test', overwrite_existing: false }],
};
const created = buildTsUpdates(emptyTs, addNew);
assert(created.args_map.new_flag === '1', 'Add New writes canonical args_map');
assert(JSON.parse(created.test_args).new_flag === '1', 'Add New writes canonical test_args');
assert(created.testArgs === undefined, 'Add New does not create unused testArgs alias');
assert(!Object.prototype.hasOwnProperty.call(created.args_map, 'timeout'), 'Add New does not copy checkbox keys onto empty TS');

const emptyAdd = buildTsUpdates(emptyTs, {
  edit_framework_args: {},
  edit_test_args: {},
  new_arguments: [{ key: 'blank', value: '', category: 'test', overwrite_existing: false }],
});
assert(Object.prototype.hasOwnProperty.call(emptyAdd.args_map, 'blank'), 'Add New keeps key when value is empty');
assert(emptyAdd.args_map.blank === '', 'empty Add New value is stored as empty string');
assert(JSON.parse(emptyAdd.test_args).blank === '', 'empty Add New value is serialized in test_args');

const emptyEdit = buildTsUpdates(
  { args_map: { a1: 'old', b1: 'keep' } },
  { edit_framework_args: {}, edit_test_args: { a1: '' }, new_arguments: [] }
);
assert(emptyEdit.args_map.a1 === '', 'checkbox edit can clear a value');
assert(emptyEdit.args_map.b1 === 'keep', 'clearing one key does not drop others');

const missingValue = patchArgMap({ seed: '1' }, { seed: null }, [
  { key: 'flag', overwrite_existing: false },
]);
assert(missingValue.seed === '', 'null edit value becomes empty string');
assert(missingValue.flag === '', 'missing Add New value becomes empty string');

const many = {};
const manyEdits = {};
for (let i = 0; i < 80; i += 1) {
  many[`k${i}`] = String(i);
  manyEdits[`k${i}`] = i % 2 === 0 ? '' : `v${i}`;
}
const manyNew = [];
for (let i = 0; i < 40; i += 1) {
  manyNew.push({ key: `n${i}`, value: i === 0 ? '' : `new${i}`, category: 'test', overwrite_existing: false });
}
const manyOut = buildTsUpdates(
  { args_map: many },
  { edit_framework_args: {}, edit_test_args: manyEdits, new_arguments: manyNew }
);
assert(Object.keys(manyOut.args_map).length === 120, `80 edits + 40 new keys, got ${Object.keys(manyOut.args_map).length}`);
assert(manyOut.args_map.k0 === '', 'many-arg edit can set empty');
assert(manyOut.args_map.k1 === 'v1', 'many-arg edit keeps non-empty');
assert(manyOut.args_map.n0 === '', 'many-arg Add New can set empty');
assert(manyOut.args_map.n39 === 'new39', 'last of many new keys is written');

const mixedTs = {
  args_map: { shared: '1', onlyA: 'a' },
};
const mixedPayload = {
  edit_framework_args: {},
  edit_test_args: { shared: '', onlyA: 'aa', onlyB: 'nope' },
  new_arguments: [
    { key: 'added', value: '', category: 'test', overwrite_existing: false },
    { key: 'added', value: 'last', category: 'test', overwrite_existing: true },
  ],
};
const mixedOut = buildTsUpdates(mixedTs, mixedPayload);
assert(mixedOut.args_map.shared === '', 'empty edit on existing key');
assert(mixedOut.args_map.onlyA === 'aa', 'non-empty edit on existing key');
assert(!Object.prototype.hasOwnProperty.call(mixedOut.args_map, 'onlyB'), 'edit does not add missing key among many');
assert(mixedOut.args_map.added === 'last', 'duplicate Add New rows: last value wins');

if (failed) {
  console.error(`\n${failed} test(s) failed`);
  process.exit(1);
}
console.log('\nAll manageTestSetArgs tests passed');
