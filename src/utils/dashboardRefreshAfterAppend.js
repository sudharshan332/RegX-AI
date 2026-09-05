/**
 * Plan which dashboard scopes to reload after "+" accepts new JITA task IDs.
 * Pure helper — keeps RegressionHome refresh behavior testable.
 */

export function planDashboardRefreshAfterAppend({
  sourceTag,
  inputMode,
  advancedOptions = {},
  acceptedCount = 0,
}) {
  if (!acceptedCount) {
    return { shouldRefresh: false, mode: null, scopes: [] };
  }
  const mode = sourceTag && inputMode === "tag" ? "tag" : "task_ids";
  const scopes = ["summary", "triage_count", "tickets_via_triage"];
  if (advancedOptions.triageCount) scopes.push("owner_triage_report");
  if (advancedOptions.qiSummaryReport) scopes.push("qi_summary");
  if (advancedOptions.triageAccuracy) scopes.push("triage_accuracy");
  scopes.push("clear_branch_tcms_qi_cache");
  scopes.push("clear_owner_jira_cache");
  return { shouldRefresh: true, mode, scopes };
}

/** True when new triage ticket set needs a JIRA details refetch. */
export function shouldRefetchOwnerJiraDetails(ownerTicketMap, cachedDetails = {}) {
  if (!ownerTicketMap || typeof ownerTicketMap !== "object") return false;
  const allTickets = new Set();
  Object.values(ownerTicketMap).forEach((tickets) => {
    Object.keys(tickets || {}).forEach((t) => allTickets.add(t));
  });
  if (allTickets.size === 0) return false;
  const cachedKeys = new Set(Object.keys(cachedDetails || {}));
  if (cachedKeys.size === 0) return true;
  if (allTickets.size !== cachedKeys.size) return true;
  return [...allTickets].some((t) => !cachedKeys.has(t));
}
