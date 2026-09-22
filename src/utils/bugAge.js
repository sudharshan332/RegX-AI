/**
 * Classify Jira tickets as new vs old relative to the regression run start.
 * New = filed on/after run start. Old = filed before run start.
 */

export function parseTimestamp(value) {
  if (!value) return null;
  if (value instanceof Date) {
    const ms = value.getTime();
    return Number.isNaN(ms) ? null : ms;
  }
  const s = String(value).trim();
  if (!s) return null;
  const normalized = s.includes("T") ? s : s.replace(" ", "T");
  // Jira returns +0000; Date.parse in some browsers needs +00:00.
  const withOffset = normalized.replace(/([+-]\d{2})(\d{2})$/, "$1:$2");
  const ms = new Date(withOffset).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function classifyBugAge(created, runStart) {
  const createdMs = parseTimestamp(created);
  const startMs = parseTimestamp(runStart);
  if (createdMs == null || startMs == null) return null;
  return createdMs >= startMs ? "new" : "old";
}

export function resolveRunStartDate(oldestStartDate, rows = []) {
  if (oldestStartDate) return oldestStartDate;
  const dates = (rows || []).map((r) => r && r.startDate).filter(Boolean);
  if (!dates.length) return null;
  return dates.reduce((earliest, d) => {
    const dMs = parseTimestamp(d);
    const eMs = parseTimestamp(earliest);
    if (dMs == null) return earliest;
    if (eMs == null || dMs < eMs) return d;
    return earliest;
  });
}
