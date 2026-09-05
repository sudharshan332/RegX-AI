/**
 * Prompt templates for Cursor agent testcase analysis.
 *
 * Instead of custom prompts, the agent reads and follows the actual skill files
 * from the nutest-py3-tests repo on Sourcegraph:
 *   - triage-cdp-test-failure skill for failed testcase triage
 *   - triage-rdm-deployment-failure skill for skipped testcase triage
 *
 * The skill files contain the complete triage methodology, log access tiers,
 * JIRA integration, Sourcegraph deep-dives, and report generation.
 */

const NUTEST_REPO = "nugerrit.ntnxdpro.com/nutest-py3-tests";
const SKILL_BASE = ".cursor/skills";

const CDP_SKILL_DIR = `${SKILL_BASE}/triage-cdp-test-failure`;

// All files in the triage-cdp-test-failure skill directory.
// The agent must read these via Sourcegraph during triage.
const CDP_SKILL_FILES = [
  `${CDP_SKILL_DIR}/SKILL.md`,
  `${CDP_SKILL_DIR}/archived-logs-reference.md`,
  `${CDP_SKILL_DIR}/ingest-reference.md`,
  `${CDP_SKILL_DIR}/extract-reference.md`,
  `${CDP_SKILL_DIR}/investigate-reference.md`,
  `${CDP_SKILL_DIR}/failure-patterns-reference.md`,
  `${CDP_SKILL_DIR}/jira-reference.md`,
  `${CDP_SKILL_DIR}/jita-task-mode-reference.md`,
  `${CDP_SKILL_DIR}/report-template-reference.md`,
  `${CDP_SKILL_DIR}/sourcegraph-reference.md`,
  `${CDP_SKILL_DIR}/live-cluster-reference.md`,
  `${CDP_SKILL_DIR}/telemetry-reference.md`,
  `${CDP_SKILL_DIR}/setup-guide.md`,
  `${CDP_SKILL_DIR}/jira_helper.py`,
];

const RDM_SKILL_DIR = `${SKILL_BASE}/triage-rdm-deployment-failure`;

/**
 * Build the prompt for analyzing a FAILED testcase.
 *
 * The agent reads the triage-cdp-test-failure SKILL.md from Sourcegraph and
 * executes its full workflow with the JITA log directory URL as input.
 */
export function buildFailedAnalysisPrompt(opts) {
  const {
    testcaseName = "",
    exceptionSummary = "",
    exception = "",
    stepsLog = "",
    nutestTestLog = "",
    testLogUrl = "",
    jiraTickets = [],
    failureStage = "",
    triageGenieTicket = "",
    gleanTickets = [],
    gleanSnippets = [],
  } = opts;

  const jiraLine = jiraTickets.length
    ? `- **Linked Jira:** ${jiraTickets.join(", ")}\n`
    : "";
  const tgLine = triageGenieTicket
    ? `- **Triage Genie suggested ticket:** ${triageGenieTicket}\n`
    : "- **Triage Genie suggested ticket:** none\n";
  const gleanTicketLines = (gleanTickets || []).slice(0, 8).map((t) => {
    const key = t.ticket || t;
    const summary = t.jira_summary || t.glean_title || t.title || "";
    const status = t.jira_status || "";
    return `  - ${key}${status ? ` [${status}]` : ""}${summary ? ` — ${summary}` : ""}`;
  });
  const gleanBlock = gleanTicketLines.length
    ? `- **Existing tickets from error-message search:**\n${gleanTicketLines.join("\n")}\n`
    : "- **Existing tickets from error-message search:** none pre-fetched; search Glean yourself.\n";
  const snippetBlock = (gleanSnippets || []).slice(0, 4).map((s) =>
    `  - ${s.title || "Untitled"}: ${(s.snippet || "").slice(0, 180)}`
  ).join("\n");

  const fileList = CDP_SKILL_FILES
    .map((f, i) => `${i + 1}. \`${f}\``)
    .join("\n");

  return `## Your Task

You are triaging a failed nutest testcase. You MUST follow the
**triage-cdp-test-failure** skill from the nutest-py3-tests repository.

### Step 1 — Load skill guidance (lazy, not all files)

Use the **gw-sourcegraph** MCP server (\`sourcegraph__read_file\`).
Repo: \`${NUTEST_REPO}\`.

1. Read \`${CDP_SKILL_DIR}/SKILL.md\` first (entry point).
2. Read additional reference files **only as the workflow requires them**
   (do not preload every file). Available references:
${fileList}
3. If a service-specific flow is needed, list \`${CDP_SKILL_DIR}/flows/\`
   and read only the matching flow file.

Prefer speed: gather enough evidence for a confident root cause, then stop.

### Step 2 — Execute the skill with this input

The triage mode is **Archived Logs Mode**. The log directory URL is:

\`\`\`
${testLogUrl || "NO LOG URL PROVIDED"}
\`\`\`

**Testcase context (for reference — the skill workflow will guide you):**
- **Testcase:** ${testcaseName}
- **Failure Stage:** ${failureStage || "Unknown"}
${jiraLine}${tgLine}${gleanBlock}${snippetBlock ? `- **Glean snippets:**\n${snippetBlock}\n` : ""}- **Exception Summary:** ${exceptionSummary || "N/A"}

Exception / Traceback:
\`\`\`
${(exception || "N/A").slice(0, 5000)}
\`\`\`

${stepsLog ? `steps.log snippet:\n\`\`\`\n${stepsLog.slice(0, 3000)}\n\`\`\`\n` : ""}
${nutestTestLog ? `nutest_test.log snippet:\n\`\`\`\n${nutestTestLog.slice(0, 3000)}\n\`\`\`\n` : ""}

