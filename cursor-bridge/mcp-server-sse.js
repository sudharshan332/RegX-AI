/**
 * RegX MCP Server (SSE Protocol) — exposes RegX regression data as MCP tools.
 *
 * Implements the standard Model Context Protocol using Server-Sent Events.
 * This version is compatible with Cursor's MCP client.
 *
 * Usage:
 *   REGX_BACKEND_URL="http://10.111.52.90:5001" node mcp-server-sse.js
 *
 * Add to Cursor's mcp.json:
 *   {
 *     "regx-data": {
 *       "url": "http://10.111.52.90:5003",
 *       "description": "RegX regression data"
 *     }
 *   }
 */

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import express from "express";

const app = express();
app.use(express.json({ limit: "2mb" }));

const PORT = parseInt(process.env.MCP_SERVER_PORT || "5003", 10);
const REGX_BACKEND = process.env.REGX_BACKEND_URL || "http://localhost:5001";
const REGX_AUTH_TOKEN = process.env.REGX_AUTH_TOKEN || "";

function regxHeaders() {
  const h = { "Content-Type": "application/json" };
  if (REGX_AUTH_TOKEN) h["Authorization"] = `Bearer ${REGX_AUTH_TOKEN}`;
  return h;
}

// ---------------------------------------------------------------------------
// MCP Server Setup
// ---------------------------------------------------------------------------
const mcpServer = new Server(
  {
    name: "regx-data",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// Define tools
mcpServer.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "get_failed_testcases",
        description:
          "Fetch the list of failed testcases for a regression tag. Returns testcase names, exception summaries, failure stages, and IDs.",
        inputSchema: {
          type: "object",
          properties: {
            tag: {
              type: "string",
              description: "Regression tag, e.g. cdp_master_full_reg",
            },
            task_ids: {
              type: "string",
              description: "Comma-separated JITA task IDs (alternative to tag)",
            },
          },
        },
      },
      {
        name: "get_testcase_details",
        description:
          "Get full details for a specific failed testcase including exception, logs, Jira tickets, and triage info.",
        inputSchema: {
          type: "object",
          properties: {
            testcase_id: {
              type: "string",
              description: "The testcase result ID from JITA",
            },
          },
          required: ["testcase_id"],
        },
      },
      {
        name: "update_testcase_analysis",
        description:
          "Write an AI analysis result back to RegX for a specific testcase. The analysis is stored and displayed in the dashboard.",
        inputSchema: {
          type: "object",
          properties: {
            job_id: {
              type: "string",
              description:
                "The batch job ID if part of a batch, or empty for ad-hoc",
            },
            testcase_id: {
              type: "string",
              description: "The testcase result ID",
            },
            analysis: {
              type: "object",
              description:
                "Analysis object with root_cause, classification, failing_code, suggested_fix, confidence, related_components",
            },
          },
          required: ["testcase_id", "analysis"],
        },
      },
    ],
  };
});

// Handle tool calls
mcpServer.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  try {
    switch (name) {
      case "get_failed_testcases":
        return await handleGetFailedTestcases(args);
      case "get_testcase_details":
        return await handleGetTestcaseDetails(args);
      case "update_testcase_analysis":
        return await handleUpdateAnalysis(args);
      default:
        throw new Error(`Unknown tool: ${name}`);
    }
  } catch (err) {
    console.error(`[mcp-server] Error in tool ${name}:`, err.message);
    return {
      content: [
        {
          type: "text",
          text: `Error: ${err.message}`,
        },
      ],
      isError: true,
    };
  }
});

// ---------------------------------------------------------------------------
// Tool handlers
// ---------------------------------------------------------------------------

async function handleGetFailedTestcases(args) {
  const params = new URLSearchParams({
    include: "basic,exception_summary,intermittent",
  });
  if (args.tag) params.set("tag", args.tag);
  else if (args.task_ids) params.set("task_ids", args.task_ids);
  else throw new Error("Either tag or task_ids is required");

  const url = `${REGX_BACKEND}/mcp/regression/failed-analysis/analyze?${params}`;
  const resp = await fetch(url, { headers: regxHeaders() });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Backend returned ${resp.status}: ${text}`);
  }
  const data = await resp.json();

  const testcases = (data.results || []).map((r) => ({
    testcase_id: r.testcase_id,
    testcase_name: r.testcase_name,
    failure_stage: r.failure_stage,
    exception_summary: r.exception_summary,
    jira_tickets: r.jira_tickets,
    regression_owner: r.regression_owner,
  }));

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify({ testcases, count: testcases.length }, null, 2),
      },
    ],
  };
}

async function handleGetTestcaseDetails(args) {
  const url = `${REGX_BACKEND}/mcp/regression/failed-analysis/testcase-detail?testcase_id=${args.testcase_id}`;
  const resp = await fetch(url, { headers: regxHeaders() });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Backend returned ${resp.status}: ${text}`);
  }
  const data = await resp.json();

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(data, null, 2),
      },
    ],
  };
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
    throw new Error(`Backend returned ${resp.status}: ${text}`);
  }
  const data = await resp.json();

  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(data),
      },
    ],
  };
}

// ---------------------------------------------------------------------------
// Express routes for SSE transport
// ---------------------------------------------------------------------------

// Health check
app.get("/health", (_req, res) => {
  res.json({ status: "ok", backend: REGX_BACKEND });
});

// Root SSE endpoint - Cursor expects this at the root URL
app.get("/", async (req, res) => {
  console.log("[regx-mcp-server] New SSE connection at root");
  const transport = new SSEServerTransport("/message", res);
  await mcpServer.connect(transport);
});

// SSE endpoint for MCP protocol
app.get("/sse", async (req, res) => {
  console.log("[regx-mcp-server] New SSE connection at /sse");
  const transport = new SSEServerTransport("/message", res);
  await mcpServer.connect(transport);
});

// MCP endpoint (alias to SSE for compatibility)
app.get("/mcp", async (req, res) => {
  console.log("[regx-mcp-server] New MCP connection at /mcp");
  const transport = new SSEServerTransport("/message", res);
  await mcpServer.connect(transport);
});

// Message endpoint for SSE transport
app.post("/message", async (req, res) => {
  console.log("[regx-mcp-server] Received message:", req.body);
  // SSE transport handles this internally
  res.status(200).end();
});

// ---------------------------------------------------------------------------
app.listen(PORT, () => {
  console.log(`[regx-mcp-server] SSE protocol listening on :${PORT}`);
  console.log(`[regx-mcp-server] RegX backend = ${REGX_BACKEND}`);
  console.log(`[regx-mcp-server] SSE endpoint: http://localhost:${PORT}/sse`);
  console.log(
    `[regx-mcp-server] Add to Cursor mcp.json: "url": "http://10.111.52.90:${PORT}"`
  );
});
