import express from "express";
import { Agent } from "@cursor/sdk";
import { buildFailedAnalysisPrompt, buildSkippedAnalysisPrompt } from "./prompt.js";

const app = express();
app.use(express.json({ limit: "2mb" }));

const PORT = parseInt(process.env.CURSOR_BRIDGE_PORT || "5002", 10);
const DEFAULT_API_KEY = process.env.CURSOR_API_KEY;
const MODEL_ID = process.env.CURSOR_MODEL_ID || "claude-sonnet-4-6";
// Faster model for follow-up chat (ask mode). Override with CURSOR_FOLLOWUP_MODEL_ID.
const FOLLOWUP_MODEL_ID =
  process.env.CURSOR_FOLLOWUP_MODEL_ID || process.env.CURSOR_MODEL_ID || "composer-2";
const BATCH_CONCURRENCY = Math.max(
  3,
  Math.min(5, parseInt(process.env.CURSOR_BATCH_CONCURRENCY || "4", 10) || 4),
);
// Set CURSOR_MCP_PROFILE=full to attach every MCP server (slower).
const MCP_PROFILE = (process.env.CURSOR_MCP_PROFILE || "triage").toLowerCase();

const NUTEST_SOURCEGRAPH = "nugerrit.ntnxdpro.com/nutest-py3-tests";

const SKILLS = {
  triageCdpTestFailure: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/triage-cdp-test-failure`,
  triageRdmDeployment: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/triage-rdm-deployment-failure`,
  gleanSearch: `${NUTEST_SOURCEGRAPH}/-/tree/.cursor/skills/glean-search`,
};

const ALL_MCP_SERVERS = {
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
  "gw-supportgpt": {
    url: "https://panacea-dev.eng.nutanix.com/mcp/supportgpt",
  },
};

// Lean set for triage — fewer MCP round-trips than attaching every server.
const TRIAGE_MCP_KEYS = ["gw-sourcegraph", "gw-jita"];

/**
 * Build MCP servers with optional per-request Atlassian tokens.
 * @param {Object} atlassianTokens - { jira: string, confluence: string }
 * @param {"none"|"triage"|"full"} profile
 */
function buildMcpServers(atlassianTokens = {}, profile = MCP_PROFILE) {
  const selected = {};
  if (profile === "full") {
    Object.assign(selected, ALL_MCP_SERVERS);
  } else if (profile !== "none") {
    for (const key of TRIAGE_MCP_KEYS) {
      if (ALL_MCP_SERVERS[key]) selected[key] = ALL_MCP_SERVERS[key];
    }
  }

  const jiraToken = atlassianTokens.jira || process.env.ATLASSIAN_JIRA_TOKEN || "";
  const confluenceToken = atlassianTokens.confluence || process.env.ATLASSIAN_CONFLUENCE_TOKEN || "";

  if (profile !== "none" && (jiraToken || confluenceToken)) {
    selected.atlassian = {
      url: "https://panacea-dev.eng.nutanix.com/mcp/atlassian",
      headers: {
        "X-Atlassian-Jira-Personal-Token": jiraToken,
        "X-Atlassian-Jira-Url": "https://jira.nutanix.com",
        "X-Atlassian-Confluence-Url": "https://confluence.eng.nutanix.com:8443/",
        "X-Atlassian-Confluence-Personal-Token": confluenceToken,
      },
    };
  }

  return selected;
}

function buildFollowUpPrompt(question, mode) {
  const selectedMode = ["ask", "agent", "plan"].includes(String(mode).toLowerCase())
    ? String(mode).toLowerCase()
    : "agent";

  if (selectedMode === "ask") {
    // Fast path: answer from existing session/analysis context — no mandatory tool use.
    return `Follow-up question about the SAME failed-testcase analysis already in context:

${question}

Mode: Ask (fast).
Rules:
- Answer from the analysis and conversation already in this session.
- Do NOT call MCP tools unless the answer is impossible without one specific fact.
- Do NOT re-run full triage or re-read skill docs.
- Keep the answer concise and evidence-based.

Respond ONLY with this JSON:
\`\`\`json
{
  "follow_up_answer": "Direct answer to the question",
  "root_cause": "Keep prior root cause unless the user asks to revise it",
  "classification": "Keep prior classification unless revised",
  "confidence": "High | Medium | Low"
}
\`\`\``;
  }

  const modeInstruction = selectedMode === "plan"
    ? "Operate in Plan mode: focus on approaches, trade-offs, and a proposed plan before execution."
    : "Operate in Agent mode: provide execution-ready guidance. Use MCP tools only if needed for new evidence.";

  return `Follow-up question on the same testcase analysis:

${question}

Requested interaction mode: ${selectedMode}
${modeInstruction}

Prefer answering from existing context. Use MCP tools only when the question needs new evidence.

Respond ONLY with JSON:
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
\`\`\``;
}

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