### Step 2b — Glean product knowledge and ticket validation

Whenever product knowledge or an existing JIRA ticket is needed, use the
**gw-glean** MCP:
- \`glean__company_search\` with \`datasources: ["jira"]\` and the exception /
  error message to find existing ENG tickets.
- \`glean__company_search\` (or \`glean__chat\`) without a Jira-only filter
  for product docs / known issues.

Validate whether the Triage Genie suggested ticket is **Correct** or
**Incorrect** for THIS failure. A similar ticket is a hypothesis, not proof.

### Step 3 — Return structured results

After completing the skill's triage workflow, return your findings as JSON:

\`\`\`json
{
  "root_cause": "Evidence-backed root cause explanation (observed/inferred/unknown per skill discipline)",
  "classification": "Test Issue | Product Issue | Infra Issue | Flaky / Timing",
  "failing_code": {
    "file": "path/to/file",
    "line_range": "start-end",
    "snippet": "relevant code"
  },
  "suggested_fix": "Actionable fix or next step",
  "confidence": "High | Medium | Low",
  "related_components": ["service1", "service2"],
  "jira_duplicates": ["ENG-XXXXX"],
  "tg_ticket_validation": {
    "ticket": "ENG-XXXXX or empty",
    "verdict": "Correct | Incorrect | Partial | Missing",
    "reason": "why the Triage Genie ticket is or is not the right ticket"
  },
  "triage_report": "The full JIRA wiki markup report as generated by the skill"
}
\`\`\`

Respond ONLY with the JSON block.`;
}

/**
 * Build the prompt for analyzing a SKIPPED testcase.
 *
 * The agent reads the triage-rdm-deployment-failure SKILL.md from Sourcegraph
 * and executes its workflow.
 */
export function buildSkippedAnalysisPrompt(opts) {
  const {
    testcaseName = "",
    exceptionSummary = "",
    exception = "",
    stepsLog = "",
    nutestTestLog = "",
    testLogUrl = "",
    rdmUrl = "",
    rdmMessage = "",
    jitaTaskId = "",
    jiraTickets = [],
    failureStage = "",
    triageGenieTicket = "",
    gleanTickets = [],
    gleanSnippets = [],
  } = opts;

  const skillInputUrl = rdmUrl || testLogUrl || "";
  const jitaLine = jitaTaskId
    ? `- **JITA task:** https://jita.eng.nutanix.com/results?task_ids=${jitaTaskId}\n`
    : "";
  const rdmLine = rdmUrl
    ? `- **RDM deployment:** ${rdmUrl}\n`
    : "";
  const jiraLine = jiraTickets.length
    ? `- **Linked Jira:** ${jiraTickets.join(", ")}\n`
    : "";
  const tgLine = triageGenieTicket
    ? `- **Triage Genie suggested ticket:** ${triageGenieTicket}\n`
    : "- **Triage Genie suggested ticket:** none\n";
  const gleanLine = (gleanTickets || []).length
    ? `- **Existing tickets from error search:** ${(gleanTickets || []).slice(0, 6).map((t) => t.ticket || t).join(", ")}\n`
    : "- **Existing tickets from error search:** none pre-fetched; search Glean yourself.\n";
  const snippetBlock = (gleanSnippets || []).slice(0, 4).map((s) =>
    `  - ${s.title || "Untitled"}: ${(s.snippet || "").slice(0, 180)}`
  ).join("\n");
  const rdmMsgBlock = rdmMessage
    ? `RDM failure_analysis / message:\n\`\`\`\n${String(rdmMessage).slice(0, 4000)}\n\`\`\`\n`
    : "";

  return `## Your Task

You are triaging a skipped nutest testcase caused by an RDM deployment failure.
You MUST read and follow the **triage-rdm-deployment-failure** skill from the
nutest-py3-tests repository:
\`${NUTEST_REPO}/-/tree/${RDM_SKILL_DIR}\`

Do **not** file a JIRA ticket yourself. Classify the failure and recommend
whether to link an existing ENG/DIAL ticket, create a new ticket, or comment
\`regx_rerun\` for an intermittent issue.

### Step 1 — Load skill guidance (lazy)

Use the **gw-sourcegraph** MCP server (\`sourcegraph__read_file\`).
Repo: \`${NUTEST_REPO}\`.

1. **Start with:** \`${RDM_SKILL_DIR}/SKILL.md\`
2. Read additional files under \`${RDM_SKILL_DIR}/\` only as the workflow requires
   (do not preload every file).
3. If needed, read only the matching \`flows/\` file for this deployment failure type.

Prefer speed: gather enough evidence for a confident skip/root-cause call, then stop.

### Step 2 — Execute the skill with this input

Primary skill input (RDM scheduled-deployment URL, log link, or JITA results URL):

\`\`\`
${skillInputUrl || "NO RDM/JITA URL PROVIDED"}
\`\`\`

**Testcase context:**
- **Testcase:** ${testcaseName}
- **Stage:** ${failureStage || "Unknown"}
${rdmLine}${jitaLine}${jiraLine}${tgLine}${gleanLine}${snippetBlock ? `- **Glean snippets:**\n${snippetBlock}\n` : ""}- **Skip Reason:** ${exceptionSummary || rdmMessage || "N/A"}

${rdmMsgBlock}\`\`\`
${(exception || rdmMessage || "N/A").slice(0, 5000)}
\`\`\`

${stepsLog ? `steps.log snippet:\n\`\`\`\n${stepsLog.slice(0, 3000)}\n\`\`\`\n` : ""}
${nutestTestLog ? `nutest_test.log snippet:\n\`\`\`\n${nutestTestLog.slice(0, 3000)}\n\`\`\`\n` : ""}

