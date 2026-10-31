import { strict as assert } from "assert";
import {
  HOME_INDEPENDENT_TABLES,
  homeDerivedTablesResetPayload,
  planHomePageParallelLoads,
  runHomePageLoadsInParallel,
} from "./homePageParallelLoad.js";

function testIndependentTablesCoverRequestedSections() {
  for (const name of [
    "regression_summary",
    "triage_count_by_owner",
    "bulk_issues",
    "bugs_overview",
    "owner_jira_breakdown",
  ]) {
    assert.ok(HOME_INDEPENDENT_TABLES.includes(name), `missing ${name}`);
  }
}

function testPlanAlwaysIncludesSummaryAndTriage() {
  const plan = planHomePageParallelLoads({});
  assert.equal(plan.parallel, true);
  assert.ok(plan.fetches.includes("regression_summary"));
  assert.ok(plan.fetches.includes("triage_count"));
  assert.ok(!plan.fetches.includes("owner_triage_report"));
}

function testPlanIncludesAdvancedFlags() {
  const plan = planHomePageParallelLoads({
    triageCount: true,
    qiSummaryReport: true,
    triageAccuracy: true,
    tcmsOverview: true,
  });
  for (const f of [
    "owner_triage_report",
    "qi_summary",
    "triage_accuracy",
    "tcms_overview",
  ]) {
    assert.ok(plan.fetches.includes(f), `missing fetch ${f}`);
  }
}

async function testRunParallelDoesNotSerialize() {
  const order = [];
  const slow = () =>
    new Promise((resolve) => {
      setTimeout(() => {
        order.push("slow");
        resolve("slow");
      }, 40);
    });
  const fast = () =>
    new Promise((resolve) => {
      setTimeout(() => {
        order.push("fast");
        resolve("fast");
      }, 5);
    });
  const results = await runHomePageLoadsInParallel([slow, fast]);
  assert.equal(order[0], "fast", "faster loader must settle first");
  assert.equal(results.length, 2);
  assert.ok(results.every((r) => r.status === "fulfilled"));
}

async function testRunParallelSurvivesRejection() {
  const results = await runHomePageLoadsInParallel([
    async () => {
      throw new Error("boom");
    },
    async () => "ok",
  ]);
  assert.equal(results[0].status, "rejected");
  assert.equal(results[1].status, "fulfilled");
  assert.equal(results[1].value, "ok");
}

function testResetPayloadClearsTableCaches() {
  const reset = homeDerivedTablesResetPayload();
  assert.equal(reset.triageCount, null);
  assert.deepEqual(reset.ownerJiraDetails, {});
  assert.equal(reset.ownerReportRows, null);
  assert.deepEqual(reset.branchQiData, {});
}

testIndependentTablesCoverRequestedSections();
testPlanAlwaysIncludesSummaryAndTriage();
testPlanIncludesAdvancedFlags();
testResetPayloadClearsTableCaches();
await testRunParallelDoesNotSerialize();
await testRunParallelSurvivesRejection();
console.log("homePageParallelLoad.test.mjs: OK");
