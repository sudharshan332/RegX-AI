/**
 * Run: node src/utils/jitaTaskIds.test.mjs
 */
import {
  extractJitaTaskIds,
  buildJitaResultsUrl,
  buildJitaResultsUrls,
  buildViewInTriageGenieUrl,
  mergeJitaTaskIds,
  normalizeJitaTaskId,
} from "./jitaTaskIds.js";

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
const A_UP = "AAAAAAAAAAAAAAAAAAAAAAAA";

assert(normalizeJitaTaskId(A_UP) === A, "normalize lowercases");
assert(normalizeJitaTaskId("short") === null, "reject short");
assert(normalizeJitaTaskId("zzzzzzzzzzzzzzzzzzzzzzzz") === null, "reject non-hex");

const url =
  `https://jita.eng.nutanix.com/results?task_ids=${A},${B}&active_tab=1&merge_tests=true&x=${C}`;
const fromUrl = extractJitaTaskIds(url);
assert(JSON.stringify(fromUrl) === JSON.stringify([A, B]), `URL extract only task_ids, got ${JSON.stringify(fromUrl)}`);
assert(!fromUrl.includes(C), "must NOT pick C from unrelated query param");

assert(
  JSON.stringify(extractJitaTaskIds(`${A}, ${B}, ${A_UP}`)) === JSON.stringify([A, B]),
  "plain list unique + casefold"
);

assert(
  JSON.stringify(extractJitaTaskIds(`${A}\n${B}\n${C}`)) === JSON.stringify([A, B, C]),
  "newline-separated IDs"
);

assert(
  JSON.stringify(extractJitaTaskIds(`${A}${B}`)) === JSON.stringify([]),
  "adjacent 48-hex without separator → no false split"
);

const m1 = mergeJitaTaskIds([A, B], `${B},${C}`);
assert(JSON.stringify(m1.merged) === JSON.stringify([A, B, C]), "merge append unique");
assert(JSON.stringify(m1.added) === JSON.stringify([C]), "added only C");
assert(JSON.stringify(m1.duplicates) === JSON.stringify([B]), "dup B reported");

const m2 = mergeJitaTaskIds([A], A_UP);
assert(m2.added.length === 0 && m2.merged.length === 1, "case-variant is duplicate");

const built = buildJitaResultsUrl([A, B, A_UP]);
assert(
  built ===
    `https://jita.eng.nutanix.com/results?task_ids=${A},${B}&active_tab=1&merge_tests=true`,
  "build URL unique lowercase"
);
assert(buildJitaResultsUrl([]) === null, "empty → null");
assert(buildJitaResultsUrl(["nope"]) === null, "invalid → null");

const smallUrls = buildJitaResultsUrls([A, B]);
assert(smallUrls.length === 1, "small list is one JITA URL");
assert(smallUrls[0] === built, "single chunk matches buildJitaResultsUrl");

const many = [];
for (let i = 0; i < 400; i += 1) {
  many.push(`b${i.toString(16).padStart(23, "0")}`);
}
const chunked = buildJitaResultsUrls(many);
assert(chunked.length > 1, "400 IDs split into multiple JITA URLs");
assert(
  chunked.every((u) => u.length <= 7800),
  "each JITA chunk stays under Apache GET limit"
);
const fromChunks = chunked.flatMap((u) => extractJitaTaskIds(u));
assert(fromChunks.length === 400, `chunks cover all IDs, got ${fromChunks.length}`);
assert(fromChunks[0] === many[0] && fromChunks[399] === many[399], "chunk order preserved");

const { merged } = mergeJitaTaskIds([A], `https://jita.eng.nutanix.com/results?task_ids=${B},${A}`);
const round = extractJitaTaskIds(buildJitaResultsUrl(merged));
assert(JSON.stringify(round) === JSON.stringify([A, B]), "round-trip stable");

// Simulate tag extras: tag-fetched IDs + newly appended must stay unique for next tag fetch
const tagFetched = [A, B];
const userAppended = [B, C]; // B already in tag
const forPersist = mergeJitaTaskIds([], userAppended); // what we POST as newly_added candidates
assert(JSON.stringify(forPersist.merged) === JSON.stringify([B, C]), "persist payload unique");
const nextTagFetchUnion = mergeJitaTaskIds(tagFetched, forPersist.merged);
assert(
  JSON.stringify(nextTagFetchUnion.merged) === JSON.stringify([A, B, C]),
  "next tag fetch must include prior tag tasks + extras (no miss, no dupe)"
);
assert(nextTagFetchUnion.added.length === 1 && nextTagFetchUnion.added[0] === C, "only C is new vs tag set");

assert(
  buildViewInTriageGenieUrl([A, B]) ===
    `http://triage-genie.eng.nutanix.com/view_tasks?jita_task_ids=${A},${B}`,
  "View in TG matches JITA /view_tasks?jita_task_ids="
);
assert(buildViewInTriageGenieUrl([]) === null, "empty TG → null");

if (failed) {
  console.error(`\n${failed} assertion(s) failed`);
  process.exit(1);
}
console.log("\nAll jitaTaskIds regression checks passed.");
