/**
 * Regression Dashboard Home — independent / progressive table loads.
 *
 * These sections must not block each other: whichever API returns first
 * should render first. Callers fire the matching loaders together
 * (e.g. Promise.allSettled) and never await them one-after-another.
 */

export const HOME_INDEPENDENT_TABLES = [
  "regression_summary",
  "triage_count_by_owner",
  "bulk_issues",
  "bugs_overview",
  "owner_jira_breakdown",
];

/**
 * Which background fetches to start for a Home job (tag / task_ids) change.
 * Summary + triage-count are always started; optional advanced sections follow flags.
 * Bugs Overview / Owner-wise Jira breakdown hydrate from triage-count then JIRA details.
 */
export function planHomePageParallelLoads(advancedOptions = {}) {
  const fetches = ["regression_summary", "triage_count"];
  if (advancedOptions.triageCount) fetches.push("owner_triage_report");
  if (advancedOptions.qiSummaryReport) fetches.push("qi_summary");
  if (advancedOptions.triageAccuracy) fetches.push("triage_accuracy");
  if (advancedOptions.tcmsOverview) fetches.push("tcms_overview");
  return {
    parallel: true,
    tables: [...HOME_INDEPENDENT_TABLES],
    fetches,
  };
}

/**
 * Run Home loaders concurrently. Does not short-circuit on the first failure.
 * @param {Array<() => (void|Promise<unknown>)>} loaders
 * @returns {Promise<PromiseSettledResult<unknown>[]>}
 */
export function runHomePageLoadsInParallel(loaders = []) {
  const jobs = (loaders || [])
    .filter((fn) => typeof fn === "function")
    .map((fn) => Promise.resolve().then(fn));
  return Promise.allSettled(jobs);
}

/**
 * Derived Home table caches to drop when the selected job changes so each
 * section can show its own loading state instead of stale rows.
 */
export function homeDerivedTablesResetPayload() {
  return {
    triageCount: null,
    ownerJiraDetails: {},
    jiraDetailsError: null,
    bulkIssuesAiAnalysis: null,
    ownerTicketsAiAnalysis: null,
    ownerReportRows: null,
    ownerReportMeta: null,
    ownerReportError: null,
    ownerReportInvalid: [],
    triageAccuracyData: null,
    qiSummaryReport: null,
    tcmsOverviewData: null,
    jitaTcmsComparison: null,
    branchQiData: {},
  };
}
