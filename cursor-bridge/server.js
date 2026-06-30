import express from "express";
import { Agent } from "@cursor/sdk";
import { buildFailedAnalysisPrompt, buildSkippedAnalysisPrompt } from "./prompt.js";

const app = express();
app.use(express.json({ limit: "2mb" }));

const PORT = parseInt(process.env.CURSOR_BRIDGE_PORT || "5002", 10);
const API_KEY = process.env.CURSOR_API_KEY;
const MODEL_ID = process.env.CURSOR_MODEL_ID || "claude-sonnet-4-6";

const NUTEST_SOURCEGRAPH = "nugerrit.ntnxdpro.com/nutest-py3-tests";

const SKILLS = {
  triageCdpTestFailure: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/triage-cdp-test-failure`,
  triageRdmDeployment: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/triage-rdm-deployment-failure`,
  gleanSearch: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/glean-search`,
};

const MCP_SERVERS = {
  "regx-data": {
    url: process.env.REGX_MCP_URL || "http://localhost:5003",
  },
  "gw-sourcegraph": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/sourcegraph",
  },
  "gw-jita": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/jita",
  },
  "gw-panacea": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/panacea",
  },
  "gw-glean": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/glean",
  },
  "atlassian": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/atlassian",
    headers: {
      "X-Atlassian-Jira-Personal-Token": process.env.ATLASSIAN_JIRA_TOKEN || "",
      "X-Atlassian-Jira-Url": "https://jira.nutanix.com",
      "X-Atlassian-Confluence-Url": "https://confluence.eng.nutanix.com:8443/",
      "X-Atlassian-Confluence-Personal-Token": process.env.ATLASSIAN_CONFLUENCE_TOKEN || "",
    },
  },
  "gw-supportgpt": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/supportgpt",
  },
};

// In-memory job store for async batch analysis
const jobs = new Map();

// Session store: keeps durable Cursor agents alive for follow-up questions.
// Key = session_id, Value = { agent, agentId, testcase_name, created_at, last_used }
const sessions = new Map();
const SESSION_TTL_MS = 30 * 60 * 1000; // 30 minutes

// Cleanup expired sessions every 5 minutes
setInterval(() => {
  const now = Date.now();
  for (const [id, session] of sessions) {
    if (now - session.last_used > SESSION_TTL_MS) {
      session.agent[Symbol.asyncDispose]().catch(() => {});
      sessions.delete(id);
      console.log(`[session] Expired and disposed: ${id}`);
    }
  }
}, 5 * 60 * 1000);

function generateSessionId() {
  return `ses_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------
app.get("/health", (_req, res) => {
  res.json({ status: "ok", jobs: jobs.size, sessions: sessions.size });
});

// ---------------------------------------------------------------------------
// POST /analyze-testcase
// Uses Agent.create() + agent.send() so the session stays alive for follow-ups.
// Returns a session_id the caller can use for /follow-up.
// ---------------------------------------------------------------------------
app.post("/analyze-testcase", async (req, res) => {
  const {
    testcase_name,
    exception_summary,
    exception,
    steps_log,
    nutest_test_log,
    test_log_url,
    jira_tickets,
    failure_stage,
    analysis_type = "failed",
  } = req.body;

  if (!testcase_name) {
    return res.status(400).json({ error: "testcase_name is required" });
  }
  if (!API_KEY) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const promptOpts = {
    testcaseName: testcase_name,
    exceptionSummary: exception_summary,
    exception,
    stepsLog: steps_log,
    nutestTestLog: nutest_test_log,
    testLogUrl: test_log_url,
    jiraTickets: jira_tickets || [],
    failureStage: failure_stage,
    sourcegraphRepo: NUTEST_SOURCEGRAPH,
    skills: SKILLS,
  };

  const prompt = analysis_type === "skipped"
    ? buildSkippedAnalysisPrompt(promptOpts)
    : buildFailedAnalysisPrompt(promptOpts);

  const sessionId = generateSessionId();

  try {
    const agent = await Agent.create({
      apiKey: API_KEY,
      model: { id: MODEL_ID },
      mcpServers: MCP_SERVERS,
    });

    const run = await agent.send(prompt);
    const result = await run.wait();

    const analysis = parseAgentResult(result.result || "");

    // Store session for follow-ups
    sessions.set(sessionId, {
      agent,
      agentId: agent.agentId,
      testcase_name,
      created_at: Date.now(),
      last_used: Date.now(),
    });

    return res.json({
      success: true,
      session_id: sessionId,
      analysis,
    });
  } catch (err) {
    console.error("[analyze-testcase] Agent error:", err.message);
    return res.status(502).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// POST /follow-up
// Continue a previous analysis session with a follow-up question.
// The agent retains full conversation context from the initial triage.
// ---------------------------------------------------------------------------
app.post("/follow-up", async (req, res) => {
  const { session_id, question } = req.body;

  if (!session_id || !question) {
    return res.status(400).json({ error: "session_id and question are required" });
  }

  const session = sessions.get(session_id);
  if (!session) {
    return res.status(404).json({
      error: "Session not found or expired. Start a new analysis first.",
    });
  }

  try {
    session.last_used = Date.now();

    const followUpPrompt = `Follow-up question on the same testcase analysis:

${question}

If this question requires deeper investigation, use the MCP tools (Sourcegraph,
JITA, Jira, Glean, etc.) to gather more evidence. Then respond with updated JSON:

\`\`\`json
{
  "root_cause": "Updated root cause (or same if unchanged)",
  "classification": "Updated classification (or same)",
  "failing_code": { "file": "...", "line_range": "...", "snippet": "..." },
  "suggested_fix": "Updated suggestion",
  "confidence": "High | Medium | Low",
  "related_components": [],
  "jira_duplicates": [],
  "follow_up_answer": "Direct answer to the follow-up question with evidence",
  "triage_report": "Updated JIRA wiki report if applicable"
}
\`\`\`

Respond ONLY with the JSON block.`;

    const run = await session.agent.send(followUpPrompt);
    const result = await run.wait();

    const analysis = parseAgentResult(result.result || "");
    return res.json({ success: true, session_id, analysis });
  } catch (err) {
    console.error("[follow-up] Agent error:", err.message);
    return res.status(502).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// DELETE /session/:sessionId — explicitly dispose a session
// ---------------------------------------------------------------------------
app.delete("/session/:sessionId", async (req, res) => {
  const session = sessions.get(req.params.sessionId);
  if (!session) return res.status(404).json({ error: "Session not found" });

  try {
    await session.agent[Symbol.asyncDispose]();
  } catch { /* already disposed */ }
  sessions.delete(req.params.sessionId);
  return res.json({ success: true });
});

// ---------------------------------------------------------------------------
// POST /analyze-batch  (async — returns job_id immediately, poll /status/:id)
// ---------------------------------------------------------------------------
app.post("/analyze-batch", (req, res) => {
  const { testcases } = req.body;
  if (!Array.isArray(testcases) || testcases.length === 0) {
    return res.status(400).json({ error: "testcases array is required" });
  }
  if (!API_KEY) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const jobId = `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const job = {
    id: jobId,
    status: "running",
    total: testcases.length,
    completed: 0,
    results: {},
    created_at: new Date().toISOString(),
  };
  jobs.set(jobId, job);

  processBatch(job, testcases);

  return res.json({ success: true, job_id: jobId, total: testcases.length });
});

// ---------------------------------------------------------------------------
// GET /status/:jobId
// ---------------------------------------------------------------------------
app.get("/status/:jobId", (req, res) => {
  const job = jobs.get(req.params.jobId);
  if (!job) return res.status(404).json({ error: "Job not found" });

  return res.json({
    job_id: job.id,
    status: job.status,
    total: job.total,
    completed: job.completed,
    results: job.results,
    created_at: job.created_at,
  });
});

// ---------------------------------------------------------------------------
// Batch processing — uses Agent.prompt() (one-shot, no sessions for batch)
// ---------------------------------------------------------------------------
async function processBatch(job, testcases) {
  for (const tc of testcases) {
    const key = tc.testcase_id || tc.testcase_name;
    try {
      const promptOpts = {
        testcaseName: tc.testcase_name,
        exceptionSummary: tc.exception_summary,
        exception: tc.exception,
        stepsLog: tc.steps_log,
        nutestTestLog: tc.nutest_test_log,
        testLogUrl: tc.test_log_url,
        jiraTickets: tc.jira_tickets || [],
        failureStage: tc.failure_stage,
        sourcegraphRepo: NUTEST_SOURCEGRAPH,
        skills: SKILLS,
      };

      const analysisType = tc.analysis_type || "failed";
      const prompt = analysisType === "skipped"
        ? buildSkippedAnalysisPrompt(promptOpts)
        : buildFailedAnalysisPrompt(promptOpts);

      const result = await Agent.prompt(prompt, {
        apiKey: API_KEY,
        model: { id: MODEL_ID },
        mcpServers: MCP_SERVERS,
      });

      job.results[key] = { success: true, analysis: parseAgentResult(result.result || "") };
    } catch (err) {
      console.error(`[batch] Error for ${key}:`, err.message);
      job.results[key] = { success: false, error: err.message };
    }
    job.completed += 1;
  }
  job.status = "done";
  setTimeout(() => jobs.delete(job.id), 3600_000);
}

// ---------------------------------------------------------------------------
function parseAgentResult(text) {
  const fenced = text.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  const jsonStr = fenced ? fenced[1].trim() : text.trim();

  try {
    return JSON.parse(jsonStr);
  } catch {
    return {
      root_cause: text.trim(),
      classification: "Unknown",
      failing_code: null,
      suggested_fix: "",
      confidence: "Low",
      related_components: [],
    };
  }
}

// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[cursor-bridge] listening on :${PORT}`);
  console.log(`[cursor-bridge] nutest via Sourcegraph = ${NUTEST_SOURCEGRAPH}`);
  console.log(`[cursor-bridge] MCP servers = ${Object.keys(MCP_SERVERS).join(", ")}`);
  console.log(`[cursor-bridge] API key configured = ${!!API_KEY}`);
});
