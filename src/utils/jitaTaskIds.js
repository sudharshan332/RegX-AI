/**
 * Pure helpers for JITA task OID extract / merge / URL build.
 * Kept separate so regression tests can lock accuracy (no false IDs / dupes).
 */

export const JITA_RESULTS_BASE = "https://jita.eng.nutanix.com/results?task_ids=";
export const JITA_TASK_ID_RE = /^[0-9a-fA-F]{24}$/;

/** Normalize OID for uniqueness (JITA ObjectIds are hex; case must not create dupes). */
export function normalizeJitaTaskId(id) {
  const s = String(id || "").trim();
  if (!JITA_TASK_ID_RE.test(s)) return null;
  return s.toLowerCase();
}

/**
 * Parse JITA task OIDs from free text or a results URL.
 * If `task_ids=` is present, ONLY that query param is used (avoids false hex matches
 * elsewhere in the URL). Otherwise scan for 24-char hex tokens.
 */
export function extractJitaTaskIds(text) {
  if (!text) return [];
  const s = String(text).trim();
  const found = [];
  const seen = new Set();

  const push = (raw) => {
    const id = normalizeJitaTaskId(raw);
    if (!id || seen.has(id)) return;
    seen.add(id);
    found.push(id);
  };

  const hasTaskIdsParam = /(?:^|[?&#])task_ids=/i.test(s);
  if (hasTaskIdsParam) {
    try {
      const url = new URL(s.startsWith("http") ? s : `https://dummy.local/?${s.replace(/^[?&]/, "")}`);
      const param = url.searchParams.get("task_ids");
      if (param) {
        param.split(",").forEach((tid) => push(tid));
        return found;
      }
    } catch (_) {
      // Fall through to regex capture of task_ids=...
      const m = s.match(/task_ids=([^&\s#]+)/i);
      if (m) {
        decodeURIComponent(m[1]).split(",").forEach((tid) => push(tid));
        return found;
      }
    }
  }

  // Plain list / single IDs — only whole 24-char hex tokens (word-ish boundaries)
  const tokenRe = /(?:^|[^0-9a-fA-F])([0-9a-fA-F]{24})(?![0-9a-fA-F])/g;
  let match;
  while ((match = tokenRe.exec(s)) !== null) {
    push(match[1]);
  }
  return found;
}

/** Normalize unique task OIDs (order preserved). */
export function normalizeJitaTaskIdList(taskIds = []) {
  const ids = [];
  const seen = new Set();
  (taskIds || []).forEach((raw) => {
    const id = normalizeJitaTaskId(raw);
    if (!id || seen.has(id)) return;
    seen.add(id);
    ids.push(id);
  });
  return ids;
}

/** Build canonical JITA results link from task OIDs (Regression_Run_Tasks). */
export function buildJitaResultsUrl(taskIds = []) {
  const ids = normalizeJitaTaskIdList(taskIds);
  if (ids.length === 0) return null;
  return `${JITA_RESULTS_BASE}${ids.join(",")}&active_tab=1&merge_tests=true`;
}

/**
 * Same URL as JITA Tests → "View in Triage Genie" for a results task set.
 * http://triage-genie.eng.nutanix.com/?jita_task_ids=<ids>
 */
export function buildViewInTriageGenieUrl(taskIds = []) {
  const ids = normalizeJitaTaskIdList(taskIds);
  if (ids.length === 0) return null;
  return `http://triage-genie.eng.nutanix.com/?jita_task_ids=${ids.join(",")}`;
}

/**
 * Merge new IDs into base (order preserved, unique, lowercased).
 * Returns { merged, added, duplicates }.
 */
export function mergeJitaTaskIds(baseIds = [], incomingTextOrIds) {
  const base = [];
  const seen = new Set();
  (baseIds || []).forEach((raw) => {
    const id = normalizeJitaTaskId(raw);
    if (!id || seen.has(id)) return;
    seen.add(id);
    base.push(id);
  });

  const incoming = Array.isArray(incomingTextOrIds)
    ? incomingTextOrIds.flatMap((x) => extractJitaTaskIds(String(x)))
    : extractJitaTaskIds(incomingTextOrIds);

  const added = [];
  const duplicates = [];
  incoming.forEach((id) => {
    if (seen.has(id)) duplicates.push(id);
    else {
      seen.add(id);
      base.push(id);
      added.push(id);
    }
  });

  return { merged: base, added, duplicates };
}
