/**
 * Per-field test-set argument updates for Manage TS.
 *
 * JITA's Test Sets UI reads Test Framework Options from `agave_options` and
 * Test Args from `args_map`. Listing and edits use those fields. Older JSON
 * string copies (`framework_args`, `test_args`, aliases) are ignored when the
 * canonical object field is populated, so leftover keys from earlier applies
 * are not shown or copied.
 *
 * Checkbox edits update a key only where it already exists on that TS.
 * New keys are added only via Add New Test/Framework Arg.
 */

export const FRAMEWORK_ARG_FIELDS = [
  { name: 'framework_args', kind: 'string' },
  { name: 'frameworkArgs', kind: 'string' },
  { name: 'agave_options', kind: 'object' },
];

export const TEST_ARG_FIELDS = [
  { name: 'test_args', kind: 'string' },
  { name: 'testArgs', kind: 'string' },
  { name: 'args_map', kind: 'object' },
];

const CANONICAL_NEW = {
  framework: ['framework_args', 'agave_options'],
  test: ['test_args', 'args_map'],
};

const PRIMARY_FIELD = {
  framework: 'agave_options',
  test: 'args_map',
};

export function parseArgsObject(value) {
  if (!value) return {};
  if (typeof value === 'object' && !Array.isArray(value)) return { ...value };
  if (typeof value !== 'string') return {};
  const raw = value.trim();
  if (!raw) return {};
  const attempts = [
    raw,
    raw.replace(/,\s*([}\]])/g, '$1'),
    raw.replace(/'/g, '"'),
    raw
      .replace(/'/g, '"')
      .replace(/\bTrue\b/g, 'true')
      .replace(/\bFalse\b/g, 'false')
      .replace(/\bNone\b/g, 'null')
      .replace(/,\s*([}\]])/g, '$1'),
  ];
  for (const s of attempts) {
    try {
      const parsed = JSON.parse(s);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed;
    } catch (_) {
      // try next parse shape
    }
  }
  return {};
}

function sortedArgMap(obj) {
  const out = {};
  Object.keys(obj || {})
    .sort()
    .forEach((k) => {
      out[k] = obj[k];
    });
  return out;
}

export function argMapsEqual(a, b) {
  return JSON.stringify(sortedArgMap(a)) === JSON.stringify(sortedArgMap(b));
}

/** Persist empty values as "" so JSON/JITA keep the key instead of dropping it. */
export function normalizeArgValue(value) {
  if (value === undefined || value === null) return '';
  return value;
}

/**
 * Args JITA's Test Sets UI shows for one test set. Prefer agave_options /
 * args_map; only fall back to JSON string fields when those objects are empty.
 */
export function extractCanonicalArgs(row, kind) {
  const isFramework = kind === 'framework';
  const primary = parseArgsObject(isFramework ? row?.agave_options : row?.args_map);
  if (Object.keys(primary).length > 0) return primary;
  const merged = {};
  const fallbacks = isFramework
    ? [row?.framework_args, row?.frameworkArgs]
    : [row?.test_args, row?.testArgs];
  fallbacks.forEach((item) => {
    const parsed = parseArgsObject(item);
    Object.keys(parsed).forEach((k) => {
      if (!(k in merged)) merged[k] = parsed[k];
    });
  });
  return merged;
}

export function patchArgMap(original, edits, newArgs) {
  const src = original && typeof original === 'object' && !Array.isArray(original) ? original : {};
  const originalKeys = new Set(Object.keys(src));
  const out = { ...src };
  Object.entries(edits || {}).forEach(([k, v]) => {
    if (originalKeys.has(k)) out[k] = normalizeArgValue(v);
  });
  (newArgs || []).forEach((arg) => {
    if (!arg?.key) return;
    if (originalKeys.has(arg.key) && !arg.overwrite_existing) return;
    out[arg.key] = normalizeArgValue(arg.value);
  });
  return out;
}

function serializeField(map, kind) {
  return kind === 'object' ? { ...map } : JSON.stringify(map);
}

function fieldHasKeys(row, fieldName) {
  return Object.keys(parseArgsObject(row?.[fieldName])).length > 0;
}

function applyCategory(row, fields, edits, newArgs, canonicalNames, primaryName, updates) {
  const primaryHasKeys = fieldHasKeys(row, primaryName);
  const fieldsWithKeys = fields.filter((f) => fieldHasKeys(row, f.name));
  let targets;
  if (primaryHasKeys) {
    targets = fields.filter((f) => f.name === primaryName);
  } else if (fieldsWithKeys.length > 0) {
    targets = fieldsWithKeys;
  } else if (newArgs.length > 0) {
    targets = fields.filter((f) => canonicalNames.includes(f.name));
  } else {
    targets = [];
  }

  targets.forEach((field) => {
    const original = parseArgsObject(row[field.name]);
    const patched = patchArgMap(original, edits, newArgs);
    if (argMapsEqual(original, patched)) return;
    updates[field.name] = serializeField(patched, field.kind);
  });
}

/**
 * Build JITA ts_updates for one test set. Only includes fields that actually
 * change. Checkbox edits never introduce keys; Add New can.
 */
export function buildTsUpdates(row, payload) {
  const updates = {};
  const newFw = (payload.new_arguments || []).filter((a) => a.category === 'framework' && a.key);
  const newTest = (payload.new_arguments || []).filter((a) => a.category === 'test' && a.key);
  applyCategory(
    row,
    FRAMEWORK_ARG_FIELDS,
    payload.edit_framework_args || {},
    newFw,
    CANONICAL_NEW.framework,
    PRIMARY_FIELD.framework,
    updates
  );
  applyCategory(
    row,
    TEST_ARG_FIELDS,
    payload.edit_test_args || {},
    newTest,
    CANONICAL_NEW.test,
    PRIMARY_FIELD.test,
    updates
  );
  return updates;
}
