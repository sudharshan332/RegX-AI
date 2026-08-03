import express from "express";
import { Agent } from "@cursor/sdk";
import { buildFailedAnalysisPrompt, buildSkippedAnalysisPrompt } from "./prompt.js";

const app = express();
app.use(express.json({ limit: "2mb" }));

const PORT = parseInt(process.env.CURSOR_BRIDGE_PORT || "5002", 10);
const DEFAULT_API_KEY = process.env.CURSOR_API_KEY;
// composer-2 is no longer available on many Cursor API keys; map legacy/friendly IDs.
const LEGACY_MODEL_ALIASES = {
  "composer-2": "auto-smart",
  "composer-1": "auto-smart",
  auto: "auto-smart",
  // Friendly (dotted) UI ids -> valid Cursor model ids
  "claude-sonnet-4.6-high": "claude-sonnet-4-6",
  "claude-sonnet-4.6": "claude-sonnet-4-6",
  "claude-sonnet-4.5": "claude-sonnet-4-5",
  "claude-haiku-4.5": "claude-haiku-4-5",
};
function resolveModelId(id) {
  const raw = String(id || "").trim();
  return LEGACY_MODEL_ALIASES[raw] || raw;
}
const MODEL_ID = resolveModelId(process.env.CURSOR_MODEL_ID || "claude-sonnet-4-6");
// Model for deep testcase analysis. The analysis workflow is tool-heavy (reads
// skill docs, logs, source), so default to the faster Sonnet 4.5 to cut latency;
// override with CURSOR_ANALYSIS_MODEL_ID (e.g. claude-sonnet-4-6 for max depth).
const ANALYSIS_MODEL_ID = resolveModelId(
  process.env.CURSOR_ANALYSIS_MODEL_ID || "claude-sonnet-4-5",
);
// Auto model for follow-up chat (ask mode). Override with CURSOR_FOLLOWUP_MODEL_ID.
const FOLLOWUP_MODEL_ID = resolveModelId(
  process.env.CURSOR_FOLLOWUP_MODEL_ID || "auto-smart",
);
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
  "auto-handoff": {
    url: process.env.AUTO_HANDOFF_MCP_URL || "http://10.40.224.6:9001/sse",
  },
};

// Lean triage: code + logs. Deep: + product knowledge.
// NOTE: auto-handoff is intentionally NOT in the default deep set. Its SSE
// endpoint (internal IP) can hang for many seconds, which was adding large
// latency to every deep analysis. It is attached only for the "handoff"
// profile, i.e. when a request explicitly needs to create a CR / handoff.
const TRIAGE_MCP_KEYS = ["gw-sourcegraph", "gw-jita"];
const DEEP_MCP_KEYS = ["gw-sourcegraph", "gw-jita", "gw-glean"];
const HANDOFF_MCP_KEYS = ["gw-sourcegraph", "gw-jita", "gw-glean", "auto-handoff"];

/**
 * Build MCP servers with optional per-request Atlassian tokens.
 * @param {Object} atlassianTokens - { jira: string, confluence: string }
 * @param {"none"|"triage"|"deep"|"full"} profile
 */