function sanitizeRecoveryHistory(history = []) {
  if (!Array.isArray(history)) return [];
  return history.slice(-20).map((m) => {
    if (!m || typeof m !== "object") return null;
    if (m.role === "user") {
      return { role: "user", text: String(m.text || "").slice(0, 2000), mode: String(m.mode || "agent") };
    }
    if (m.role === "assistant") {
      return {
        role: "assistant",
        mode: String(m.mode || "agent"),
        follow_up_answer: String(m?.data?.follow_up_answer || ""),
        root_cause: String(m?.data?.root_cause || ""),
      };
    }
    return null;
  }).filter(Boolean);
}

async function recoverSessionFromContext(
  sessionId,
  recoveryContext = {},
  userApiKey = null,
  atlassianTokens = {},
  pendingQuestion = null,
  mode = "ask",
) {
  const testcaseName = String(recoveryContext.testcase_name || "");
  const latestAnalysis = recoveryContext.latest_analysis || {};
  const priorHistory = sanitizeRecoveryHistory(recoveryContext.prior_history || []);

  if (!testcaseName && !latestAnalysis?.root_cause && priorHistory.length === 0) {
    return null;
  }

  const apiKey = userApiKey || DEFAULT_API_KEY;
  const selectedMode = ["ask", "agent", "plan"].includes(String(mode).toLowerCase())
    ? String(mode).toLowerCase()
    : "ask";
  // Ask recovery: no MCP. Agent/plan: lean triage MCPs only.
  const mcpProfile = selectedMode === "ask" ? "none" : "triage";
  const modelId = selectedMode === "ask" ? FOLLOWUP_MODEL_ID : MODEL_ID;

  const agent = await Agent.create({
    apiKey,
    model: { id: modelId },
    mcpServers: buildMcpServers(atlassianTokens, mcpProfile),
  });

  // One round-trip: restore context AND answer the pending question (if any).
  const questionBlock = pendingQuestion
    ? `\n\nNow answer this follow-up immediately (do not wait for another turn):\n${buildFollowUpPrompt(pendingQuestion, selectedMode)}`
    : "\n\nAcknowledge internally that context is restored. Await the next user follow-up question.";

  const bootstrapPrompt = `You are continuing a previously completed failed-testcase analysis session.

Preserve prior context and continue the same discussion style.
Do NOT restart triage from scratch unless the user explicitly asks.

Testcase: ${testcaseName || "unknown"}

Latest known analysis JSON:
\`\`\`json
${JSON.stringify(latestAnalysis || {}, null, 2).slice(0, 8000)}
\`\`\`

Recent follow-up conversation (most recent entries):
\`\`\`json
${JSON.stringify(priorHistory, null, 2).slice(0, 6000)}
\`\`\`
${questionBlock}`;

  const run = await agent.send(bootstrapPrompt);
  const result = await run.wait();

  const restored = {
    agent,
    agentId: agent.agentId,
    testcase_name: testcaseName || "recovered-session",
    created_at: Date.now(),
    last_used: Date.now(),
    answeredPending: Boolean(pendingQuestion),
    pendingResult: pendingQuestion ? parseAgentResult(result.result || "") : null,
  };
  sessions.set(sessionId, restored);
  return restored;
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
    rdm_url,
    rdm_message,
    jita_task_id,
    jira_tickets,
    failure_stage,
    triage_genie_ticket,
    glean_tickets,
    glean_snippets,
    analysis_type = "failed",
    cursor_api_key,
    atlassian_tokens = {},
  } = req.body;

  if (!testcase_name) {
    return res.status(400).json({ error: "testcase_name is required" });
  }

  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const mcpServers = buildMcpServers(atlassian_tokens, MCP_PROFILE === "full" ? "full" : "triage");

  const promptOpts = {
    testcaseName: testcase_name,
    exceptionSummary: exception_summary,
    exception,
    stepsLog: steps_log,
    nutestTestLog: nutest_test_log,
    testLogUrl: test_log_url,
    rdmUrl: rdm_url || "",
    rdmMessage: rdm_message || "",
    jitaTaskId: jita_task_id || "",
    jiraTickets: jira_tickets || [],
    failureStage: failure_stage,
    triageGenieTicket: triage_genie_ticket || "",
    gleanTickets: glean_tickets || [],
    gleanSnippets: glean_snippets || [],
    sourcegraphRepo: NUTEST_SOURCEGRAPH,
    skills: SKILLS,
  };

  const prompt = analysis_type === "skipped"
    ? buildSkippedAnalysisPrompt(promptOpts)
    : buildFailedAnalysisPrompt(promptOpts);

  const sessionId = generateSessionId();

  try {
    const agent = await Agent.create({
      apiKey,
      model: { id: MODEL_ID },
      mcpServers,
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
  const {
    session_id,
    question,
    mode = "agent",
    recovery_context = {},
    cursor_api_key,
    atlassian_tokens = {},
  } = req.body;

  if (!session_id || !question) {
    return res.status(400).json({ error: "session_id and question are required" });
  }

  const selectedMode = ["ask", "agent", "plan"].includes(String(mode).toLowerCase())
    ? String(mode).toLowerCase()
    : "ask";

  let session = sessions.get(session_id);
  if (!session) {
    try {
      // Recover + answer in a single agent turn (avoids bootstrap wait + second wait).
      session = await recoverSessionFromContext(
        session_id,
        recovery_context,
        cursor_api_key,
        atlassian_tokens,
        question,
        selectedMode,
      );
    } catch (recoverErr) {
      console.error("[follow-up] Session recovery failed:", recoverErr.message);
    }
    if (!session) {
      return res.status(404).json({
        error: "Session expired and could not be restored from cached context. Run a new analysis first.",
      });
    }
    if (session.answeredPending && session.pendingResult) {
      const analysis = session.pendingResult;
      session.pendingResult = null;
      session.answeredPending = false;
      return res.json({ success: true, session_id, analysis });
    }
  }

  try {
    session.last_used = Date.now();
    const followUpPrompt = buildFollowUpPrompt(question, selectedMode);
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
  const { testcases, cursor_api_key, atlassian_tokens = {} } = req.body;
  if (!Array.isArray(testcases) || testcases.length === 0) {
    return res.status(400).json({ error: "testcases array is required" });
  }

  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
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

  processBatch(job, testcases, apiKey, atlassian_tokens);

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
// Batch processing — creates durable sessions per testcase for follow-ups
// ---------------------------------------------------------------------------
async function processBatch(job, testcases, apiKey, atlassianTokens = {}) {
  const mcpServers = buildMcpServers(atlassianTokens, MCP_PROFILE === "full" ? "full" : "triage");

  async function analyzeOne(tc) {
    const key = tc.testcase_id || tc.testcase_name;
    try {
      const promptOpts = {
        testcaseName: tc.testcase_name,
        exceptionSummary: tc.exception_summary,
        exception: tc.exception,
        stepsLog: tc.steps_log,
        nutestTestLog: tc.nutest_test_log,
        testLogUrl: tc.test_log_url,
        rdmUrl: tc.rdm_url || "",
        rdmMessage: tc.rdm_message || "",
        jitaTaskId: tc.jita_task_id || tc.agave_task_id || "",
        jiraTickets: tc.jira_tickets || [],
        failureStage: tc.failure_stage,
        sourcegraphRepo: NUTEST_SOURCEGRAPH,
        skills: SKILLS,
      };

      const analysisType = tc.analysis_type || "failed";
      const prompt = analysisType === "skipped"
        ? buildSkippedAnalysisPrompt(promptOpts)
        : buildFailedAnalysisPrompt(promptOpts);

      const agent = await Agent.create({
        apiKey,
        model: { id: MODEL_ID },
        mcpServers,
      });
      const run = await agent.send(prompt);
      const result = await run.wait();
      const sessionId = generateSessionId();

      sessions.set(sessionId, {
        agent,
        agentId: agent.agentId,
        testcase_name: tc.testcase_name,
        created_at: Date.now(),
        last_used: Date.now(),
      });

      job.results[key] = {
        success: true,
        analysis: parseAgentResult(result.result || ""),
        session_id: sessionId,
      };
    } catch (err) {
      console.error(`[batch] Error for ${key}:`, err.message);
      job.results[key] = { success: false, error: err.message };
    } finally {
      job.completed += 1;
    }
  }

  let nextIndex = 0;
  const workerCount = Math.min(BATCH_CONCURRENCY, testcases.length);
  const workers = Array.from({ length: workerCount }, async () => {
    while (true) {
      const idx = nextIndex;
      nextIndex += 1;
      if (idx >= testcases.length) return;
      await analyzeOne(testcases[idx]);
    }
  });

  await Promise.all(workers);
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
// POST /chat
// Lightweight conversational path for Cursor AI chat UI fallback.
// ---------------------------------------------------------------------------
app.post("/chat", async (req, res) => {
  const {
    message,
    system_prompt = "",
    cursor_api_key,
    atlassian_tokens = {},
  } = req.body || {};

  if (!message || !String(message).trim()) {
    return res.status(400).json({ error: "message is required" });
  }

  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const prompt = system_prompt
    ? `${system_prompt}\n\n---\nUser message:\n${message}`
    : String(message);

  try {
    const agent = await Agent.create({
      apiKey,
      model: { id: FOLLOWUP_MODEL_ID },
      mcpServers: buildMcpServers(atlassian_tokens, "none"),
    });
    const run = await agent.send(prompt);
    const result = await run.wait();
    return res.json({
      success: true,
      reply: (result.result || "").trim(),
      agent_id: agent.agentId,
    });
  } catch (err) {
    console.error("[chat] Agent error:", err.message);
    return res.status(502).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[cursor-bridge] listening on :${PORT}`);
  console.log(`[cursor-bridge] nutest via Sourcegraph = ${NUTEST_SOURCEGRAPH}`);
  console.log(`[cursor-bridge] MCP profile = ${MCP_PROFILE} (triage keys: ${TRIAGE_MCP_KEYS.join(", ")})`);
  console.log(`[cursor-bridge] model = ${MODEL_ID}; follow-up model = ${FOLLOWUP_MODEL_ID}`);
  console.log(`[cursor-bridge] Default API key configured = ${!!DEFAULT_API_KEY}`);
  console.log(`[cursor-bridge] Per-request API keys = enabled`);
  console.log(`[cursor-bridge] batch concurrency = ${BATCH_CONCURRENCY}`);
});