import { strict as assert } from "assert";
import { classifyBugAge, parseTimestamp, resolveRunStartDate } from "./bugAge.js";

assert.equal(classifyBugAge("2026-09-21T10:00:00.000+0000", "2026-09-20 09:00:00"), "new");
assert.equal(classifyBugAge("2026-09-21T10:00:00.000+00:00", "2026-09-20 09:00:00"), "new");
assert.equal(classifyBugAge("2026-09-19T10:00:00.000+0000", "2026-09-20 09:00:00"), "old");
assert.equal(classifyBugAge("2026-09-20T09:00:00", "2026-09-20 09:00:00"), "new");
assert.equal(classifyBugAge(null, "2026-09-20 09:00:00"), null);
assert.equal(classifyBugAge("2026-09-21T10:00:00.000+0000", null), null);
assert.ok(parseTimestamp("2026-09-20 09:00:00") > 0);

assert.equal(
  resolveRunStartDate("2026-09-01 08:00:00", [{ startDate: "2026-09-10 08:00:00" }]),
  "2026-09-01 08:00:00",
);
assert.equal(
  resolveRunStartDate(null, [
    { startDate: "2026-09-10 08:00:00" },
    { startDate: "2026-09-01 08:00:00" },
  ]),
  "2026-09-01 08:00:00",
);
assert.equal(resolveRunStartDate(null, []), null);

console.log("bugAge tests passed");