### Step 2b — Hunt existing ENG and DIAL tickets

Use the **gw-glean** MCP (\`glean__company_search\`, \`datasources: ["jira"]\`)
to find tickets that match THIS deployment failure (literal error, nodes,
Foundation/imaging, pool, nested AHV, etc.):

- **DIAL-*** — lab / infra / Foundation / pool / node issues (e.g. DIAL-23079)
- **ENG-*** — product / AOS / hypervisor / genesis bugs

A similar ticket is a hypothesis, not proof. Only set \`recommended_action\`
to \`link_existing\` when the ticket describes the same root cause.

Validate whether the Triage Genie suggested ticket is **Correct** or
**Incorrect** for THIS failure.

### Step 2c — Recommended next action (do not file Jira)

Pick **one**:

| Finding | recommended_action | suggested_comment |
|---|---|---|
| Matching open ENG or DIAL ticket | \`link_existing\` | \`regx_rerun (DIAL-23079)\` or \`regx_rerun (ENG-xxxxx)\` |
| Intermittent / one-off infra, safe to retry | \`rerun\` | \`regx_rerun\` |
| Bad node named in the RDM error | \`disable_node_and_rerun\` | \`regx_rerun_disable-<node> Rerun cause due to node issue\` |
| New Foundation / infra / product bug, no matching ticket | \`create_jira\` | \`regx_rerun\` (ticket will be filed by the user) |

\`suggested_jira_project\`: **DIAL** for Foundation/infra/lab; **ENG** for product.

### Step 3 — Return structured results

After completing the skill's triage workflow, return your findings as JSON:

\`\`\`json
{
  "root_cause": "Why the test was skipped — deployment failure details with evidence",
  "classification": "Foundation Issue | Infra Issue | Product Issue | Config Issue | Plugin Issue | Intermittent | Other",
  "issue_category": "FOUNDATION | INFRA | PRODUCT | CONFIG | PLUGIN | INTERMITTENT | OTHER",
  "failing_code": {
    "file": "path/to/file",
    "line_range": "start-end",
    "snippet": "relevant deployment or skip code"
  },
  "suggested_fix": "Actionable fix or next step for the deployment issue",
  "confidence": "High | Medium | Low",
  "related_components": ["service1", "service2"],
  "existing_tickets": [
    {"ticket": "DIAL-23079", "project": "DIAL", "match": "same root cause"}
  ],
  "jira_duplicates": ["DIAL-23079"],
  "recommended_action": "link_existing | create_jira | rerun | disable_node_and_rerun",
  "suggested_comment": "regx_rerun (DIAL-23079)",
  "suggested_jira_project": "DIAL",
  "tg_ticket_validation": {
    "ticket": "ENG-XXXXX or empty",
    "verdict": "Correct | Incorrect | Partial | Missing",
    "reason": "why the Triage Genie ticket is or is not the right ticket"
  },
  "triage_report": "The full triage report as generated by the skill"
}
\`\`\`

Respond ONLY with the JSON block.`;
}