function buildMcpServers(atlassianTokens = {}, profile = MCP_PROFILE) {
  const selected = {};
  if (profile === "full") {
    Object.assign(selected, ALL_MCP_SERVERS);
  } else if (profile === "handoff") {
    for (const key of HANDOFF_MCP_KEYS) {
      if (ALL_MCP_SERVERS[key]) selected[key] = ALL_MCP_SERVERS[key];
    }
  } else if (profile === "deep") {
    for (const key of DEEP_MCP_KEYS) {
      if (ALL_MCP_SERVERS[key]) selected[key] = ALL_MCP_SERVERS[key];
    }
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

/** True when follow-up needs live tools (Jira/Glean/CR/code), not ask-mode memory. */
function needsToolFollowUp(question) {
  const t = String(question || "").toLowerCase();
  if (!t.trim()) return false;
  return (
    /\b(jira|eng-\d+|gerrit|glean|confluence|sourcegraph|cr\b|change request|handoff|duplicate)\b/.test(t)
    || /\b(create|file|raise|submit|open)\b.{0,40}\b(ticket|cr|change)\b/.test(t)
    || /\b(fixed|resolved|status|root cause|product knowledge|has it been)\b/.test(t)
    || /\b(review|what('?s| is) the (issue|fix|cr))\b/.test(t)
  );
}

function resolveFollowUpMode(mode, question) {
  const requested = ["ask", "agent", "plan"].includes(String(mode).toLowerCase())
    ? String(mode).toLowerCase()
    : "ask";
  if (requested === "ask" && needsToolFollowUp(question)) return "agent";
  return requested;
}

/** True only when the user explicitly wants to create/update a CR or run a handoff/deprecation. */
function needsHandoff(question) {
  const t = String(question || "").toLowerCase();
  if (!t.trim()) return false;
  return (
    /\b(handoff|hand off|deprecate|deprecation)\b/.test(t)
    || /\b(create|file|raise|submit|open|push|update)\b.{0,40}\b(cr|change request|gerrit|change)\b/.test(t)
  );
}

function resolveMcpProfile(mode, question) {
  if (mode === "ask") return "none";
  if (MCP_PROFILE === "full") return "full";
  // Only pull in the (slow) auto-handoff MCP when the user actually wants a CR/handoff.
  if (needsHandoff(question)) return "handoff";
  if (needsToolFollowUp(question) || mode === "agent" || mode === "plan") return "deep";
  return "triage";
}

function buildFollowUpPrompt(question, mode, crContext = null) {
  const selectedMode = ["ask", "agent", "plan"].includes(String(mode).toLowerCase())
    ? String(mode).toLowerCase()
    : "ask";

  if (selectedMode === "ask") {
    // Fast path: plain-text answer from existing context — no tools, no JSON tax.
    return `Quick follow-up on the SAME failed-testcase analysis already in this conversation.

Question: ${question}

Rules:
- Answer from context already in this session. Be concise (a few paragraphs max).
- Do NOT call tools, re-triage, or re-read skill docs.
- Plain text only — no JSON wrapper.`;
  }

  const cr = crContext && typeof crContext === "object" ? crContext : {};
  const gerritBranch = String(cr.gerrit_branch || cr.handoff_branch || "").trim();
  const handoffBranch = String(cr.handoff_branch || gerritBranch || "").trim();
  let branchBlock = "";
  if (gerritBranch) {
    branchBlock = `
CRITICAL BRANCH CONTEXT (from the failed JITA run — do NOT ignore):
- Target Gerrit branch: ${gerritBranch}
- Push ref MUST be: refs/for/${gerritBranch}
- For auto_handoff / auto_deprecate use branch="${handoffBranch || gerritBranch}"
- Do NOT ask the user which branch to use and do NOT default to master unless the run was on master.
- Testcase: ${cr.testcase_name || "(from session)"}
`;
  }

  const modeInstruction = selectedMode === "plan"
    ? "Operate in Plan mode: propose approaches and trade-offs. You may use read-only MCP tools for evidence."
    : `Operate in Agent mode with FULL tool access. You MUST use MCP tools when the question needs live data:
- **Atlassian/Jira**: read ENG ticket status, resolution, comments, linked issues; search duplicates.
- **Glean (gw-glean)**: product knowledge, prior incidents, design docs, owner context.
- **Sourcegraph (gw-sourcegraph)**: code, commits, fix CRs, failing file history (search on the target branch above).
- **JITA (gw-jita)**: logs / task evidence when needed.
- **auto-handoff / auto_deprecate**: create/preview Gerrit CRs for handoff/deprecation when the user asks to create a CR. ALWAYS pass the branch from CRITICAL BRANCH CONTEXT.
Do not claim a ticket/CR was created unless a tool call succeeded. Prefer evidence over memory.
Structure the answer clearly: Issue → Status/Fixed? → CR(s) → Glean/product context → Next actions.`;

  return `Follow-up question on the same testcase analysis:

${question}
${branchBlock}
Requested interaction mode: ${selectedMode}
${modeInstruction}

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
  "follow_up_answer": "Direct answer with evidence from tools (ticket status, fix/CR, glean findings)",
  "triage_report": "Updated JIRA wiki report if applicable",
  "created_ticket": "ENG-XXXX if you created one, else empty",
  "related_crs": ["Gerrit CR urls or change numbers if found/created"],
  "cr_branch": "${gerritBranch || ""}"
}
\`\`\``;
}

function compactRecoveryAnalysis(latestAnalysis = {}) {
  const src = latestAnalysis && typeof latestAnalysis === "object" ? latestAnalysis : {};
  return {
    root_cause: String(src.root_cause || "").slice(0, 1500),
    classification: String(src.classification || "").slice(0, 120),
    confidence: String(src.confidence || "").slice(0, 40),
    suggested_fix: String(src.suggested_fix || "").slice(0, 800),
    failing_code: src.failing_code || null,
  };
}

// Agent.resume() returns Promise<Agent> — MUST be awaited, otherwise the
// caller gets a Promise whose `.send` is undefined ("agent.send is not a function").
async function tryResumeAgent(agentId, apiKey, modelId, mcpServers = {}) {
  if (!agentId) return null;
  try {
    const agent = await Agent.resume(String(agentId), {
      apiKey,
      model: { id: modelId },
      mcpServers,
    });
    if (!agent || typeof agent.send !== "function") {
      console.warn(`[session] Resume returned invalid agent for ${agentId}`);
      return null;
    }
    console.log(`[session] Resumed agent ${agentId}`);
    return agent;
  } catch (err) {
    console.warn(`[session] Resume failed for ${agentId}: ${err.message}`);
    return null;
  }
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
  const latestAnalysis = compactRecoveryAnalysis(recoveryContext.latest_analysis || {});
  const priorHistory = sanitizeRecoveryHistory(recoveryContext.prior_history || []);
  const priorAgentId = recoveryContext.agent_id || null;
  const crContext = recoveryContext.cr_context || {
    gerrit_branch: recoveryContext.gerrit_branch,
    handoff_branch: recoveryContext.handoff_branch,
    testcase_name: testcaseName,
  };

  if (!testcaseName && !latestAnalysis?.root_cause && priorHistory.length === 0 && !priorAgentId) {
    return null;
  }

  const apiKey = userApiKey || DEFAULT_API_KEY;
  const selectedMode = resolveFollowUpMode(mode, pendingQuestion || "");
  const mcpProfile = resolveMcpProfile(selectedMode, pendingQuestion || "");
  const modelId = selectedMode === "ask" ? FOLLOWUP_MODEL_ID : MODEL_ID;
  const mcpServers = buildMcpServers(atlassianTokens, mcpProfile);
  const t0 = Date.now();

  // Fast path: resume durable Cursor agent (keeps full prior conversation).
  if (priorAgentId && pendingQuestion) {
    const resumed = await tryResumeAgent(priorAgentId, apiKey, modelId, mcpServers);
    if (resumed) {
      try {
        const run = await resumed.send(buildFollowUpPrompt(pendingQuestion, selectedMode, crContext));
        const result = await run.wait();
        const restored = {
          agent: resumed,
          agentId: resumed.agentId || priorAgentId,
          testcase_name: testcaseName || "recovered-session",
          created_at: Date.now(),
          last_used: Date.now(),
          answeredPending: true,
          pendingResult: parseAgentResult(result.result || "", {
            preferFollowUp: selectedMode === "ask",
          }),
        };
        sessions.set(sessionId, restored);
        console.log(`[follow-up] resume+answer in ${Date.now() - t0}ms (mode=${selectedMode}, mcp=${mcpProfile})`);
        return restored;
      } catch (err) {
        console.warn(`[follow-up] resumed send failed: ${err.message}`);
        resumed[Symbol.asyncDispose]?.().catch(() => {});
      }
    }
  }

  const agent = await Agent.create({
    apiKey,
    model: { id: modelId },
    mcpServers,
  });

  // One round-trip: restore lean context AND answer the pending question (if any).
  const questionBlock = pendingQuestion
    ? `\n\nAnswer this follow-up now:\n${buildFollowUpPrompt(pendingQuestion, selectedMode, crContext)}`
    : "\n\nContext restored. Wait for the next question.";

  const bootstrapPrompt = `Continue a failed-testcase analysis. Do NOT re-triage from scratch.

Testcase: ${testcaseName || "unknown"}

Analysis summary:
\`\`\`json
${JSON.stringify(latestAnalysis, null, 2).slice(0, 2500)}
\`\`\`

Recent Q&A:
\`\`\`json
${JSON.stringify(priorHistory.slice(-6), null, 2).slice(0, 2500)}
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
    pendingResult: pendingQuestion
      ? parseAgentResult(result.result || "", { preferFollowUp: true })
      : null,
  };
  sessions.set(sessionId, restored);
  console.log(`[follow-up] bootstrap+answer in ${Date.now() - t0}ms (mode=${selectedMode})`);
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
    jira_tickets,
    failure_stage,
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

  // Initial deep analysis gets Glean + Sourcegraph + JITA (+ Atlassian when tokens present).
  const mcpServers = buildMcpServers(
    atlassian_tokens,
    MCP_PROFILE === "full" ? "full" : "deep",
  );

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
      apiKey,
      model: { id: ANALYSIS_MODEL_ID },
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
      agent_id: agent.agentId || null,
      analysis,
    });
  } catch (err) {
    console.error("[analyze-testcase] Agent error:", err.message);
    return res.status(502).json({ error: err.message });
  }
});

/** Human-friendly progress label for a tool_call event during deep analysis. */
function toolStatusLabel(name, args) {
  const n = String(name || "").toLowerCase();
  let target = "";
  if (args && typeof args === "object") {
    target = args.path || args.file || args.query || args.pattern || args.url || "";
    if (typeof target !== "string") target = "";
    target = target.split("/").slice(-2).join("/").slice(0, 80);
  }
  if (n.includes("sourcegraph") || n.includes("read_file") || n.includes("read")) {
    return target ? `Reading source: ${target}` : "Reading source code…";
  }
  if (n.includes("grep") || n.includes("search") || n.includes("sem")) {
    return target ? `Searching: ${target}` : "Searching source…";
  }
  if (n.includes("jita") || n.includes("log")) return "Fetching test logs…";
  if (n.includes("glean")) return "Searching product knowledge (Glean)…";
  if (n.includes("atlassian") || n.includes("jira")) return "Checking Jira tickets…";
  if (n.includes("handoff") || n.includes("gerrit") || n.includes("cr")) return "Working with CR/handoff…";
  return name ? `Running ${name}…` : "Working…";
}

// ---------------------------------------------------------------------------
// POST /analyze-testcase-stream
// Same deep analysis as /analyze-testcase, but streams the agent's output as
// it is produced (SSE). The UI shows progress within a couple of seconds
// instead of waiting for the whole (multi-tool) triage to finish. Emits
// {type:status,text} for tool activity, {type:delta,text} for the answer,
// then {type:done, analysis, session_id, ...}.
// ---------------------------------------------------------------------------
app.post("/analyze-testcase-stream", async (req, res) => {
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
    cursor_api_key,
    atlassian_tokens = {},
  } = req.body || {};

  if (!testcase_name) {
    return res.status(400).json({ error: "testcase_name is required" });
  }
  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const mcpServers = buildMcpServers(
    atlassian_tokens,
    MCP_PROFILE === "full" ? "full" : "deep",
  );

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

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  if (typeof res.flushHeaders === "function") res.flushHeaders();

  const send = (obj) => {
    try {
      res.write(`data: ${JSON.stringify(obj)}\n\n`);
    } catch { /* client gone */ }
  };

  const t0 = Date.now();
  const sessionId = generateSessionId();
  let agent = null;

  try {
    agent = await Agent.create({
      apiKey,
      model: { id: ANALYSIS_MODEL_ID },
      mcpServers,
    });

    const run = await agent.send(prompt);

    let lastFull = "";
    let firstTokenMs = null;
    let lastStatus = "";
    if (typeof run.supports !== "function" || run.supports("stream")) {
      for await (const event of run.stream()) {
        // Surface tool activity as progress so the user sees work within ~2s,
        // long before the final JSON answer is produced.
        if (event.type === "tool_call" && event.status === "running") {
          const label = toolStatusLabel(event.name, event.args);
          if (label && label !== lastStatus) {
            lastStatus = label;
            if (firstTokenMs === null) firstTokenMs = Date.now() - t0;
            send({ type: "status", text: label });
          }
          continue;
        }
        if (event.type === "assistant" && event.message && Array.isArray(event.message.content)) {
          let full = "";
          for (const block of event.message.content) {
            if (block.type === "text" && block.text) full += block.text;
            else if (block.type === "tool_use" && block.name) {
              const label = toolStatusLabel(block.name, block.input);
              if (label && label !== lastStatus) {
                lastStatus = label;
                if (firstTokenMs === null) firstTokenMs = Date.now() - t0;
                send({ type: "status", text: label });
              }
            }
          }
          if (full) {
            const delta = full.startsWith(lastFull) ? full.slice(lastFull.length) : full;
            lastFull = full;
            if (delta) {
              if (firstTokenMs === null) firstTokenMs = Date.now() - t0;
              send({ type: "delta", text: delta });
            }
          }
        }
      }
    }

    const result = await run.wait();
    const rawText = (result.result || lastFull || "").trim();
    const analysis = parseAgentResult(rawText);

    sessions.set(sessionId, {
      agent,
      agentId: agent.agentId,
      testcase_name,
      created_at: Date.now(),
      last_used: Date.now(),
    });

    send({
      type: "done",
      analysis,
      session_id: sessionId,
      agent_id: agent.agentId || null,
      elapsed_ms: Date.now() - t0,
    });
    res.end();
    console.log(
      `[analyze-testcase-stream] model=${ANALYSIS_MODEL_ID} firstToken=${firstTokenMs}ms total=${Date.now() - t0}ms`,
    );
  } catch (err) {
    console.error("[analyze-testcase-stream] Agent error:", err.message);
    send({ type: "error", message: err.message });
    try { res.end(); } catch { /* noop */ }
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
    cr_context = null,
    cursor_api_key,
    atlassian_tokens = {},
  } = req.body;

  if (!session_id || !question) {
    return res.status(400).json({ error: "session_id and question are required" });
  }

  const selectedMode = resolveFollowUpMode(mode, question);
  const mcpProfile = resolveMcpProfile(selectedMode, question);
  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  const resolvedCrContext = cr_context
    || recovery_context.cr_context
    || {
      gerrit_branch: recovery_context.gerrit_branch,
      handoff_branch: recovery_context.handoff_branch,
      testcase_name: recovery_context.testcase_name,
    };

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
      return res.json({
        success: true,
        session_id,
        agent_id: session.agentId || null,
        analysis,
      });
    }
  }

  try {
    const t0 = Date.now();
    session.last_used = Date.now();

    // Tool-heavy follow-ups: re-attach deep MCP servers (Glean/Jira/auto-handoff)
    // onto the durable agent so Ask-mode sessions can still investigate live.
    if (selectedMode !== "ask" && session.agentId && apiKey) {
      const mcpServers = buildMcpServers(atlassian_tokens, mcpProfile);
      const resumed = await tryResumeAgent(
        session.agentId,
        apiKey,
        selectedMode === "ask" ? FOLLOWUP_MODEL_ID : MODEL_ID,
        mcpServers,
      );
      if (resumed) {
        session.agent = resumed;
        session.agentId = resumed.agentId || session.agentId;
      }
    }

    const followUpPrompt = buildFollowUpPrompt(question, selectedMode, resolvedCrContext);
    const run = await session.agent.send(followUpPrompt);
    const result = await run.wait();

    const analysis = parseAgentResult(result.result || "", {
      preferFollowUp: selectedMode === "ask",
    });
    console.log(`[follow-up] live session answer in ${Date.now() - t0}ms (mode=${selectedMode}, mcp=${mcpProfile})`);
    return res.json({
      success: true,
      session_id,
      agent_id: session.agentId || null,
      analysis,
    });
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
  const mcpServers = buildMcpServers(atlassianTokens, MCP_PROFILE === "full" ? "full" : "deep");

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
        model: { id: ANALYSIS_MODEL_ID },
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
        agent_id: agent.agentId || null,
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
function parseAgentResult(text, { preferFollowUp = false } = {}) {
  const raw = String(text || "").trim();
  const fenced = raw.match(/```(?:json)?\s*\n?([\s\S]*?)```/);
  const jsonStr = fenced ? fenced[1].trim() : raw;

  try {
    const parsed = JSON.parse(jsonStr);
    if (preferFollowUp && parsed && typeof parsed === "object" && !parsed.follow_up_answer) {
      parsed.follow_up_answer = parsed.root_cause || raw;
    }
    return parsed;
  } catch {
    if (preferFollowUp) {
      return {
        follow_up_answer: raw,
        root_cause: "",
        classification: "",
        confidence: "",
      };
    }
    return {
      root_cause: raw,
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
// Fast conversational path: resume prior agent when possible (Cursor-like).
// ---------------------------------------------------------------------------
app.post("/chat", async (req, res) => {
  const {
    message,
    system_prompt = "",
    agent_id = null,
    session_id = null,
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

  const t0 = Date.now();
  const chatSessionId = session_id || (agent_id ? `chat_${agent_id}` : generateSessionId());
  let session = sessions.get(chatSessionId);
  let agent = session?.agent || null;
  let created = false;

  try {
    if (!agent && agent_id) {
      agent = await tryResumeAgent(agent_id, apiKey, FOLLOWUP_MODEL_ID, {});
    }
    if (!agent) {
      agent = await Agent.create({
        apiKey,
        model: { id: FOLLOWUP_MODEL_ID },
        mcpServers: {}, // chat is text-only for speed (no MCP cold-start)
      });
      created = true;
    }

    const prompt = created && system_prompt
      ? `${String(system_prompt).slice(0, 2500)}\n\n---\nUser:\n${message}`
      : String(message);

    const run = await agent.send(prompt);
    const result = await run.wait();
    const reply = (result.result || "").trim();

    sessions.set(chatSessionId, {
      agent,
      agentId: agent.agentId || agent_id || null,
      testcase_name: "chat",
      created_at: session?.created_at || Date.now(),
      last_used: Date.now(),
    });

    console.log(`[chat] ${created ? "new" : "resume"} agent reply in ${Date.now() - t0}ms`);
    return res.json({
      success: true,
      reply,
      agent_id: agent.agentId || agent_id || null,
      session_id: chatSessionId,
    });
  } catch (err) {
    console.error("[chat] Agent error:", err.message);
    if (created && agent) {
      agent[Symbol.asyncDispose]?.().catch(() => {});
    }
    return res.status(502).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// POST /chat-stream
// Streaming conversational path (SSE). Emits {type:delta,text} as the model
// generates, then {type:done,...}. This is what makes it feel like Cursor.
// ---------------------------------------------------------------------------
app.post("/chat-stream", async (req, res) => {
  const {
    message,
    system_prompt = "",
    regression_context = "",
    model = "",
    agent_id = null,
    session_id = null,
    cursor_api_key,
  } = req.body || {};

  if (!message || !String(message).trim()) {
    return res.status(400).json({ error: "message is required" });
  }
  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }

  const modelId = resolveModelId(model || FOLLOWUP_MODEL_ID);

  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  if (typeof res.flushHeaders === "function") res.flushHeaders();

  const send = (obj) => {
    try {
      res.write(`data: ${JSON.stringify(obj)}\n\n`);
    } catch { /* client gone */ }
  };

  const t0 = Date.now();
  const chatSessionId = session_id || (agent_id ? `chat_${agent_id}` : generateSessionId());
  let session = sessions.get(chatSessionId);
  let agent = session?.agent || null;
  let created = false;

  try {
    if (!agent && agent_id) {
      agent = await tryResumeAgent(agent_id, apiKey, modelId, {});
    }
    if (!agent) {
      agent = await Agent.create({
        apiKey,
        model: { id: modelId },
        mcpServers: {}, // text-only for speed (no MCP cold-start)
      });
      created = true;
    }

    // Prepend live regression data on EVERY turn (created or resumed) so data
    // questions ("success count") are answered from real numbers, no MCP calls.
    const ctxBlock = regression_context
      ? `Current regression run data (authoritative — use this for any counts/metrics and for questions about which tests are in the tag; do NOT say data is unavailable):\n${String(regression_context).slice(0, 16000)}\n\n`
      : "";
    const prompt = created && system_prompt
      ? `${String(system_prompt).slice(0, 2500)}\n\n${ctxBlock}---\nUser:\n${message}`
      : `${ctxBlock}${message}`;

    const run = await agent.send(prompt);

    let lastFull = "";
    let firstTokenMs = null;
    if (typeof run.supports !== "function" || run.supports("stream")) {
      for await (const event of run.stream()) {
        if (event.type === "assistant" && event.message && Array.isArray(event.message.content)) {
          let full = "";
          for (const block of event.message.content) {
            if (block.type === "text" && block.text) full += block.text;
          }
          if (full) {
            const delta = full.startsWith(lastFull) ? full.slice(lastFull.length) : full;
            lastFull = full;
            if (delta) {
              if (firstTokenMs === null) firstTokenMs = Date.now() - t0;
              send({ type: "delta", text: delta });
            }
          }
        }
      }
    }

    const result = await run.wait();
    const reply = (result.result || lastFull || "").trim();
    if (!lastFull && reply) send({ type: "delta", text: reply });

    sessions.set(chatSessionId, {
      agent,
      agentId: agent.agentId || agent_id || null,
      testcase_name: "chat",
      created_at: session?.created_at || Date.now(),
      last_used: Date.now(),
    });

    send({
      type: "done",
      reply,
      agent_id: agent.agentId || agent_id || null,
      session_id: chatSessionId,
      elapsed_ms: Date.now() - t0,
    });
    res.end();
    console.log(
      `[chat-stream] ${created ? "new" : "resume"} model=${modelId} firstToken=${firstTokenMs}ms total=${Date.now() - t0}ms`,
    );
  } catch (err) {
    console.error("[chat-stream] error:", err.message);
    send({ type: "error", message: err.message });
    if (created && agent) agent[Symbol.asyncDispose]?.().catch(() => {});
    try { res.end(); } catch { /* noop */ }
  }
});

// ---------------------------------------------------------------------------
// POST /chat-warm
// Pre-creates + primes a chat agent so the user's FIRST real message resumes
// (~6s to first token) instead of cold-starting (~16s). Called on page load.
// ---------------------------------------------------------------------------
app.post("/chat-warm", async (req, res) => {
  const { cursor_api_key, model = "" } = req.body || {};
  const apiKey = cursor_api_key || DEFAULT_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ error: "CURSOR_API_KEY not configured on bridge" });
  }
  const modelId = resolveModelId(model || FOLLOWUP_MODEL_ID);
  const t0 = Date.now();
  try {
    const agent = await Agent.create({
      apiKey,
      model: { id: modelId },
      mcpServers: {},
    });
    // Prime with the persona so real turns are short and on-topic.
    const run = await agent.send(
      "You are RegX AI — a fast, concise regression-analysis assistant. " +
        "Answer briefly and directly. Use any regression run data provided in the conversation as authoritative. " +
        "Reply with exactly: READY",
    );
    await run.wait();
    const sessionId = `chat_${agent.agentId || generateSessionId()}`;
    sessions.set(sessionId, {
      agent,
      agentId: agent.agentId || null,
      testcase_name: "chat",
      created_at: Date.now(),
      last_used: Date.now(),
    });
    console.log(`[chat-warm] primed model=${modelId} in ${Date.now() - t0}ms`);
    return res.json({
      success: true,
      agent_id: agent.agentId || null,
      session_id: sessionId,
    });
  } catch (err) {
    console.error("[chat-warm] error:", err.message);
    return res.status(502).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[cursor-bridge] listening on :${PORT}`);
  console.log(`[cursor-bridge] nutest via Sourcegraph = ${NUTEST_SOURCEGRAPH}`);
  console.log(`[cursor-bridge] MCP profile = ${MCP_PROFILE} (triage: ${TRIAGE_MCP_KEYS.join(", ")}; deep: ${DEEP_MCP_KEYS.join(", ")})`);
  console.log(`[cursor-bridge] model = ${MODEL_ID}; analysis model = ${ANALYSIS_MODEL_ID}; follow-up model = ${FOLLOWUP_MODEL_ID}`);
  console.log(`[cursor-bridge] Default API key configured = ${!!DEFAULT_API_KEY}`);
  console.log(`[cursor-bridge] Per-request API keys = enabled`);
  console.log(`[cursor-bridge] batch concurrency = ${BATCH_CONCURRENCY}`);
});
