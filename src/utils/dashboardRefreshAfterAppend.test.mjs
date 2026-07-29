import { strict as assert } from "assert";
import {
  planDashboardRefreshAfterAppend,
  shouldRefetchOwnerJiraDetails,
} from "./dashboardRefreshAfterAppend.js";

function testPlanTagModeAllScopes() {
  const plan = planDashboardRefreshAfterAppend({
    sourceTag: "my-tag",
    inputMode: "tag",
    acceptedCount: 2,
    advancedOptions: {
      triageCount: true,
      qiSummaryReport: true,
      triageAccuracy: true,
    },
  });
  assert.equal(plan.shouldRefresh, true);
  assert.equal(plan.mode, "tag");
  for (const s of [
    "summary",
    "triage_count",
    "tickets_via_triage",
    "owner_triage_report",
    "qi_summary",
    "triage_accuracy",
    "clear_branch_tcms_qi_cache",
    "clear_owner_jira_cache",
  ]) {
    assert.ok(plan.scopes.includes(s), `missing scope ${s}`);
  }
}

function testPlanNoAcceptNoRefresh() {
  const plan = planDashboardRefreshAfterAppend({
    sourceTag: "my-tag",
    inputMode: "tag",
    acceptedCount: 0,
  });
  assert.equal(plan.shouldRefresh, false);
}

function testPlanTaskIdsWhenNoTag() {
  const plan = planDashboardRefreshAfterAppend({
    sourceTag: "",
    inputMode: "tag",
    acceptedCount: 1,
  });
  assert.equal(plan.mode, "task_ids");
}

function testJiraRefetchOnNewTickets() {
  assert.equal(
    shouldRefetchOwnerJiraDetails({ alice: { "ENG-1": ["t"] } }, {}),
    true
  );
  assert.equal(
    shouldRefetchOwnerJiraDetails(
      { alice: { "ENG-1": ["t"] } },
      { "ENG-1": { status: "Open" } }
    ),
    false
  );
  assert.equal(
    shouldRefetchOwnerJiraDetails(
      { alice: { "ENG-1": ["t"], "ENG-2": ["t"] } },
      { "ENG-1": { status: "Open" } }
    ),
    true,
    "new ticket ENG-2 must trigger refetch"
  );
}

testPlanTagModeAllScopes();
testPlanNoAcceptNoRefresh();
testPlanTaskIdsWhenNoTag();
testJiraRefetchOnNewTickets();
console.log("dashboardRefreshAfterAppend.test.mjs: OK");
