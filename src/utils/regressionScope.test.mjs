/**
 * Run: node src/utils/regressionScope.test.mjs
 *
 * Uses a minimal localStorage stub (Node has none).
 */
import { createRequire } from "module";

const require = createRequire(import.meta.url);

// Stub browser storage before importing module under test
const store = new Map();
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
};

const {
  readScopedFullRegressionTaskIds,
  persistFullRegressionLink,
  clearFullRegressionLink,
  readRegressionScopeFromLocalStorage,
  scopeToQueryParams,
  scopeToRequestPayload,
  shouldPostTriageScope,
  TG_SCOPE_POST_THRESHOLD,
  FULL_LINK_TAG_KEY,
  FULL_LINK_TASK_IDS_KEY,
  DASHBOARD_TAG_KEY,
  DASHBOARD_MODE_KEY,
} = await import("./regressionScope.js");

let failed = 0;
function assert(cond, msg) {
  if (!cond) {
    failed += 1;
    console.error("FAIL:", msg);
  } else {
    console.log("OK:", msg);
  }
}

const A = "aaaaaaaaaaaaaaaaaaaaaaaa";
const B = "bbbbbbbbbbbbbbbbbbbbbbbb";
const C = "cccccccccccccccccccccccc";

store.clear();
localStorage.setItem(DASHBOARD_MODE_KEY, "tag");
localStorage.setItem(DASHBOARD_TAG_KEY, "7.6|RC1-june-15-2026");
persistFullRegressionLink([A, B], "7.6|RC1-june-15-2026");
assert(
  JSON.stringify(readScopedFullRegressionTaskIds("7.6|RC1-june-15-2026")) ===
    JSON.stringify([A, B]),
  "scoped IDs returned for matching tag"
);

localStorage.setItem(DASHBOARD_TAG_KEY, "7.6|other-job");
assert(
  readScopedFullRegressionTaskIds("7.6|other-job").length === 0,
  "foreign tag must NOT reuse prior job Full regression IDs"
);

clearFullRegressionLink();
persistFullRegressionLink([A, C], "7.6|other-job");
localStorage.setItem(DASHBOARD_TAG_KEY, "7.6|other-job");
const scope = readRegressionScopeFromLocalStorage();
assert(scope.tag === "7.6|other-job", "scope tag");
assert(
  JSON.stringify(scope.taskIds) === JSON.stringify([A, C]),
  "scope taskIds for selected job only"
);

const params = scopeToQueryParams(scope);
assert(params.tag === "7.6|other-job", "query keeps tag for label/cache");
assert(params.task_ids === `${A},${C}`, "Full-link task_ids win (View in Triage Genie scope)");

const payload = scopeToRequestPayload(scope);
assert(Array.isArray(payload.task_ids) && payload.task_ids.join(",") === `${A},${C}`, "payload has task_ids array");
assert(payload.tag === "7.6|other-job", "payload keeps tag");

const tagOnly = scopeToQueryParams({ mode: "tag", tag: "7.6|orphan", taskIds: null });
assert(tagOnly.tag === "7.6|orphan", "tag-only fallback sends tag");
assert(tagOnly.task_ids == null, "tag-only fallback has no task_ids");

const taskOnly = scopeToQueryParams({ mode: "task_ids", tag: null, taskIds: [A, C] });
assert(taskOnly.task_ids === `${A},${C}`, "task_ids mode sends Full regression ids");
assert(taskOnly.tag == null, "task_ids mode has no tag");

const many = Array.from({ length: TG_SCOPE_POST_THRESHOLD + 1 }, (_, i) =>
  i.toString(16).padStart(24, "a")
);
assert(shouldPostTriageScope({ taskIds: many }) === true, "large Full link uses POST");
assert(shouldPostTriageScope({ taskIds: [A, C] }) === false, "small Full link can use GET");

assert(localStorage.getItem(FULL_LINK_TAG_KEY) === "7.6|other-job", "link tag persisted");
assert(
  localStorage.getItem(FULL_LINK_TASK_IDS_KEY) === JSON.stringify([A, C]),
  "link task ids persisted"
);

if (failed) {
  console.error(`\n${failed} failed`);
  process.exit(1);
}
console.log("\nAll regressionScope tests passed");
// silence unused require lint in some runners
void require;
