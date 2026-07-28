/**
 * RegX MCP Server — exposes RegX regression data as MCP tools.
 *
 * When added to Cursor's MCP config, this lets Cursor agents:
 *   - Fetch failed testcases for a given tag
 *   - Get detailed testcase info + logs
 *   - Push analysis results back to RegX
 *
 * Runs as an HTTP MCP server on port 5003 (configurable).
 * Talks to the Flask backend at REGX_BACKEND_URL (default http://localhost:5001).
 */

import express from "express";

const app = express();
app.use(express.json({ limit: "2mb" }));

const PORT = parseInt(process.env.MCP_SERVER_PORT || "5003", 10);
const REGX_BACKEND = process.env.REGX_BACKEND_URL || "http://localhost:5001";

// Auth token for RegX backend (JWT); callers can set this via env
const REGX_AUTH_TOKEN = process.env.REGX_AUTH_TOKEN || "";

function regxHeaders() {
  const h = { "Content-Type": "application/json" };
  if (REGX_AUTH_TOKEN) h["Authorization"] = `Bearer ${REGX_AUTH_TOKEN}`;
  return h;
}

// ---------------------------------------------------------------------------
// MCP Tool Definitions (served at GET /tools for discovery)
// ---------------------------------------------------------------------------
const TOOLS = [
  {
    name: "get_failed_testcases",
    description: "Fetch the list of failed testcases for a regression tag. Returns testcase names, exception summaries, failure stages, and IDs.",
    inputSchema: {
      type: "object",
      properties: {
        tag: { type: "string", description: "Regression tag, e.g. cdp_master_full_reg" },
        task_ids: { type: "string", description: "Comma-separated JITA task IDs (alternative to tag)" },
      },
    },
  },
  {
    name: "get_testcase_details",
    description: "Get full details for a specific failed testcase including exception, logs, Jira tickets, and triage info.",
    inputSchema: {
      type: "object",
      properties: {
        testcase_id: { type: "string", description: "The testcase result ID from JITA" },
      },
      required: ["testcase_id"],
    },
  },
  {
    name: "update_testcase_analysis",
    description: "Write an AI analysis result back to RegX for a specific testcase. The analysis is stored and displayed in the dashboard.",
    inputSchema: {
      type: "object",
      properties: {
        job_id: { type: "string", description: "The batch job ID if part of a batch, or empty for ad-hoc" },
        testcase_id: { type: "string", description: "The testcase result ID" },
        analysis: {
          type: "object",
          description: "Analysis object with root_cause, classification, failing_code, suggested_fix, confidence, related_components",
        },
      },
      required: ["testcase_id", "analysis"],
    },
  },
];

// ---------------------------------------------------------------------------
// MCP Protocol endpoints
// ---------------------------------------------------------------------------

// Tool listing (MCP discovery)
app.get("/tools", (_req, res) => {
  res.json({ tools: TOOLS });
});

// Tool invocation
app.post("/call-tool", async (req, res) => {
  const { name, arguments: args } = req.body;

  try {
    switch (name) {
      case "get_failed_testcases":
        return res.json(await handleGetFailedTestcases(args));
      case "get_testcase_details":
        return res.json(await handleGetTestcaseDetails(args));
      case "update_testcase_analysis":
        return res.json(await handleUpdateAnalysis(args));
      default:
        return res.status(400).json({ error: `Unknown tool: ${name}` });
    }
  } catch (err) {
    console.error(`[mcp-server] Error in tool ${name}:`, err.message);
    return res.status(500).json({ error: err.message });
  }
});

// Health
app.get("/health", (_req, res) => {
  res.json({ status: "ok", backend: REGX_BACKEND });
});

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

async function handleGetFailedTestcases(args) {
  const params = new URLSearchParams({ include: "basic,exception_summary,intermittent" });
  if (args.tag) params.set("tag", args.tag);
  else if (args.task_ids) params.set("task_ids", args.task_ids);
  else return { error: "Either tag or task_ids is required" };

  const url = `${REGX_BACKEND}/mcp/regression/failed-analysis/analyze?${params}`;
  const resp = await fetch(url, { headers: regxHeaders() });
  if (!resp.ok) {
    const text = await resp.text();
    return { error: `Backend returned ${resp.status}: ${text}` };
  }
  const data = await resp.json();
  // Return a trimmed-down list
  const testcases = (data.results || []).map(r => ({
    testcase_id: r.testcase_id,
    testcase_name: r.testcase_name,
    failure_stage: r.failure_stage,
    exception_summary: r.exception_summary,
    jira_tickets: r.jira_tickets,
    regression_owner: r.regression_owner,
  }));
  return { content: [{ type: "text", text: JSON.stringify(testcases, null, 2) }] };
}

async function handleGetTestcaseDetails(args) {
  const url = `${REGX_BACKEND}/mcp/regression/failed-analysis/testcase-detail?testcase_id=${args.testcase_id}`;
  const resp = await fetch(url, { headers: regxHeaders() });
  if (!resp.ok) {
    const text = await resp.text();
    return { error: `Backend returned ${resp.status}: ${text}` };
  }
  const data = await resp.json();
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
}

async function handleUpdateAnalysis(args) {
  const url = `${REGX_BACKEND}/mcp/regression/cursor-ai/result`;
  const resp = await fetch(url, {
    method: "POST",
    headers: regxHeaders(),
    body: JSON.stringify({
      job_id: args.job_id || "",
      testcase_id: args.testcase_id,
      analysis: args.analysis,
    }),
  });
  if (!resp.ok) {
    const text = await resp.text();
    return { error: `Backend returned ${resp.status}: ${text}` };
  }
  const data = await resp.json();
  return { content: [{ type: "text", text: JSON.stringify(data) }] };
}

// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[regx-mcp-server] listening on :${PORT}`);
  console.log(`[regx-mcp-server] RegX backend = ${REGX_BACKEND}`);
});
