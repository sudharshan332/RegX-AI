import React, { useEffect, useState } from "react";
import api from "./api";
import { API_BASE_URL } from "./config";
import AiMarkdown from "./components/AiMarkdown";
import TriageGenieCoverageModal from "./components/TriageGenieCoverageModal";
import {
  buildJitaResultsUrls,
  extractJitaTaskIds,
  mergeJitaTaskIds,
  normalizeJitaTaskId,
  normalizeJitaTaskIdList,
} from "./utils/jitaTaskIds";
import { shouldRefetchOwnerJiraDetails } from "./utils/dashboardRefreshAfterAppend";
import {
  clearFullRegressionLink,
  persistFullRegressionLink,
  readScopedFullRegressionTaskIds,
  scopeToRequestPayload,
  shouldPostTriageScope,
  TG_SCOPE_POST_THRESHOLD,
} from "./utils/regressionScope";
import "./RegressionHome.css";

const API_URL = `${API_BASE_URL}/mcp/regression/home`;
const CONFIG_API = `${API_BASE_URL}/mcp/regression/config`;
const CONFIG_TAGS_API = `${API_BASE_URL}/mcp/regression/config/tags`;
const TAG_EXTRA_TASK_IDS_API = `${API_BASE_URL}/mcp/regression/config/tag-extra-task-ids`;
const TCMS_OVERALL_QI_API = `${API_BASE_URL}/mcp/regression/tcms-overall-qi`;
const TEAM_CONFIG_API = `${API_BASE_URL}/mcp/regression/team-config`;
const DEFAULT_TAG = "cdp_master_full_reg";
const JITA_RESULTS_URL = "https://jita.eng.nutanix.com/results?task_ids=";
const JIRA_URL = "https://jira.nutanix.com/browse/";
const OWNER_TRIAGE_REPORT_API = `${API_BASE_URL}/mcp/regression/owner-triage-report`;

const safeScopedTaskIds = (scopeTag = null) => {
  const ids = readScopedFullRegressionTaskIds(scopeTag);
  return Array.isArray(ids) ? ids : [];
};

/** TCMS milestone from branch: ganges-7.6.0.6-stable → 7.6.0.6, ganges-7.6-stable → 7.6 */
const resolveTcmsMilestone = (branch) => {
  const raw = (branch || "").trim();
  const lower = raw.toLowerCase();
  if (lower === "master" || lower === "main") return "master";
  const ganges = raw.match(/^ganges-(\d+(?:\.\d+)+)-stable$/i);
  if (ganges) return ganges[1];
  const m = raw.match(/(\d+(?:\.\d+)+)/);
  return m ? m[1] : branch;
};

/** Collect JITA task IDs for the selected job only (scoped Full regression + rows). */
const collectJitaTaskIdsFromPage = (rowList = []) => {
  const seen = new Set();
  const out = [];
  const add = (ids) => {
    (ids || []).forEach((raw) => {
      const id = normalizeJitaTaskId(raw);
      if (id && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    });
  };

  const tag = (localStorage.getItem("regressionDashboardTag") || "").trim();
  add(safeScopedTaskIds(tag || null));
  (rowList || []).forEach((row) => add(row.actualTasks || []));
  return out;
};

/**
 * Build API params for the selected dashboard job (home / QI / triage-count).
 * Tag mode → tag only (JITA tester_tag = selected job; avoids 414 from mega task_ids).
 * Task-ids mode → Full regression link IDs.
 * Explicit taskIdsToUse wins only when no tag (or caller is task_ids mode).
 */
const resolveTagOrTaskIdsParams = (tagToUse, taskIdsToUse, tagState) => {
  const params = {};
  const activeTag = (tagToUse || tagState || "").trim() || null;
  const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";

  // Selected job by tag: never send Full-link task_ids (stale mega-lists → JITA 414)
  if (savedMode === "tag" || activeTag) {
    const tag = activeTag || (localStorage.getItem("regressionDashboardTag") || "").trim();
    if (tag) {
      params.tag = tag;
      return params;
    }
  }

  if (taskIdsToUse) {
    const ids = Array.isArray(taskIdsToUse)
      ? taskIdsToUse.map(normalizeJitaTaskId).filter(Boolean)
      : String(taskIdsToUse)
          .split(",")
          .map(normalizeJitaTaskId)
          .filter(Boolean);
    if (ids.length) {
      params.task_ids = ids.join(",");
      return params;
    }
  }

  const scoped = safeScopedTaskIds(null);
  if (scoped.length) {
    params.task_ids = scoped.join(",");
  }
  return params;
};

/**
 * Scope for Triage Accuracy / TG analysis: Regression_Run_Tasks Full link wins
 * (same task set as JITA → View in Triage Genie). Tag kept for label/cache.
 */
const resolveTriageAccuracyScope = (tagToUse, taskIdsToUse, tagState, globalIds = []) => {
  const activeTag = (
    tagToUse ||
    tagState ||
    localStorage.getItem("regressionDashboardTag") ||
    ""
  ).trim() || null;

  let taskIds = [];
  if (taskIdsToUse) {
    taskIds = Array.isArray(taskIdsToUse)
      ? taskIdsToUse.map(normalizeJitaTaskId).filter(Boolean)
      : String(taskIdsToUse)
          .split(",")
          .map(normalizeJitaTaskId)
          .filter(Boolean);
  }
  if (!taskIds.length && Array.isArray(globalIds) && globalIds.length) {
    taskIds = globalIds.map(normalizeJitaTaskId).filter(Boolean);
  }
  if (!taskIds.length) {
    taskIds = safeScopedTaskIds(activeTag);
  }

  return {
    mode: taskIds.length ? "task_ids" : "tag",
    tag: activeTag,
    taskIds: taskIds.length ? taskIds : null,
  };
};

// Bug-type color code shared across the owner breakdown tiles and the donut graph.
const BUG_TYPE_COLORS = {
  "Product Bug": "#c45c5c", // muted brick red
  "Test Bug": "#c9954a",    // muted gold
  "Environment": "#5b82b8", // muted slate blue
  "Flaky": "#8b74a8",       // muted purple
  "Other": "#8d939c",       // muted grey
};

// Classify a Jira issue type string into a bug category.
// Rule (per product): any "test" issue type -> Test Bug, any "bug" -> Product Bug.
const categorizeBugType = (issueType) => {
  if (!issueType) return null;
  const s = String(issueType).toLowerCase();
  if (s.includes("environment")) return "Environment";
  if (s.includes("flaky")) return "Flaky";
  if (s.includes("test") || s.includes("testbed")) return "Test Bug";
  if (s.includes("bug")) return "Product Bug";
  return null;
};

// Resolve the bug type for a ticket, preferring the backend-provided value.
const bugTypeOf = (jiraInfo) => {
  if (!jiraInfo) return null;
  return jiraInfo.bug_type || categorizeBugType(jiraInfo.issue_type);
};

// Build a Jira search URL (JQL "issuekey in (...)") for a set of tickets.
const jiraJqlUrl = (tickets) => {
  const list = Array.from(new Set(tickets)).filter(Boolean);
  if (list.length === 0) return null;
  return `https://jira.nutanix.com/issues/?jql=${encodeURIComponent(`issuekey in (${list.join(",")}) ORDER BY status`)}`;
};

const openTickets = (tickets) => {
  const url = jiraJqlUrl(tickets);
  if (url) window.open(url, "_blank", "noopener,noreferrer");
};

// Derive a risk level from an overall QI impact value (mirrors backend thresholds).
const riskFromQi = (qi) => {
  const n = typeof qi === "number" ? qi : parseFloat(qi);
  if (isNaN(n)) return null;
  if (n <= -5) return "Critical";
  if (n <= -2) return "High";
  if (n <= -1) return "Medium";
  return "Low";
};

const RISK_COLORS = {
  Critical: { bg: "#fee2e2", color: "#991b1b" },
  High: { bg: "#ffedd5", color: "#9a3412" },
  Medium: { bg: "#fef9c3", color: "#854d0e" },
  Low: { bg: "#dcfce7", color: "#166534" },
};

// Pie chart of bug-type totals. Hover a slice for its ticket count ("Label - N").
// The pie is display-only; use the legend on the right to open Jira.
function BugPie({ segments, total, size = 150 }) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 2;
  const active = segments.filter((s) => s.value > 0);
  const pointOnCircle = (deg) => {
    const rad = ((deg - 90) * Math.PI) / 180; // start from 12 o'clock
    return [cx + r * Math.cos(rad), cy + r * Math.sin(rad)];
  };
  let angle = 0;
  return (
    <div className="rh-bug-pie" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label="Bug type distribution">
        {total === 0 && <circle cx={cx} cy={cy} r={r} fill="#eef2f7" />}
        {active.length === 1 && (
          <circle cx={cx} cy={cy} r={r} fill={active[0].color} className="rh-bug-pie-slice">
            <title>{`${active[0].label} ${active[0].value} (100%)`}</title>
          </circle>
        )}
        {active.length > 1 &&
          active.map((s) => {
            const pct = s.value / total;
            const sweep = pct * 360;
            const start = angle;
            const end = angle + sweep;
            angle = end;
            const [x1, y1] = pointOnCircle(start);
            const [x2, y2] = pointOnCircle(end);
            const largeArc = sweep > 180 ? 1 : 0;
            const d = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
            return (
              <path
                key={s.label}
                d={d}
                fill={s.color}
                stroke="#fff"
                strokeWidth="1"
                className="rh-bug-pie-slice"
              >
                <title>{`${s.label} (${Math.round(pct * 100)}%)`}</title>
              </path>
            );
          })}
      </svg>
    </div>
  );
}

// Load tag from localStorage or use default
const getStoredTag = () => {
  const stored = localStorage.getItem("regressionDashboardTag");
  return stored || DEFAULT_TAG;
};


// Load advanced action options from localStorage
const getStoredAdvancedOptions = () => {
  const defaults = {
    triageCount: true, // Load by default
    triageAccuracy: false, // Triage Accuracy Analyzer
    triageGenieCoverage: false, // Triage Genie coverage
    qiSummaryReport: false,
    flakyTestInsights: false,
    aiRootCauseSummary: false,
    regressionRiskScore: false,
    bulkIssuesQiImpact: false,
    qiImpactedBulkIssue: false, // QI Impacted Bulk issue - not loaded by default
    tcmsOverview: false // TCMS Overview & Comparison
  };
  const stored = localStorage.getItem("regressionDashboardAdvancedOptions");
  if (!stored) return defaults;
  try {
    return { ...defaults, ...JSON.parse(stored) };
  } catch {
    return defaults;
  }
};

export default function RegressionHome() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tag, setTag] = useState(getStoredTag());
  const [showConfigModal, setShowConfigModal] = useState(false);
  const [showAddRemoveTaskIds, setShowAddRemoveTaskIds] = useState(false);
  const [tgCoverageOpen, setTgCoverageOpen] = useState(false);
  const [configTagInput, setConfigTagInput] = useState(tag);
  const [addedTags, setAddedTags] = useState([]);
  const [defaultTag, setDefaultTag] = useState(null);
  const [newTagInput, setNewTagInput] = useState("");
  const [inputMode, setInputMode] = useState(() => {
    return localStorage.getItem("regressionDashboardInputMode") || "tag";
  });
  // Local state for modal input mode (doesn't trigger API calls)
  const [modalInputMode, setModalInputMode] = useState("tag");
  const [configTaskIdsInput, setConfigTaskIdsInput] = useState(() => {
    const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
    return savedTaskIds ? JSON.parse(savedTaskIds).join(", ") : "";
  });
  // Add / remove JITA task IDs + tag under active tag (Configuration → tag mode)
  const [taskIdsActionInput, setTaskIdsActionInput] = useState("");
  const [appendingTaskIds, setAppendingTaskIds] = useState(false);
  const [removingTaskIds, setRemovingTaskIds] = useState(false);
  // Quiet inline status — no alerts, no full-page refresh
  const [taskIdsActionStatus, setTaskIdsActionStatus] = useState(null);
  // Track task IDs as string to trigger useEffect when they change
  const [taskIdsKey, setTaskIdsKey] = useState(() => {
    const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
    return savedTaskIds ? savedTaskIds : null; // Store as string for comparison
  });
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [advancedOptions, setAdvancedOptions] = useState(getStoredAdvancedOptions());
  const [triageCount, setTriageCount] = useState(null);
  const [qiSummaryReport, setQiSummaryReport] = useState(null);
  const [loadingTriage, setLoadingTriage] = useState(false);
  const [loadingQiSummary, setLoadingQiSummary] = useState(false);
  const [loadingBulkQi, setLoadingBulkQi] = useState(false); // Separate loading state for bulk QI
  const [triageAccuracyData, setTriageAccuracyData] = useState(null);
  const [loadingTriageAccuracy, setLoadingTriageAccuracy] = useState(false);
  const [configLoaded, setConfigLoaded] = useState(false); // Track if config has been loaded from JSON
  const [branchQiData, setBranchQiData] = useState({});
  const [branchQiLoading, setBranchQiLoading] = useState({});
  const [tcmsDetailModal, setTcmsDetailModal] = useState(null);
  const [teamConfig, setTeamConfig] = useState(null);
  const [bulkIssuesAiAnalysis, setBulkIssuesAiAnalysis] = useState(null);
  const [loadingBulkAi, setLoadingBulkAi] = useState(false);
  const [ownerTicketsAiAnalysis, setOwnerTicketsAiAnalysis] = useState(null);
  const [loadingOwnerAi, setLoadingOwnerAi] = useState(false);
  const [ownerJiraDetails, setOwnerJiraDetails] = useState({});
  const [loadingJiraDetails, setLoadingJiraDetails] = useState(false);
  const [jiraDetailsError, setJiraDetailsError] = useState(null);

  // TCMS Overview & Comparison
  const [tcmsOverviewData, setTcmsOverviewData] = useState(null);
  const [loadingTcmsOverview, setLoadingTcmsOverview] = useState(false);
  const [jitaTcmsComparison, setJitaTcmsComparison] = useState(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [showComparisonModal, setShowComparisonModal] = useState(false);
  const [comparisonActiveTab, setComparisonActiveTab] = useState("matched");

  // Owner triage report (notebook schema) — FE holds full task_ids list
  const [ownerReportTaskIds, setOwnerReportTaskIds] = useState([]);
  const [ownerReportRows, setOwnerReportRows] = useState(null);
  const [ownerReportMeta, setOwnerReportMeta] = useState(null);
  const [loadingOwnerReport, setLoadingOwnerReport] = useState(false);
  const [ownerReportError, setOwnerReportError] = useState(null);
  const [ownerReportInvalid, setOwnerReportInvalid] = useState([]);
  // Global JITA task IDs (option B) — drives Regression_Run_Tasks link
  const [globalJitaTaskIds, setGlobalJitaTaskIds] = useState(() => {
    try {
      const saved = localStorage.getItem("regressionDashboardTaskIds");
      return saved ? JSON.parse(saved).map(normalizeJitaTaskId).filter(Boolean) : [];
    } catch (_) {
      return [];
    }
  });
  // Deep Analysis tabs state
  const [activeTab, setActiveTab] = useState("home");
  const [deepAnalysisTabs, setDeepAnalysisTabs] = useState([]);
  const [deepAnalysisResults, setDeepAnalysisResults] = useState({});
  const [deepAnalysisLoading, setDeepAnalysisLoading] = useState({});
  const [deepAnalysisSessions, setDeepAnalysisSessions] = useState({});
  const [deepAnalysisFollowUp, setDeepAnalysisFollowUp] = useState({});
  const [deepAnalysisFollowUpLoading, setDeepAnalysisFollowUpLoading] = useState({});
  const [deepAnalysisHistory, setDeepAnalysisHistory] = useState({});

  // Helper function to determine QI color based on value
  const qiColor = (val) => {
    if (val === "error") return "#dc3545";
    if (val >= 80) return "#28a745";
    if (val >= 50) return "#fd7e14";
    return "#dc3545";
  };

  // Parse JITA task link or comma-separated task IDs
  const parseTaskIds = (input) => {
    if (!input || !input.trim()) return [];
    
    const trimmed = input.trim();
    
    // Check if it's a JITA link
    if (trimmed.includes("jita.eng.nutanix.com") || trimmed.includes("jita.nutanix.com")) {
      try {
        const url = new URL(trimmed);
        const taskIdsParam = url.searchParams.get("task_ids");
        if (taskIdsParam) {
          return taskIdsParam.split(",").map(id => id.trim()).filter(id => id);
        }
      } catch (e) {
        console.error("Error parsing JITA link:", e);
      }
    }
    
    // Otherwise, treat as comma-separated task IDs
    return trimmed.split(",").map(id => id.trim()).filter(id => id);
  };

  // Load configuration from JSON file on component mount
  useEffect(() => {
    // Hidden Branches feature removed — drop stale client filter
    try {
      localStorage.removeItem("regressionDashboardHiddenBranches");
    } catch (_) { /* ignore */ }

    const loadConfigFromJSON = async () => {
      try {
        const response = await api.get(CONFIG_API);
        const config = response.data;
        
        setAddedTags(config.added_tags || []);
        setDefaultTag(config.default_tag || null);
        
        if (config.input_mode === "tag") {
          const effectiveTag = config.default_tag || config.tag || "";
          setTag(effectiveTag || null);
          setInputMode("tag");
          setConfigTagInput(effectiveTag);
          setModalInputMode("tag");
          localStorage.setItem("regressionDashboardTag", effectiveTag || "");
          localStorage.setItem("regressionDashboardInputMode", "tag");
          localStorage.removeItem("regressionDashboardTaskIds");
          setTaskIdsKey(null);
        } else if (config.input_mode === "task_ids" && config.task_ids && config.task_ids.length > 0) {
          // Load task IDs configuration
          setTag(null);
          setInputMode("task_ids");
          setModalInputMode("task_ids");
          setConfigTaskIdsInput(config.task_ids.join(", "));
          const taskIdsString = JSON.stringify(config.task_ids);
          setTaskIdsKey(taskIdsString);
          localStorage.setItem("regressionDashboardInputMode", "task_ids");
          localStorage.setItem("regressionDashboardTaskIds", taskIdsString);
          localStorage.removeItem("regressionDashboardTag");
        }
        setConfigLoaded(true);
      } catch (error) {
        console.error("Error loading configuration from JSON:", error);
        // Fallback to localStorage if JSON load fails
        setConfigLoaded(true);
      }
    };
    
    loadConfigFromJSON();

    api.get(TEAM_CONFIG_API)
      .then((res) => setTeamConfig(res.data?.team_config || {}))
      .catch((err) => console.error("Error loading team config:", err));
  }, []); // Only run on mount

  const activeConfigTag = (
    defaultTag ||
    configTagInput ||
    tag ||
    ""
  ).trim();

  // When config modal opens, refresh config to sync addedTags and defaultTag
  useEffect(() => {
    if (showConfigModal) {
      api.get(CONFIG_API).then((res) => {
        const c = res.data;
        setAddedTags(c.added_tags || []);
        setDefaultTag(c.default_tag || null);
        if (c.input_mode === "tag") {
          setConfigTagInput(c.default_tag || c.tag || "");
        }
      }).catch(() => {});
    }
  }, [showConfigModal]);

  // Fetch data based on current configuration
  const fetchData = async (params) => {
    try {
      setLoading(true);
      const response = await api.get(API_URL, { params });
      if (response.data && response.data.runs && Array.isArray(response.data.runs)) {
        // Debug: Log branch information for troubleshooting
        console.log("Raw runs data:", response.data.runs.map(r => ({ task_id: r.task_id, branch: r.branch, label: r.label })));
        
        // Check if there are missing task IDs and show a warning
        if (response.data.missing_task_ids && response.data.missing_task_ids.length > 0) {
          const missingCount = response.data.missing_task_ids.length;
          const requestedCount = response.data.requested_count || 0;
          const foundCount = response.data.found_count || response.data.runs.length;
          console.warn(`Warning: ${missingCount} out of ${requestedCount} task IDs were not found in the database. Only ${foundCount} tasks were found.`);
          if (missingCount === requestedCount) {
            alert(`None of the ${requestedCount} task IDs were found in the database. Please verify the task IDs are correct.`);
          } else {
            alert(`Warning: ${missingCount} out of ${requestedCount} task IDs were not found. Only ${foundCount} tasks will be displayed.`);
          }
        }
        
        const aggregated = aggregateByBranch(response.data.runs, response.data.branch_start_dates || {});
        console.log("Aggregated by branch:", aggregated);
        setRows(aggregated);
        
      } else {
        console.error("Invalid response data or empty runs:", response.data);
        setRows([]);
        if (params.task_ids) {
          alert("No data was returned for the provided task IDs. Please verify the task IDs are correct and exist in the database.");
        }
      }
      setLoading(false);
    } catch (err) {
      console.error("Error fetching regression data:", err);
      setRows([]);
      setLoading(false);
      if (params.task_ids) {
        alert(`Failed to fetch data for the provided task IDs: ${err.message || "Unknown error"}`);
      }
    }
  };

  useEffect(() => {
    // Wait for config to be loaded before fetching data
    if (!configLoaded) {
      return;
    }
    
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    let params = {};
    
    if (savedMode === "tag" && tag) {
      params = { tag: tag };
    } else if (savedMode === "task_ids") {
      const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
      if (savedTaskIds) {
        try {
          const taskIds = JSON.parse(savedTaskIds);
          if (taskIds && taskIds.length > 0) {
            params = { task_ids: taskIds.join(",") };
          } else {
            setLoading(false);
            return;
          }
        } catch (e) {
          console.error("Error parsing task IDs:", e);
          setLoading(false);
          return;
        }
      } else {
        setLoading(false);
        return;
      }
    } else {
      setLoading(false);
      return;
    }
    
    fetchData(params);
  }, [tag, inputMode, taskIdsKey, configLoaded]);

  // Load Triage Count for selected job (tag = tester_tag job; task_ids mode = Full link)
  useEffect(() => {
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && tag) {
      fetchTriageCount(tag, null);
    } else if (savedMode === "task_ids") {
      const ids = globalJitaTaskIds.length
        ? globalJitaTaskIds
        : safeScopedTaskIds(null);
      if (ids.length > 0) {
        fetchTriageCount(null, ids.join(","));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tag, inputMode, taskIdsKey]);

  // Keep global JITA link list in sync when config / taskIdsKey changes (tag-scoped)
  useEffect(() => {
    const activeTag = (tag || localStorage.getItem("regressionDashboardTag") || "").trim();
    const mode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (mode === "tag" && activeTag) {
      const linkTag = (localStorage.getItem("regressionDashboardFullLinkTag") || "").trim();
      if (linkTag && linkTag !== activeTag) {
        clearFullRegressionLink();
        setGlobalJitaTaskIds([]);
        return;
      }
    }
    const ids = safeScopedTaskIds(mode === "tag" ? activeTag || null : null);
    setGlobalJitaTaskIds(ids);
  }, [taskIdsKey, tag]);

  // Tag mode: ALWAYS replace Regression_Run_Tasks from current home rows (no cross-job merge).
  useEffect(() => {
    if (inputMode !== "tag") return;
    const currentTag = (tag || "").trim();
    if (!currentTag) return;

    const fromRows = [];
    const seen = new Set();
    (rows || []).forEach((row) => {
      (row.actualTasks || []).forEach((raw) => {
        const id = normalizeJitaTaskId(raw);
        if (id && !seen.has(id)) {
          seen.add(id);
          fromRows.push(id);
        }
      });
    });
    if (!fromRows.length) return;

    const same =
      fromRows.length === globalJitaTaskIds.length &&
      fromRows.every((id, i) => id === globalJitaTaskIds[i]);
    if (!same) {
      updateRegressionLinkQuietly(fromRows, currentTag);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- sync when home rows / tag change
  }, [rows, inputMode, tag]);

  // Owner triage report for selected job
  useEffect(() => {
    if (!advancedOptions.triageCount) return;
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && tag) {
      fetchOwnerTriageReport({ tagToUse: tag });
      return;
    }
    const ids = globalJitaTaskIds.length
      ? globalJitaTaskIds
      : safeScopedTaskIds(null);
    if (ids.length > 0) {
      setOwnerReportTaskIds(ids);
      fetchOwnerTriageReport({ taskIds: ids });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advancedOptions.triageCount, tag, inputMode, taskIdsKey]);

  // Triage Accuracy for selected job (Full link = View in Triage Genie scope)
  useEffect(() => {
    if (!advancedOptions.triageAccuracy) return;
    const ids = globalJitaTaskIds.length
      ? globalJitaTaskIds
      : safeScopedTaskIds(tag || null);
    if (ids.length > 0) {
      fetchTriageAccuracy(tag || null, ids.join(","));
    } else if (tag) {
      fetchTriageAccuracy(tag, null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advancedOptions.triageAccuracy, tag, inputMode, taskIdsKey]);

  // QI Summary for selected job
  useEffect(() => {
    if (!advancedOptions.qiSummaryReport) return;
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && tag) {
      fetchQiSummaryReport(tag, null);
    } else {
      const ids = globalJitaTaskIds.length
        ? globalJitaTaskIds
        : safeScopedTaskIds(null);
      if (ids.length > 0) {
        fetchQiSummaryReport(null, ids.join(","));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advancedOptions.qiSummaryReport, tag, inputMode, taskIdsKey]);

  // TCMS Overview for selected job
  useEffect(() => {
    if (!advancedOptions.tcmsOverview) return;
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && tag) {
      fetchTcmsOverview(tag, null);
    } else if (savedMode === "task_ids") {
      const ids = globalJitaTaskIds.length ? globalJitaTaskIds : readScopedFullRegressionTaskIds(tag || null);
      if (ids && ids.length > 0) {
        fetchTcmsOverview(null, ids.join(","));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [advancedOptions.tcmsOverview, tag, inputMode, taskIdsKey]);

  // Fetch JIRA details (status, issue type) for all tickets in owner_ticket_map
  const fetchOwnerJiraDetails = async () => {
    if (!triageCount || !triageCount.owner_ticket_map) return;
    const allTickets = new Set();
    Object.values(triageCount.owner_ticket_map).forEach(tickets => {
      Object.keys(tickets).forEach(t => allTickets.add(t));
    });
    if (allTickets.size === 0) return;
    setLoadingJiraDetails(true);
    setJiraDetailsError(null);
    try {
      const resp = await api.post(`${API_BASE_URL}/mcp/regression/jira-ticket-details`, {
        ticket_ids: Array.from(allTickets)
      }, { timeout: 120000 });
      if (resp.data.success && resp.data.details) {
        setOwnerJiraDetails(resp.data.details);
      } else {
        setJiraDetailsError(resp.data.error || "Could not load Jira bug types");
      }
    } catch (err) {
      console.error("Error fetching JIRA details:", err);
      setJiraDetailsError(
        err.response?.data?.error || "Could not load Jira bug types"
      );
    } finally {
      setLoadingJiraDetails(false);
    }
  };

  // Auto-fetch JIRA details when owner_ticket_map changes (new task IDs → new tickets).
  useEffect(() => {
    if (!triageCount || !triageCount.owner_ticket_map) return;
    const entries = Object.values(ownerJiraDetails);
    const allStale = entries.length > 0 && entries.every(
      (d) => (d?.status === "N/A" || d?.status === "Unknown" || !d?.status) && !d?.bug_type
    );
    if (
      allStale ||
      shouldRefetchOwnerJiraDetails(triageCount.owner_ticket_map, ownerJiraDetails)
    ) {
      fetchOwnerJiraDetails();
    }
  }, [triageCount]);

  // Handle configuration save
  const handleSaveConfig = async () => {
    try {
      if (modalInputMode === "tag") {
        const selectedTag = defaultTag || null;
        
        // Save to JSON file
        const configData = {
          input_mode: "tag",
          default_tag: selectedTag,
          added_tags: addedTags,
          tag: selectedTag || "",
          task_ids: []
        };
        await api.post(CONFIG_API, configData);
        
        // Update local state — reset Full regression link so prior job IDs never leak
        setTag(selectedTag || null);
        setConfigTagInput(selectedTag || "");
        localStorage.setItem("regressionDashboardTag", selectedTag || "");
        localStorage.setItem("regressionDashboardInputMode", "tag");
        clearFullRegressionLink();
        setGlobalJitaTaskIds([]);
        setTaskIdsKey(null);
        
        // Update global inputMode state (this will trigger useEffects)
        setInputMode("tag");
        
        // Close modal first
        setShowConfigModal(false);
        
        // Clear cached QI data so buttons re-appear for fresh load
        setBranchQiData({});

        // Fetch data only if a tag is selected
        if (selectedTag) {
          await fetchData({ tag: selectedTag });
          await fetchTriageCount(selectedTag);
          try {
            if (advancedOptions.qiSummaryReport) {
              await fetchQiSummaryReport(selectedTag);
            } else {
              setQiSummaryReport(null);
              setLoadingQiSummary(false);
            }
            if (advancedOptions.triageAccuracy) {
              await fetchTriageAccuracy(selectedTag);
            }
          } catch (error) {
            console.error("Error loading advanced options data:", error);
          }
        } else {
          setRows([]);
          setTriageCount(null);
          setTriageAccuracyData(null);
          setQiSummaryReport(null);
        }
      } else {
        // Task IDs mode
        const taskIds = parseTaskIds(configTaskIdsInput);
        if (!taskIds || taskIds.length === 0) {
          alert("Please enter JITA Task IDs (comma-separated) or a JITA task link");
          return;
        }
        
        // Save to JSON file
        const configData = {
          input_mode: "task_ids",
          tag: "",
          task_ids: taskIds
        };
        await api.post(CONFIG_API, configData);
        
        // Store task IDs and clear tag (task_ids mode = selected job link)
        setTag(null);
        setDefaultTag(null);
        localStorage.removeItem("regressionDashboardTag");
        localStorage.setItem("regressionDashboardInputMode", "task_ids");
        const normalized = persistFullRegressionLink(taskIds, null);
        setGlobalJitaTaskIds(normalized);
        const taskIdsString = JSON.stringify(normalized);
        
        // Update global inputMode state and taskIdsKey state (this will trigger useEffects)
        setInputMode("task_ids");
        setTaskIdsKey(taskIdsString); // Update key to trigger useEffect
        
        // Close modal first
        setShowConfigModal(false);

        // Clear cached QI data so buttons re-appear for fresh load
        setBranchQiData({});
        
        // Fetch data automatically after save
        await fetchData({ task_ids: taskIds.join(",") });
        
        // Triage Count is always loaded by default, checkbox only controls visibility
        // Refresh triage count using task IDs
        await fetchTriageCount(null, taskIds.join(","));
        
        // Fetch data if advanced options are enabled
        try {
          if (advancedOptions.qiSummaryReport) {
            await fetchQiSummaryReport(null, taskIds.join(","));
          } else {
            setQiSummaryReport(null);
            setLoadingQiSummary(false);
          }
          if (advancedOptions.triageAccuracy) {
            await fetchTriageAccuracy(null, taskIds.join(","));
          }
        } catch (error) {
          console.error("Error loading advanced options data:", error);
        }
      }
      
      // Save advanced options
      localStorage.setItem("regressionDashboardAdvancedOptions", JSON.stringify(advancedOptions));
    } catch (error) {
      console.error("Error saving configuration:", error);
      alert("Failed to save configuration. Please try again.");
    }
  };

  // Add tag to added_tags (lenient - adds even if JITA validation fails)
  const handleAddTag = async () => {
    const tagToAdd = newTagInput.trim();
    if (!tagToAdd) {
      alert("Tag name cannot be empty");
      return;
    }
    setLoadingBranches(true);
    try {
      const response = await api.post(CONFIG_TAGS_API, { tag: tagToAdd });
      const updatedAdded = response.data.added_tags || [];
      setAddedTags(updatedAdded);
      setNewTagInput("");
      // Optionally set newly added tag as default for quick selection
      if (!defaultTag && updatedAdded.includes(tagToAdd)) {
        setDefaultTag(tagToAdd);
        setConfigTagInput(tagToAdd);
      }
      // Preload triage accuracy data in background (saves to per-tag JSON)
      api.get(`${API_BASE_URL}/mcp/regression/triage-accuracy`, { params: { tag: tagToAdd } })
        .then(() => { /* cache warmed */ })
        .catch(() => { /* non-blocking; user can load later when selecting tag */ });
    } catch (err) {
      alert(err.response?.data?.error || "Failed to add tag.");
    } finally {
      setLoadingBranches(false);
    }
  };

  // Delete tag from added_tags (also removes per-tag triage JSON)
  const handleDeleteTag = async (tagToDelete) => {
    if (!window.confirm(`Delete tag "${tagToDelete}"? This will also remove its triage accuracy data.`)) return;
    try {
      const response = await api.delete(CONFIG_TAGS_API, {
        params: { tag: tagToDelete }
      });
      setAddedTags(response.data.added_tags || []);
      if (defaultTag === tagToDelete) {
        setDefaultTag(null);
        setTag(null);
        setConfigTagInput("");
      }
    } catch (err) {
      alert(err.response?.data?.error || "Failed to delete tag.");
    }
  };

  // Fetch Triage Accuracy — Full-link task_ids (Regression_Run_Tasks) win when present
  const fetchTriageAccuracy = async (tagToUse = null, taskIdsToUse = null, reload = false) => {
    setLoadingTriageAccuracy(true);
    try {
      const scope = resolveTriageAccuracyScope(
        tagToUse,
        taskIdsToUse,
        tag,
        globalJitaTaskIds
      );
      if (!scope.tag && !(scope.taskIds && scope.taskIds.length)) {
        setLoadingTriageAccuracy(false);
        return;
      }
      const timeout = 900000; // 15 minutes - Triage Genie lookups can be slow for large runs
      const headers = reload ? { "Cache-Control": "no-cache", "Pragma": "no-cache" } : {};
      let response;
      if (shouldPostTriageScope(scope) || (scope.taskIds && scope.taskIds.length > TG_SCOPE_POST_THRESHOLD)) {
        const body = scopeToRequestPayload(scope, { reload });
        response = await api.post(`${API_BASE_URL}/mcp/regression/triage-accuracy`, body, {
          timeout,
          headers,
        });
      } else {
        const params = {};
        if (scope.tag) params.tag = scope.tag;
        if (scope.taskIds?.length) params.task_ids = scope.taskIds.join(",");
        if (reload) {
          params.reload = "true";
          params._t = Date.now();
        }
        response = await api.get(`${API_BASE_URL}/mcp/regression/triage-accuracy`, {
          params,
          timeout,
          headers,
        });
      }
      setTriageAccuracyData(response.data);
    } catch (err) {
      console.error("Error fetching triage accuracy:", err);
      const status = err.response?.status;
      const data = err.response?.data;
      let msg;
      if (status === 404) {
        msg = "Triage Accuracy endpoint not found (404). Restart the Flask backend to load the latest routes: ./start_backend.sh or python3 backend/test_flask.py";
      } else if (typeof data === "object" && data?.error) {
        msg = data.error;
      } else if (data && typeof data === "string" && (data.toLowerCase().includes("<!doctype") || data.toLowerCase().includes("<html"))) {
        msg = status ? `Backend returned ${status}. Ensure the Flask backend is running and REACT_APP_API_URL is correct. Restart backend: ./start_backend.sh` : "Invalid response from server. Check that the backend is running.";
      } else {
        const networkError = err.code === "ECONNABORTED" ? "Request timed out (15 min)" : err.message || "";
        msg = (status ? `Backend returned ${status}. ` : "") + (networkError ? `Network: ${networkError}. ` : "") + "Ensure Flask backend is running (./start_backend.sh) and REACT_APP_API_URL points to it.";
      }
      setTriageAccuracyData({ error: msg.trim() });
    } finally {
      setLoadingTriageAccuracy(false);
    }
  };

  // Reload Triage Accuracy — prefer Regression_Run_Tasks Full link (View in TG scope)
  const handleReloadTriageAccuracy = () => {
    const effectiveTag = tag || defaultTag || null;
    const ids = globalJitaTaskIds.length
      ? globalJitaTaskIds
      : safeScopedTaskIds(effectiveTag);
    if (ids.length > 0) {
      fetchTriageAccuracy(effectiveTag, ids.join(","), true);
      return;
    }
    if (effectiveTag) {
      fetchTriageAccuracy(effectiveTag, null, true);
      return;
    }
    alert("No tag or Regression_Run_Tasks link configured. Configure in Configuration first.");
  };

  // Download Excel report for Triage Accuracy
  const handleDownloadTriageAccuracyExcel = async () => {
    try {
      const params = {};
      const effectiveTag = tag || defaultTag;
      if (inputMode === "tag" && effectiveTag) {
        params.tag = effectiveTag;
      }
      const response = await api.get(`${API_BASE_URL}/mcp/regression/triage-accuracy/export-excel`, {
        params,
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", "triage_accuracy_report.xlsx");
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Error downloading Excel:", err);
      alert(err.response?.data?.error || "Failed to download Excel report. Load Triage Accuracy data first.");
    }
  };

  // Owner triage report — notebook columns; always send full task_ids when using ID mode
  const fetchOwnerTriageReport = async ({ taskIds = null, tagToUse = null, executionUrl = null } = {}) => {
    setLoadingOwnerReport(true);
    setOwnerReportError(null);
    try {
      const body = {};
      const normalized = (taskIds || []).map(normalizeJitaTaskId).filter(Boolean);
      if (normalized.length > 0) {
        body.task_ids = normalized;
      } else if (executionUrl) {
        body.execution_url = executionUrl;
      } else {
        // Prefer localStorage mode over stale React `tag` after "+" append
        const resolved = resolveTagOrTaskIdsParams(tagToUse, null, tag);
        if (resolved.task_ids) {
          body.task_ids = resolved.task_ids.split(",").map(normalizeJitaTaskId).filter(Boolean);
        } else if (resolved.tag) {
          body.tag = resolved.tag;
        } else {
          setOwnerReportError("No JITA task IDs or tag available.");
          setOwnerReportRows([]);
          setLoadingOwnerReport(false);
          return;
        }
      }

      const response = await api.post(OWNER_TRIAGE_REPORT_API, body, { timeout: 180000 });
      const data = response.data || {};
      if (data.error && !data.rows) {
        setOwnerReportError(data.error);
        setOwnerReportRows([]);
        return;
      }
      setOwnerReportRows(Array.isArray(data.rows) ? data.rows : []);
      setOwnerReportMeta(data.meta || null);
      setOwnerReportInvalid(data.invalid_task_ids || []);
      if (Array.isArray(data.task_ids) && data.task_ids.length > 0) {
        setOwnerReportTaskIds(data.task_ids);
      } else if (taskIds && taskIds.length > 0) {
        setOwnerReportTaskIds(taskIds);
      }
      if (data.error) {
        setOwnerReportError(data.error);
      }
    } catch (err) {
      console.error("Error fetching owner triage report:", err);
      const msg =
        err.response?.data?.error ||
        err.message ||
        "Failed to fetch owner triage report.";
      setOwnerReportError(msg);
      setOwnerReportRows([]);
    } finally {
      setLoadingOwnerReport(false);
    }
  };

  const handleRefreshOwnerTriageSection = async () => {
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    const ids = globalJitaTaskIds.length
      ? globalJitaTaskIds
      : safeScopedTaskIds(savedMode === "tag" ? tag : null);

    if (savedMode === "tag" && tag) {
      await Promise.all([
        fetchOwnerTriageReport({ tagToUse: tag }),
        fetchTriageCount(tag, null),
      ]);
      return;
    }

    if (ids.length > 0) {
      setOwnerReportTaskIds(ids);
      await Promise.all([
        fetchOwnerTriageReport({ taskIds: ids }),
        fetchTriageCount(null, ids.join(",")),
      ]);
      return;
    }

    setOwnerReportError("No JITA task IDs or tag available to refresh.");
  };

  /** 1-click: scrape page for JITA task IDs, else prompt, else fall back to tag. */
  const handleOneClickOwnerReport = async () => {
    let ids = collectJitaTaskIdsFromPage(rows);
    if (ownerReportTaskIds.length > 0) {
      // Prefer already-tracked list (includes user appends)
      ids = ownerReportTaskIds;
    }
    if (ids.length === 0) {
      const prompted = window.prompt(
        "No JITA task IDs found on page. Paste a JITA results URL or comma-separated task IDs:"
      );
      if (prompted == null) return;
      ids = extractJitaTaskIds(prompted);
      if (ids.length === 0 && (tag || "").trim()) {
        await fetchOwnerTriageReport({ tagToUse: tag });
        return;
      }
      if (ids.length === 0) {
        setOwnerReportError("No valid 24-char JITA task IDs found in input.");
        return;
      }
    }
    setOwnerReportTaskIds(ids);
    await fetchOwnerTriageReport({ taskIds: ids });
  };

  const getRegressionLinkTaskIds = () => {
    let base = globalJitaTaskIds.length > 0 ? [...globalJitaTaskIds] : [];
    if (base.length === 0) {
      try {
        const saved = localStorage.getItem("regressionDashboardTaskIds");
        if (saved) {
          base = JSON.parse(saved).map(normalizeJitaTaskId).filter(Boolean);
        }
      } catch (_) { /* ignore */ }
    }
    if (base.length === 0) {
      base = collectJitaTaskIdsFromPage(rows);
    }
    return base;
  };

  /** Update JITA link in memory + localStorage without bumping taskIdsKey (no page refetch). */
  const updateRegressionLinkQuietly = (nextIds, scopeTag = null) => {
    const tagForLink = (
      scopeTag ||
      tag ||
      localStorage.getItem("regressionDashboardTag") ||
      ""
    ).trim();
    const merged = persistFullRegressionLink(nextIds, tagForLink || null);
    setGlobalJitaTaskIds(merged);
    try {
      window.dispatchEvent(
        new CustomEvent("regressionFullLinkUpdated", {
          detail: { taskIds: merged, tag: tagForLink || null },
        })
      );
    } catch (_) { /* ignore */ }
  };

  /**
   * Add task ID(s) + tag in background. Silent: no alerts, no dashboard refresh.
   */
  const handleAppendTaskIdsToTag = async (rawInput) => {
    const prompted = (rawInput != null ? String(rawInput) : taskIdsActionInput).trim();
    if (!prompted) {
      setTaskIdsActionStatus({ type: "warn", text: "Paste a task ID or JITA URL first." });
      return;
    }

    const base = getRegressionLinkTaskIds();
    const { added, duplicates } = mergeJitaTaskIds(base, prompted);
    if (added.length === 0) {
      setTaskIdsActionStatus({
        type: "warn",
        text:
          extractJitaTaskIds(prompted).length === 0
            ? "No valid 24-char JITA task IDs found."
            : `Already in link${duplicates.length ? `: ${duplicates.join(", ")}` : "."}`,
      });
      return;
    }

    const sourceTag = activeConfigTag || (
      localStorage.getItem("regressionDashboardTag") || ""
    ).trim();

    if (!sourceTag) {
      const { merged } = mergeJitaTaskIds(base, added);
      updateRegressionLinkQuietly(merged);
      setTaskIdsActionInput("");
      setTaskIdsActionStatus({
        type: "ok",
        text: `Added to link (${added.length}). No default tag — tag not applied on JITA.`,
      });
      return;
    }

    // Optimistic: clear input, show quiet working status, run API in background
    setTaskIdsActionInput("");
    setAppendingTaskIds(true);
    setTaskIdsActionStatus({
      type: "info",
      text: `Adding ${added.length} task ID(s) in background…`,
    });

    try {
      const resp = await api.post(
        TAG_EXTRA_TASK_IDS_API,
        {
          tag: sourceTag,
          task_ids: added,
          validate_tag: true,
          add_missing_tag: true,
        },
        { timeout: 90000 }
      );
      const data = resp.data || {};
      const accepted = data.newly_added || [];
      const notFound = data.rejected_not_found || [];
      const tagFailed = data.rejected_wrong_tag || [];

      if (accepted.length > 0) {
        const { merged } = mergeJitaTaskIds(base, accepted);
        updateRegressionLinkQuietly(merged);
      }

      const parts = [];
      if (accepted.length) parts.push(`Added ${accepted.length}`);
      if (notFound.length) parts.push(`Not present: ${notFound.join(", ")}`);
      if (tagFailed.length) parts.push(`Tag apply failed: ${tagFailed.join(", ")}`);
      if (!parts.length) parts.push(data.error || "Nothing added");

      setTaskIdsActionStatus({
        type: accepted.length ? (notFound.length || tagFailed.length ? "warn" : "ok") : "warn",
        text: parts.join(" · "),
      });
    } catch (err) {
      console.error("Failed to persist/validate tag_extra_task_ids:", err);
      const data = err.response?.data || {};
      const notFound = data.rejected_not_found || [];
      let text = data.error || "Add failed.";
      if (!err.response) text = "Backend not reachable (:5001).";
      if (notFound.length) text = `Not present: ${notFound.join(", ")}`;
      setTaskIdsActionStatus({ type: "err", text });
    } finally {
      setAppendingTaskIds(false);
    }
  };

  /**
   * Remove tag + drop from link in background. Silent. "Not present" if ID not in link.
   */
  const handleRemoveTaskIdsFromTag = async () => {
    const prompted = taskIdsActionInput.trim();
    if (!prompted) {
      setTaskIdsActionStatus({ type: "warn", text: "Paste a task ID or JITA URL first." });
      return;
    }

    const sourceTag = activeConfigTag;
    if (!sourceTag) {
      setTaskIdsActionStatus({ type: "warn", text: "Select a Default Tag Name first." });
      return;
    }

    const toRemove = extractJitaTaskIds(prompted);
    if (toRemove.length === 0) {
      setTaskIdsActionStatus({ type: "warn", text: "No valid 24-char JITA task IDs found." });
      return;
    }

    const base = getRegressionLinkTaskIds();
    const baseSet = new Set(base.map((id) => String(id).toLowerCase()));
    const present = toRemove.filter((id) => baseSet.has(id));
    const notPresent = toRemove.filter((id) => !baseSet.has(id));

    if (present.length === 0) {
      setTaskIdsActionStatus({
        type: "warn",
        text: `Not present: ${notPresent.join(", ")}`,
      });
      return;
    }

    setTaskIdsActionInput("");
    setRemovingTaskIds(true);
    setTaskIdsActionStatus({
      type: "info",
      text: `Removing ${present.length} task ID(s) in background…`,
    });

    try {
      const resp = await api.post(
        TAG_EXTRA_TASK_IDS_API,
        {
          action: "remove",
          tag: sourceTag,
          task_ids: present,
          remove_tag_from_jita: true,
        },
        { timeout: 90000 }
      );
      const data = resp.data || {};
      const removed = data.removed || data.untagged_now || present;
      const removeSet = new Set(removed.map((t) => String(t).toLowerCase()));
      updateRegressionLinkQuietly(base.filter((id) => !removeSet.has(String(id).toLowerCase())));

      const parts = [];
      if (removed.length) parts.push(`Removed ${removed.length}`);
      if ((data.untag_failed || []).length) {
        parts.push(`Tag strip failed: ${(data.untag_failed || []).join(", ")}`);
      }
      if (notPresent.length) parts.push(`Not present: ${notPresent.join(", ")}`);

      setTaskIdsActionStatus({
        type: (data.untag_failed || []).length || notPresent.length ? "warn" : "ok",
        text: parts.join(" · ") || "Done",
      });
    } catch (err) {
      console.error("Failed to remove task IDs / tag:", err);
      const data = err.response?.data || {};
      let text = data.error || "Remove failed.";
      if (!err.response) text = "Backend not reachable (:5001).";
      setTaskIdsActionStatus({ type: "err", text });
    } finally {
      setRemovingTaskIds(false);
    }
  };

  /** Remove one ID from task_ids-mode textarea (local until Save). */
  const handleRemoveConfigTaskIdChip = (tid) => {
    const id = normalizeJitaTaskId(tid);
    if (!id) return;
    const current = parseTaskIds(configTaskIdsInput);
    setConfigTaskIdsInput(current.filter((x) => normalizeJitaTaskId(x) !== id).join(", "));
  };

  // Fetch Triage Count - supports both tag and task_ids
  // By default, exclude bulk issues QI calculation for faster loading
  const fetchTriageCount = async (tagToUse = null, taskIdsToUse = null, includeBulkQi = false) => {
    setLoadingTriage(true);
    try {
      // CRITICAL: task_ids must win over stale React `tag` state after "+" append
      const params = resolveTagOrTaskIdsParams(tagToUse, taskIdsToUse, tag);
      if (!params.tag && !params.task_ids) {
        setLoadingTriage(false);
        return;
      }

      // Only include bulk QI calculation if explicitly requested
      if (includeBulkQi) {
        params.include_bulk_qi = "true";
      }
      
      const response = await api.get(`${API_BASE_URL}/mcp/regression/triage-count`, {
        params,
        timeout: 180000 // 3 minutes timeout
      });
      setTriageCount(response.data);
    } catch (err) {
      console.error("Error fetching triage count:", err);
      setTriageCount({ error: "Failed to fetch triage count. Please check backend endpoint." });
    } finally {
      setLoadingTriage(false);
    }
  };

  // Fetch Bulk Issues QI Impact separately (when button is clicked)
  const fetchBulkIssuesQi = async () => {
    if (!triageCount || triageCount.error) {
      return; // Need triage count data first
    }
    
    setLoadingBulkQi(true);
    try {
      const params = resolveTagOrTaskIdsParams(null, null, tag);
      if (!params.tag && !params.task_ids) {
        setLoadingBulkQi(false);
        return;
      }
      
      // Request bulk QI calculation
      params.include_bulk_qi = "true";
      
      const response = await api.get(`${API_BASE_URL}/mcp/regression/triage-count`, {
        params,
        timeout: 300000 // 5 minutes timeout for QI calculation
      });
      
      // Update triage count with per-ticket + bulk issues QI data
      if (response.data.bulk_issues_with_qi || response.data.ticket_qi_map) {
        setTriageCount(prev => ({
          ...prev,
          bulk_issues_with_qi: response.data.bulk_issues_with_qi || prev.bulk_issues_with_qi || {},
          ticket_qi_map: response.data.ticket_qi_map || response.data.bulk_issues_with_qi || {}
        }));
      }
    } catch (err) {
      console.error("Error fetching bulk issues QI:", err);
      // Don't set error, just log it
    } finally {
      setLoadingBulkQi(false);
    }
  };

  const fetchBulkIssuesAiAnalysis = async () => {
    if (!triageCount || !triageCount.bulk_issues) return;
    setLoadingBulkAi(true);
    setBulkIssuesAiAnalysis(null);
    try {
      const response = await api.post(
        `${API_BASE_URL}/mcp/regression/ai-analysis/bulk-issues`,
        {
          bulk_issues: triageCount.bulk_issues,
          bulk_issues_with_qi: triageCount.bulk_issues_with_qi || {},
          tag: triageCount.tag || tag || "",
          total_tests_processed: triageCount.total_tests_processed || 0
        },
        { timeout: 120000 }
      );
      if (response.data.success) {
        setBulkIssuesAiAnalysis(response.data.analysis);
      } else {
        setBulkIssuesAiAnalysis(`Error: ${response.data.error || "Unknown error"}`);
      }
    } catch (err) {
      console.error("Error fetching bulk issues AI analysis:", err);
      setBulkIssuesAiAnalysis(`Error: ${err.response?.data?.error || err.message}`);
    } finally {
      setLoadingBulkAi(false);
    }
  };

  const fetchOwnerTicketsAiAnalysis = async () => {
    if (!triageCount || !triageCount.owner_ticket_map) return;
    setLoadingOwnerAi(true);
    setOwnerTicketsAiAnalysis(null);
    try {
      const response = await api.post(
        `${API_BASE_URL}/mcp/regression/ai-analysis/owner-tickets`,
        {
          owner_ticket_map: triageCount.owner_ticket_map,
          triage_summary: triageCount.triage_summary || {},
          tag: triageCount.tag || tag || "",
          total_tests_processed: triageCount.total_tests_processed || 0
        },
        { timeout: 180000 }
      );
      if (response.data.success) {
        setOwnerTicketsAiAnalysis(response.data.analysis);
        if (response.data.jira_details) {
          setOwnerJiraDetails(response.data.jira_details);
        }
      } else {
        setOwnerTicketsAiAnalysis(`Error: ${response.data.error || "Unknown error"}`);
      }
    } catch (err) {
      console.error("Error fetching owner tickets AI analysis:", err);
      setOwnerTicketsAiAnalysis(`Error: ${err.response?.data?.error || err.message}`);
    } finally {
      setLoadingOwnerAi(false);
    }
  };

  // Fetch TCMS Overview
  const fetchTcmsOverview = async (tagToUse, taskIdsToUse) => {
    setLoadingTcmsOverview(true);
    try {
      const params = {
        tag: tagToUse,
        task_ids: taskIdsToUse,
        time_filter: "all"
      };
      const response = await api.get(`${API_BASE_URL}/mcp/regression/tcms-overview`, { params });
      setTcmsOverviewData(response.data);
    } catch (error) {
      console.error("Error fetching TCMS overview:", error);
      setTcmsOverviewData(null);
    } finally {
      setLoadingTcmsOverview(false);
    }
  };

  // Fetch JITA vs TCMS Comparison
  const fetchJitaTcmsComparison = async () => {
    if (!tcmsOverviewData) {
      alert("Please wait for TCMS Overview data to load first");
      return;
    }
    
    setLoadingComparison(true);
    try {
      const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
      let payload = {
        team_name: tcmsOverviewData.team_name,
        branch_name: tcmsOverviewData.branch_name
      };
      
      if (savedMode === "tag" && tag) {
        payload.tag = tag;
      } else {
        const ids = globalJitaTaskIds.length ? globalJitaTaskIds : readScopedFullRegressionTaskIds(tag || null);
        if (ids && ids.length > 0) {
          payload.task_ids = ids;
        } else if (tag) {
          payload.tag = tag;
        }
      }
      
      const response = await api.post(
        `${API_BASE_URL}/mcp/regression/jita-tcms-comparison`,
        payload,
        { timeout: 120000 }
      );
      
      if (response.data.success) {
        setJitaTcmsComparison(response.data);
        setShowComparisonModal(true);
        setComparisonActiveTab("matched");
      } else {
        alert(`Error: ${response.data.error || "Unknown error"}`);
      }
    } catch (error) {
      console.error("Error fetching Jita-TCMS comparison:", error);
      alert(`Error: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoadingComparison(false);
    }
  };

  // --- Deep Analysis Tab handlers ---
  const openDeepAnalysisTab = async (ticket, testName, tests) => {
    const existingTab = deepAnalysisTabs.find(t => t.ticket === ticket);
    if (existingTab) {
      setActiveTab(ticket);
      return;
    }
    const featureParts = (testName || "").split(".");
    const featureArea = featureParts.length >= 3
      ? featureParts.slice(0, 3).join(".")
      : featureParts.slice(0, 2).join(".");
    const newTab = { ticket, testName, featureArea, tests: tests || [] };
    setDeepAnalysisTabs(prev => [...prev, newTab]);
    setActiveTab(ticket);
    setDeepAnalysisLoading(prev => ({ ...prev, [ticket]: true }));
    setDeepAnalysisHistory(prev => ({ ...prev, [ticket]: [] }));

    try {
      const resp = await api.post(
        `${API_BASE_URL}/mcp/regression/cursor-ai/analyze-testcase`,
        {
          testcase_name: testName,
          exception_summary: `Bulk issue ticket ${ticket} affecting ${(tests || []).length} testcases in feature area: ${featureArea}`,
          exception: "",
          test_log_url: "",
          jira_tickets: [ticket],
          failure_stage: "bulk_issue_triage",
        },
        { timeout: 600000 }
      );
      if (resp.data?.success) {
        setDeepAnalysisResults(prev => ({ ...prev, [ticket]: resp.data.analysis }));
        if (resp.data.session_id) {
          setDeepAnalysisSessions(prev => ({ ...prev, [ticket]: resp.data.session_id }));
        }
      } else {
        setDeepAnalysisResults(prev => ({
          ...prev,
          [ticket]: { error: resp.data?.error || "Analysis failed" }
        }));
      }
    } catch (err) {
      const errMsg = err.response?.data?.error || err.message || "Cursor AI analysis failed";
      setDeepAnalysisResults(prev => ({ ...prev, [ticket]: { error: errMsg } }));
    } finally {
      setDeepAnalysisLoading(prev => ({ ...prev, [ticket]: false }));
    }
  };

  const handleDeepAnalysisFollowUp = async (ticket) => {
    const question = (deepAnalysisFollowUp[ticket] || "").trim();
    if (!question) return;
    const sessionId = deepAnalysisSessions[ticket];

    setDeepAnalysisFollowUpLoading(prev => ({ ...prev, [ticket]: true }));
    setDeepAnalysisHistory(prev => ({
      ...prev,
      [ticket]: [...(prev[ticket] || []), { role: "user", text: question }]
    }));
    setDeepAnalysisFollowUp(prev => ({ ...prev, [ticket]: "" }));

    try {
      const tab = deepAnalysisTabs.find(t => t.ticket === ticket);
      const prevResult = deepAnalysisResults[ticket] || {};
      const ticketContext = {
        testcase_name: tab?.testName || "",
        root_cause: String(prevResult.root_cause || ""),
        classification: prevResult.classification || "",
        suggested_fix: String(prevResult.suggested_fix || ""),
        triage_report: String(prevResult.triage_report || ""),
        related_components: prevResult.related_components || [],
        jira_duplicates: prevResult.jira_duplicates || (ticket ? [ticket] : []),
        summary: "",
      };

      let resp;
      if (sessionId) {
        resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/follow-up`, {
          session_id: sessionId,
          question,
          mode: "agent",
          ticket_context: ticketContext,
          recovery_context: {
            testcase_name: tab?.testName || "",
            latest_analysis: {
              ...ticketContext,
              failing_code: prevResult.failing_code || null,
              confidence: prevResult.confidence || "",
            },
          },
        });
      } else {
        // No live session — still support create-ticket via dedicated endpoint /
        // follow-up intercept by synthesizing a short-lived session path.
        const createIntent = /\b(create|file|open|raise|make|creaet)\b.*\b(ticket|eng|jira)\b/i.test(question)
          || /\b(create|file)\s+eng\b/i.test(question);
        if (createIntent) {
          resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/create-eng-ticket`, {
            ticket_context: ticketContext,
          });
          if (resp.data?.success) {
            resp = {
              data: {
                success: true,
                analysis: resp.data.analysis || {
                  follow_up_answer: `Created ${resp.data.key}: ${resp.data.url}`,
                  created_ticket: resp.data.key,
                  created_ticket_url: resp.data.url,
                },
              },
            };
          }
        } else {
          resp = await api.post(
            `${API_BASE_URL}/mcp/regression/cursor-ai/analyze-testcase`,
            {
              testcase_name: tab?.testName || "",
              exception_summary: `Follow-up question on ${ticket}: ${question}\n\nPrevious analysis: ${prevResult.root_cause || "N/A"}`,
              exception: "",
              test_log_url: "",
              jira_tickets: [ticket],
              failure_stage: "follow_up",
            },
            { timeout: 600000 }
          );
          if (resp.data?.success) {
            if (resp.data.session_id) {
              setDeepAnalysisSessions(prev => ({ ...prev, [ticket]: resp.data.session_id }));
            }
            resp = { data: { success: true, analysis: resp.data.analysis } };
          }
        }
      }
      if (resp.data?.success) {
        const analysis = resp.data.analysis;
        setDeepAnalysisHistory(prev => ({
          ...prev,
          [ticket]: [...(prev[ticket] || []), { role: "assistant", data: analysis }]
        }));
        setDeepAnalysisResults(prev => ({
          ...prev,
          [ticket]: { ...(prev[ticket] || {}), ...analysis }
        }));
        if (resp.data.session_id) {
          setDeepAnalysisSessions(prev => ({ ...prev, [ticket]: resp.data.session_id }));
        }
      } else {
        setDeepAnalysisHistory(prev => ({
          ...prev,
          [ticket]: [...(prev[ticket] || []), { role: "error", text: resp.data?.error || "Follow-up failed" }]
        }));
      }
    } catch (err) {
      const errMsg = err.response?.data?.error || err.message || "Follow-up failed";
      setDeepAnalysisHistory(prev => ({
        ...prev,
        [ticket]: [...(prev[ticket] || []), { role: "error", text: errMsg }]
      }));
    } finally {
      setDeepAnalysisFollowUpLoading(prev => ({ ...prev, [ticket]: false }));
    }
  };

  const closeDeepAnalysisTab = (ticket) => {
    setDeepAnalysisTabs(prev => prev.filter(t => t.ticket !== ticket));
    if (activeTab === ticket) {
      setActiveTab("home");
    }
  };

  // Fetch QI Summary Report - supports both tag and task_ids
  const fetchQiSummaryReport = async (tagToUse = null, taskIdsToUse = null) => {
    setLoadingQiSummary(true);
    try {
      const params = resolveTagOrTaskIdsParams(tagToUse, taskIdsToUse, tag);
      if (!params.tag && !params.task_ids) {
        setLoadingQiSummary(false);
        return;
      }
      
      const response = await api.get(`${API_BASE_URL}/mcp/regression/qi-summary`, {
        params,
        timeout: 180000 // 3 minutes timeout
      });
      setQiSummaryReport(response.data);
    } catch (err) {
      console.error("Error fetching QI Summary Report:", err);
      setQiSummaryReport({ error: "Failed to fetch QI Summary Report. Please check backend endpoint." });
    } finally {
      setLoadingQiSummary(false);
    }
  };

  const resolveTeamName = (currentTag) => {
    if (!teamConfig) return "CDP";
    const cfg = teamConfig[currentTag] || teamConfig["default"];
    return cfg ? cfg.team : "CDP";
  };

  const fetchBranchQi = async (branch, timeFilter) => {
    const qiKey = `${branch}_${timeFilter}`;
    setBranchQiLoading((prev) => ({ ...prev, [qiKey]: true }));
    try {
      const teamName = resolveTeamName(tag);
      const dateOnly = timeFilter === "all" ? "all" : timeFilter.split(" ")[0];
      const response = await api.get(TCMS_OVERALL_QI_API, {
        params: { team_name: teamName, branch_name: branch, time_filter: dateOnly },
        timeout: 60000,
      });
      const qiValue = response.data?.qi_value;
      const dataKey = timeFilter === "all" ? "overall" : "current";
      const detailKey = timeFilter === "all" ? "overallDetail" : "currentDetail";
      setBranchQiData((prev) => ({
        ...prev,
        [branch]: {
          ...prev[branch],
          [dataKey]: qiValue,
          [detailKey]: response.data,
        },
      }));
    } catch (err) {
      console.error(`Error fetching QI for branch ${branch}:`, err);
      const dataKey = timeFilter === "all" ? "overall" : "current";
      setBranchQiData((prev) => ({
        ...prev,
        [branch]: {
          ...prev[branch],
          [dataKey]: "error",
        },
      }));
    } finally {
      setBranchQiLoading((prev) => ({ ...prev, [qiKey]: false }));
    }
  };

  // Note: Advanced options data is NOT loaded automatically on page load
  // Data is only fetched when user explicitly saves the advanced options

  if (loading) {
    return (
      <div className="container">
        <div style={{ padding: "20px", textAlign: "center" }}>
          <div>Loading Regression Dashboard...</div>
        </div>
      </div>
    );
  }
  
    return (
      <div className="container">
      {/* Tab Bar */}
      {deepAnalysisTabs.length > 0 && (
        <div style={{
          display: "flex", alignItems: "center", gap: "0", borderBottom: "2px solid #dee2e6",
          marginBottom: "15px", flexWrap: "wrap",
        }}>
          <button
            onClick={() => setActiveTab("home")}
            style={{
              padding: "8px 16px", border: "1px solid #dee2e6", borderBottom: activeTab === "home" ? "2px solid white" : "none",
              background: activeTab === "home" ? "#fff" : "#f8f9fa", cursor: "pointer",
              fontWeight: activeTab === "home" ? "700" : "400", borderRadius: "6px 6px 0 0",
              marginBottom: "-2px", fontSize: "13px", color: activeTab === "home" ? "#0066cc" : "#666",
            }}
          >
            Home
          </button>
          {deepAnalysisTabs.map(tab => (
            <div key={tab.ticket} style={{ display: "flex", alignItems: "center", marginLeft: "2px" }}>
              <button
                onClick={() => setActiveTab(tab.ticket)}
                style={{
                  padding: "8px 12px", border: "1px solid #dee2e6",
                  borderBottom: activeTab === tab.ticket ? "2px solid white" : "none",
                  background: activeTab === tab.ticket ? "#fff" : "#f8f9fa", cursor: "pointer",
                  fontWeight: activeTab === tab.ticket ? "700" : "400", borderRadius: "6px 6px 0 0",
                  marginBottom: "-2px", fontSize: "13px", color: activeTab === tab.ticket ? "#6f42c1" : "#666",
                }}
              >
                {tab.ticket}
              </button>
              <button
                onClick={() => closeDeepAnalysisTab(tab.ticket)}
                style={{
                  padding: "4px 6px", background: "none", border: "none", cursor: "pointer",
                  color: "#999", fontSize: "14px", lineHeight: 1, marginBottom: "-2px",
                }}
                title="Close tab"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Deep Analysis Tab Content */}
      {activeTab !== "home" && (() => {
        const tab = deepAnalysisTabs.find(t => t.ticket === activeTab);
        if (!tab) return null;
        const result = deepAnalysisResults[tab.ticket];
        const isLoading = deepAnalysisLoading[tab.ticket];
        const sessionId = deepAnalysisSessions[tab.ticket];
        const history = deepAnalysisHistory[tab.ticket] || [];
        const followUpText = deepAnalysisFollowUp[tab.ticket] || "";
        const followUpLoading = deepAnalysisFollowUpLoading[tab.ticket];

        return (
          <div style={{ padding: "10px 0" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
              <div>
                <h3 style={{ margin: 0, color: "#6f42c1" }}>
                  Deep Analysis: <a href={`${JIRA_URL}${tab.ticket}`} target="_blank" rel="noopener noreferrer" style={{ color: "#0066cc" }}>{tab.ticket}</a>
                </h3>
                <div style={{ fontSize: "12px", color: "#666", marginTop: "4px" }}>
                  Feature: <strong>{tab.featureArea}</strong> | Test: <code style={{ fontSize: "11px" }}>{tab.testName}</code>
                </div>
              </div>
              <button
                onClick={() => openDeepAnalysisTab(tab.ticket, tab.testName, tab.tests)}
                disabled={isLoading}
                style={{
                  padding: "6px 12px", background: isLoading ? "#6c757d" : "#6f42c1", color: "white",
                  border: "none", borderRadius: "4px", cursor: isLoading ? "not-allowed" : "pointer", fontSize: "12px",
                }}
              >
                {isLoading ? "Analyzing..." : "Re-run Analysis"}
              </button>
            </div>

            {isLoading && !result && (
              <div style={{ padding: "40px", textAlign: "center", color: "#6f42c1" }}>
                <div style={{ fontSize: "16px", marginBottom: "10px" }}>Cursor AI is analyzing...</div>
                <div style={{ fontSize: "12px", color: "#666" }}>This may take a few minutes. The AI is examining logs, source code, and internal docs.</div>
              </div>
            )}

            {/* Interactive Chat Window */}
            {result && !isLoading && (
              <div style={{
                marginTop: "20px", border: "1px solid #dee2e6", borderRadius: "10px",
                background: "#fff", display: "flex", flexDirection: "column",
                height: "400px", overflow: "hidden", boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
              }}>
                {/* Chat Header */}
                <div style={{
                  padding: "12px 16px", borderBottom: "1px solid #e9ecef",
                  background: "linear-gradient(135deg, #6f42c1, #5a32a3)",
                  borderRadius: "10px 10px 0 0", display: "flex", alignItems: "center", gap: "10px",
                }}>
                  <div style={{ width: "8px", height: "8px", borderRadius: "50%", background: "#4caf50" }} />
                  <span style={{ color: "#fff", fontSize: "13px", fontWeight: "600" }}>
                    Cursor AI Chat — {tab.ticket}
                  </span>
                  <span style={{ color: "rgba(255,255,255,0.7)", fontSize: "11px", marginLeft: "auto" }}>
                    {sessionId ? "Session active" : "Interactive"}
                  </span>
                </div>

                {/* Chat Messages Area */}
                <div style={{
                  flex: 1, overflowY: "auto", padding: "16px",
                  display: "flex", flexDirection: "column", gap: "12px",
                  background: "#fafbfc",
                }}>
                  {/* Initial AI response as first message */}
                  {!result.error && (
                    <div style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
                      <div style={{
                        width: "28px", height: "28px", borderRadius: "50%", background: "#6f42c1",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "#fff", fontSize: "12px", fontWeight: "700", flexShrink: 0,
                      }}>AI</div>
                      <div style={{
                        background: "#fff", border: "1px solid #e9ecef", borderRadius: "4px 12px 12px 12px",
                        padding: "10px 14px", maxWidth: "85%", fontSize: "13px", lineHeight: "1.5",
                      }}>
                        <div style={{ marginBottom: "6px" }}>
                          <span style={{
                            padding: "2px 8px", borderRadius: "10px", fontSize: "10px", fontWeight: "600",
                            background: (result.classification || "").includes("Test") ? "#fff3cd"
                              : (result.classification || "").includes("Product") ? "#f8d7da"
                              : (result.classification || "").includes("Infra") ? "#d1ecf1" : "#e2e3e5",
                            color: (result.classification || "").includes("Test") ? "#856404"
                              : (result.classification || "").includes("Product") ? "#721c24"
                              : (result.classification || "").includes("Infra") ? "#0c5460" : "#383d41",
                          }}>
                            {result.classification || "Analysis Complete"}
                          </span>
                          {result.confidence && (
                            <span style={{ marginLeft: "8px", fontSize: "10px", color: "#888" }}>Confidence: {result.confidence}</span>
                          )}
                        </div>
                        <div style={{ marginBottom: "4px" }}><strong>Root Cause:</strong> {result.root_cause || "N/A"}</div>
                        {result.suggested_fix && <div style={{ marginBottom: "4px" }}><strong>Suggested Fix:</strong> {result.suggested_fix}</div>}
                        {result.failing_code && (
                          <div style={{ marginTop: "6px" }}>
                            <div style={{ fontSize: "11px", color: "#666" }}>
                              {result.failing_code.file}{result.failing_code.line_range && ` (lines ${result.failing_code.line_range})`}
                            </div>
                            {result.failing_code.snippet && (
                              <pre style={{ background: "#282c34", color: "#abb2bf", padding: "8px", borderRadius: "4px", fontSize: "10px", overflow: "auto", marginTop: "4px", marginBottom: 0 }}>
                                {result.failing_code.snippet}
                              </pre>
                            )}
                          </div>
                        )}
                        {result.related_components && result.related_components.length > 0 && (
                          <div style={{ marginTop: "6px", display: "flex", gap: "4px", flexWrap: "wrap" }}>
                            {result.related_components.map((c, i) => (
                              <span key={i} style={{ background: "#e9ecef", padding: "1px 6px", borderRadius: "8px", fontSize: "10px" }}>{c}</span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {result.error && (
                    <div style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
                      <div style={{
                        width: "28px", height: "28px", borderRadius: "50%", background: "#dc3545",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "#fff", fontSize: "10px", fontWeight: "700", flexShrink: 0,
                      }}>!</div>
                      <div style={{
                        background: "#fce4ec", border: "1px solid #f5c6cb", borderRadius: "4px 12px 12px 12px",
                        padding: "10px 14px", maxWidth: "85%", fontSize: "13px",
                      }}>
                        <strong>Error:</strong> {result.error}
                        <div style={{ marginTop: "8px", fontSize: "11px", color: "#666" }}>
                          Paste in Cursor chat: <code style={{ background: "#f8f9fa", padding: "2px 4px", borderRadius: "3px" }}>/triage-cdp-test-failure {tab.ticket}</code>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Follow-up conversation messages */}
                  {history.map((msg, i) => (
                    msg.role === "user" ? (
                      <div key={i} style={{ display: "flex", gap: "8px", alignItems: "flex-start", justifyContent: "flex-end" }}>
                        <div style={{
                          background: "#e3f2fd", border: "1px solid #bbdefb", borderRadius: "12px 4px 12px 12px",
                          padding: "10px 14px", maxWidth: "75%", fontSize: "13px",
                        }}>
                          {msg.text}
                        </div>
                        <div style={{
                          width: "28px", height: "28px", borderRadius: "50%", background: "#1976d2",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "#fff", fontSize: "11px", fontWeight: "700", flexShrink: 0,
                        }}>U</div>
                      </div>
                    ) : msg.role === "assistant" ? (
                      <div key={i} style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
                        <div style={{
                          width: "28px", height: "28px", borderRadius: "50%", background: "#6f42c1",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "#fff", fontSize: "12px", fontWeight: "700", flexShrink: 0,
                        }}>AI</div>
                        <div style={{
                          background: "#fff", border: "1px solid #e9ecef", borderRadius: "4px 12px 12px 12px",
                          padding: "10px 14px", maxWidth: "85%", fontSize: "13px", lineHeight: "1.5",
                        }}>
                          {msg.data?.follow_up_answer || msg.data?.root_cause || (
                            typeof msg.data === "object" ? (
                              <pre style={{ margin: 0, fontSize: "11px", whiteSpace: "pre-wrap" }}>{JSON.stringify(msg.data, null, 2)}</pre>
                            ) : String(msg.data)
                          )}
                        </div>
                      </div>
                    ) : (
                      <div key={i} style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
                        <div style={{
                          width: "28px", height: "28px", borderRadius: "50%", background: "#dc3545",
                          display: "flex", alignItems: "center", justifyContent: "center",
                          color: "#fff", fontSize: "10px", fontWeight: "700", flexShrink: 0,
                        }}>!</div>
                        <div style={{
                          background: "#fce4ec", border: "1px solid #f5c6cb", borderRadius: "4px 12px 12px 12px",
                          padding: "10px 14px", maxWidth: "85%", fontSize: "13px", color: "#c62828",
                        }}>
                          {msg.text}
                        </div>
                      </div>
                    )
                  ))}

                  {/* Typing indicator */}
                  {followUpLoading && (
                    <div style={{ display: "flex", gap: "8px", alignItems: "flex-start" }}>
                      <div style={{
                        width: "28px", height: "28px", borderRadius: "50%", background: "#6f42c1",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        color: "#fff", fontSize: "12px", fontWeight: "700", flexShrink: 0,
                      }}>AI</div>
                      <div style={{
                        background: "#fff", border: "1px solid #e9ecef", borderRadius: "4px 12px 12px 12px",
                        padding: "10px 14px", fontSize: "13px", color: "#999",
                      }}>
                        <span style={{ animation: "pulse 1.5s infinite" }}>Thinking...</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* Chat Input Bar */}
                <div style={{
                  padding: "12px 16px", borderTop: "1px solid #e9ecef", background: "#fff",
                  borderRadius: "0 0 10px 10px", display: "flex", gap: "8px", alignItems: "center",
                }}>
                  <input
                    type="text"
                    placeholder="Ask anything — create eng ticket, ENG status/CR, Glean, create CR..."
                    value={followUpText}
                    onChange={e => setDeepAnalysisFollowUp(prev => ({ ...prev, [tab.ticket]: e.target.value }))}
                    onKeyDown={e => { if (e.key === "Enter" && !followUpLoading && followUpText.trim()) handleDeepAnalysisFollowUp(tab.ticket); }}
                    disabled={followUpLoading}
                    style={{
                      flex: 1, padding: "10px 14px", border: "1px solid #dee2e6", borderRadius: "20px",
                      fontSize: "13px", outline: "none", background: "#f8f9fa",
                      transition: "border-color 0.2s",
                    }}
                    onFocus={e => { e.target.style.borderColor = "#6f42c1"; e.target.style.background = "#fff"; }}
                    onBlur={e => { e.target.style.borderColor = "#dee2e6"; e.target.style.background = "#f8f9fa"; }}
                  />
                  <button
                    onClick={() => handleDeepAnalysisFollowUp(tab.ticket)}
                    disabled={followUpLoading || !followUpText.trim()}
                    style={{
                      width: "36px", height: "36px", borderRadius: "50%",
                      background: followUpLoading || !followUpText.trim() ? "#dee2e6" : "#6f42c1",
                      color: "white", border: "none", cursor: followUpLoading || !followUpText.trim() ? "not-allowed" : "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px",
                      transition: "background 0.2s",
                    }}
                    title="Send"
                  >
                    &#10148;
                  </button>
                </div>
              </div>
            )}
          </div>
        );
      })()}

      {/* Home Tab Content */}
      {activeTab === "home" && <>
      {advancedOptions.triageGenieCoverage && (
        <>
          <button
            type="button"
            className="tg-coverage-genie-btn"
            onClick={() => setTgCoverageOpen(true)}
            title="Triage Genie coverage"
            aria-label="Triage Genie coverage"
          >
            <svg
              className="tg-coverage-genie-icon"
              viewBox="0 0 120 120"
              aria-hidden="true"
              focusable="false"
            >
              <defs>
                <linearGradient id="tgGenieBlue" x1="20" y1="10" x2="100" y2="110" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#7dd3fc" />
                  <stop offset="45%" stopColor="#38bdf8" />
                  <stop offset="100%" stopColor="#0284c7" />
                </linearGradient>
                <linearGradient id="tgGenieSmoke" x1="40" y1="70" x2="80" y2="118" gradientUnits="userSpaceOnUse">
                  <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.95" />
                  <stop offset="100%" stopColor="#0ea5e9" stopOpacity="0.15" />
                </linearGradient>
              </defs>
              <path
                fill="url(#tgGenieSmoke)"
                d="M48 72c-6 8-4 16 2 22 6 6 4 14-4 18 14-2 28-8 34-18 6-10 2-20-6-26-4 8-14 10-26 4z"
              />
              <ellipse cx="60" cy="58" rx="28" ry="22" fill="url(#tgGenieBlue)" />
              <path
                fill="url(#tgGenieBlue)"
                d="M34 52c-10 2-16 12-14 20 2 6 8 8 14 6 2-8 4-16 0-26zm52 0c10 2 16 12 14 20-2 6-8 8-14 6-2-8-4-16 0-26z"
              />
              <circle cx="60" cy="34" r="18" fill="url(#tgGenieBlue)" />
              <ellipse cx="60" cy="14" rx="7" ry="9" fill="#0ea5e9" />
              <circle cx="60" cy="6" r="4" fill="#38bdf8" />
              <ellipse cx="53" cy="32" rx="3.2" ry="3.8" fill="#0f172a" />
              <ellipse cx="67" cy="32" rx="3.2" ry="3.8" fill="#0f172a" />
              <circle cx="54" cy="31" r="1" fill="#fff" />
              <circle cx="68" cy="31" r="1" fill="#fff" />
              <path d="M48 26q5-4 10 0" stroke="#0f172a" strokeWidth="1.6" fill="none" strokeLinecap="round" />
              <path d="M62 26q5-4 10 0" stroke="#0f172a" strokeWidth="1.6" fill="none" strokeLinecap="round" />
              <path
                d="M48 40c4 8 20 8 24 0"
                stroke="#0f172a"
                strokeWidth="2.2"
                fill="none"
                strokeLinecap="round"
              />
              <path d="M52 40c3 5 13 5 16 0" fill="#be185d" opacity="0.85" />
              <rect x="24" y="66" width="10" height="5" rx="2" fill="#fbbf24" />
              <rect x="86" y="66" width="10" height="5" rx="2" fill="#fbbf24" />
              <path d="M40 72h40" stroke="#fbbf24" strokeWidth="3" strokeLinecap="round" />
            </svg>
          </button>
          <TriageGenieCoverageModal
            open={tgCoverageOpen}
            onClose={() => setTgCoverageOpen(false)}
          />
        </>
      )}
      <div style={{ 
        display: "flex", 
        justifyContent: "space-between", 
        alignItems: "center", 
        marginBottom: "20px", 
        flexWrap: "wrap", 
        gap: "10px" 
      }}>
        <h2 style={{ margin: 0 }}>Regression Dashboard</h2>
        <div style={{ 
          display: "flex", 
          gap: "10px", 
          flexWrap: "nowrap",
          alignItems: "center"
        }}>
          {inputMode === "tag" && (
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <label style={{ fontSize: "13px", fontWeight: "500", whiteSpace: "nowrap" }}>Tag:</label>
              <select
                value={tag || defaultTag || ""}
                onChange={async (e) => {
                  const selected = e.target.value || null;
                  if (selected === (tag || defaultTag)) return;
                  // Drop prior job's Full regression IDs before loading new tag
                  clearFullRegressionLink();
                  setGlobalJitaTaskIds([]);
                  setTag(selected);
                  setDefaultTag(selected);
                  localStorage.setItem("regressionDashboardTag", selected || "");
                  if (selected) {
                    try {
                      await api.post(CONFIG_API, {
                        input_mode: "tag",
                        default_tag: selected,
                        added_tags: addedTags,
                        tag: selected,
                        task_ids: []
                      });
                    } catch (err) {
                      console.error("Failed to save tag config:", err);
                    }
                    setBranchQiData({});
                    await fetchData({ tag: selected });
                    await fetchTriageCount(selected);
                    if (advancedOptions.qiSummaryReport) await fetchQiSummaryReport(selected);
                    if (advancedOptions.triageAccuracy) await fetchTriageAccuracy(selected);
                  } else {
                    setRows([]);
                    setTriageCount(null);
                    setTriageAccuracyData(null);
                    setQiSummaryReport(null);
                    setBranchQiData({});
                    try {
                      await api.post(CONFIG_API, {
                        input_mode: "tag",
                        default_tag: null,
                        added_tags: addedTags,
                        tag: "",
                        task_ids: []
                      });
                    } catch (err) {
                      console.error("Failed to save tag config:", err);
                    }
                  }
                }}
                style={{
                  padding: "6px 10px",
                  fontSize: "13px",
                  border: "1px solid #ddd",
                  borderRadius: "4px",
                  minWidth: "180px",
                  background: "white",
                  cursor: "pointer"
                }}
                title="Quick-select tag to load regression overview"
              >
                <option value="">None</option>
                {addedTags.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
          )}
          <button
            onClick={() => {
              // Restore input mode and values from localStorage
              const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
              setModalInputMode(savedMode); // Use modal-specific state
              if (savedMode === "tag") {
                setConfigTagInput(tag || "");
                setConfigTaskIdsInput("");
              } else {
                const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
                setConfigTaskIdsInput(savedTaskIds ? JSON.parse(savedTaskIds).join(", ") : "");
                setConfigTagInput("");
              }
              setShowAddRemoveTaskIds(false);
              setShowConfigModal(true);
            }}
            style={{
              padding: "8px 16px",
              background: "#6c757d",
              color: "white",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "14px",
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              whiteSpace: "nowrap",
              minWidth: "fit-content"
            }}
            title="Configuration Settings"
          >
            ⚙️ Configuration
          </button>
        </div>
      </div>

      {/* Configuration Modal */}
      {showConfigModal && (
        <div 
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.5)",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            zIndex: 1000
          }}
          onClick={() => setShowConfigModal(false)}
        >
          <div 
            style={{
              background: "white",
              padding: "24px",
              borderRadius: "8px",
              boxShadow: "0 4px 6px rgba(0, 0, 0, 0.1)",
              minWidth: "500px",
              maxWidth: "90%",
              maxHeight: "90vh",
              overflowY: "auto"
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 style={{ marginTop: 0, marginBottom: "20px", color: "#333" }}>Configuration</h3>
            
            {/* Input Mode Selection */}
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "10px", fontWeight: "bold" }}>
                Fetch Regression Overview By:
              </label>
              <div style={{ display: "flex", gap: "20px", marginBottom: "15px" }}>
                <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="inputMode"
                    value="tag"
                    checked={modalInputMode === "tag"}
                    onChange={(e) => setModalInputMode(e.target.value)}
                    style={{ marginRight: "8px" }}
                  />
                  Default Tag Name
                </label>
                <label style={{ display: "flex", alignItems: "center", cursor: "pointer" }}>
                  <input
                    type="radio"
                    name="inputMode"
                    value="task_ids"
                    checked={modalInputMode === "task_ids"}
                    onChange={(e) => setModalInputMode(e.target.value)}
                    style={{ marginRight: "8px" }}
                  />
                  JITA Task IDs / Link
                </label>
        </div>
            </div>
            
            {/* Tag Mode: Default Tag Name + Added Tag List */}
            {modalInputMode === "tag" && (
            <>
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontWeight: "bold" }}>
                1. Default Tag Name:
              </label>
              <select
                value={defaultTag || ""}
                onChange={(e) => {
                  const v = e.target.value;
                  setDefaultTag(v || null);
                  setConfigTagInput(v || "");
                }}
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "14px",
                  border: "1px solid #ddd",
                  borderRadius: "4px",
                  boxSizing: "border-box"
                }}
              >
                <option value="">None</option>
                {addedTags.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontWeight: "bold" }}>
                2. Add Tag:
              </label>
              <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
                <input
                  type="text"
                  value={newTagInput}
                  onChange={(e) => setNewTagInput(e.target.value)}
                  placeholder="Enter tag name to add"
                  style={{
                    flex: 1,
                    padding: "8px",
                    fontSize: "14px",
                    border: "1px solid #ddd",
                    borderRadius: "4px"
                  }}
                  onKeyDown={(e) => e.key === "Enter" && handleAddTag()}
                />
                <button
                  onClick={handleAddTag}
                  disabled={loadingBranches || !newTagInput.trim()}
                  style={{
                    padding: "8px 16px",
                    background: loadingBranches || !newTagInput.trim() ? "#ccc" : "#28a745",
                    color: "white",
                    border: "none",
                    borderRadius: "4px",
                    cursor: loadingBranches || !newTagInput.trim() ? "not-allowed" : "pointer",
                    whiteSpace: "nowrap"
                  }}
                >
                  {loadingBranches ? "Adding..." : "Add Tag"}
                </button>
              </div>
              {addedTags.length > 0 ? (
                <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
                  {addedTags.map((t) => (
                    <li key={t} style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "6px", padding: "6px", background: "#f8f9fa", borderRadius: "4px" }}>
                      <span style={{ flex: 1 }}>{t}</span>
                      <button
                        type="button"
                        onClick={() => handleDeleteTag(t)}
                        title="Delete tag"
                        style={{
                          padding: "4px 10px",
                          background: "#dc3545",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor: "pointer",
                          fontSize: "12px"
                        }}
                      >
                        Delete
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div style={{ color: "#666", fontSize: "13px" }}>No tags added yet. Add a tag above.</div>
              )}
            </div>
            </>
            )}
            
            {/* JITA Task IDs / Link */}
            {modalInputMode === "task_ids" && (
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontWeight: "bold" }}>
                1. JITA Task IDs or Link:
              </label>
              <textarea
                value={configTaskIdsInput}
                onChange={(e) => setConfigTaskIdsInput(e.target.value)}
                placeholder="Enter comma-separated task IDs (e.g., 69786c3e2bc0c4e5a95ff046,69786c032bc0c4e5b6bee89f) or JITA link (e.g., https://jita.eng.nutanix.com/results?task_ids=69786c3e2bc0c4e5a95ff046,69786c032bc0c4e5b6bee89f)"
                style={{
                  width: "100%",
                  padding: "8px",
                  fontSize: "14px",
                  border: "1px solid #ddd",
                  borderRadius: "4px",
                  boxSizing: "border-box",
                  minHeight: "80px",
                  resize: "vertical",
                  fontFamily: "monospace"
                }}
              />
              <small style={{ display: "block", marginTop: "5px", color: "#666", fontSize: "12px" }}>
                You can enter either comma-separated task IDs or paste a JITA results link. The link will be automatically parsed to extract task IDs. Click × on a chip below to drop one ID, then Save.
              </small>
              {parseTaskIds(configTaskIdsInput).length > 0 && (
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: "6px",
                    marginTop: "10px",
                  }}
                >
                  {parseTaskIds(configTaskIdsInput).map((tid) => (
                    <span
                      key={tid}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "4px",
                        padding: "4px 8px",
                        background: "#eef2f7",
                        borderRadius: "4px",
                        fontFamily: "monospace",
                        fontSize: "11px",
                      }}
                    >
                      {tid}
                      <button
                        type="button"
                        onClick={() => handleRemoveConfigTaskIdChip(tid)}
                        title="Remove this task ID"
                        style={{
                          border: "none",
                          background: "transparent",
                          color: "#dc3545",
                          cursor: "pointer",
                          fontWeight: 700,
                          fontSize: "14px",
                          lineHeight: 1,
                          padding: "0 2px",
                        }}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
            )}

            {/* Advanced Options */}
            <div style={{ marginBottom: "20px", paddingTop: "20px", borderTop: "1px solid #ddd" }}>
              <label style={{ display: "block", marginBottom: "15px", fontWeight: "bold", fontSize: "16px" }}>
                {modalInputMode === "tag" ? "3" : "2"}. Advanced Options:
              </label>

              {modalInputMode === "tag" && (
              <div style={{ marginBottom: "15px" }}>
                <label style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  marginBottom: "12px",
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={showAddRemoveTaskIds}
                    onChange={(e) => setShowAddRemoveTaskIds(e.target.checked)}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>Add / Remove task ID and tag</span>
                </label>
                {showAddRemoveTaskIds && (
                  <div
                    style={{
                      marginLeft: "8px",
                      padding: "12px",
                      border: "1px solid #e0e0e0",
                      borderRadius: "6px",
                      background: "#fafafa",
                    }}
                  >
                    <textarea
                      value={taskIdsActionInput}
                      onChange={(e) => setTaskIdsActionInput(e.target.value)}
                      placeholder="Paste task ID(s) or JITA results URL"
                      style={{
                        width: "100%",
                        padding: "8px",
                        fontSize: "14px",
                        border: "1px solid #ddd",
                        borderRadius: "4px",
                        boxSizing: "border-box",
                        minHeight: "64px",
                        resize: "vertical",
                        fontFamily: "monospace",
                        marginBottom: "8px",
                      }}
                    />
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        onClick={() => handleAppendTaskIdsToTag()}
                        disabled={
                          appendingTaskIds ||
                          removingTaskIds ||
                          !taskIdsActionInput.trim() ||
                          !activeConfigTag
                        }
                        style={{
                          padding: "8px 16px",
                          background:
                            appendingTaskIds ||
                            removingTaskIds ||
                            !taskIdsActionInput.trim() ||
                            !activeConfigTag
                              ? "#ccc"
                              : "#0d6efd",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor:
                            appendingTaskIds ||
                            removingTaskIds ||
                            !taskIdsActionInput.trim() ||
                            !activeConfigTag
                              ? "not-allowed"
                              : "pointer",
                          whiteSpace: "nowrap",
                          fontWeight: 600,
                        }}
                        title="Add tester_tag on JITA and include task ID(s) in regression JITA link"
                      >
                        {appendingTaskIds ? "Adding..." : "+ Add"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRemoveTaskIdsFromTag()}
                        disabled={
                          removingTaskIds ||
                          appendingTaskIds ||
                          !taskIdsActionInput.trim() ||
                          !activeConfigTag
                        }
                        style={{
                          padding: "8px 16px",
                          background:
                            removingTaskIds ||
                            appendingTaskIds ||
                            !taskIdsActionInput.trim() ||
                            !activeConfigTag
                              ? "#ccc"
                              : "#dc3545",
                          color: "white",
                          border: "none",
                          borderRadius: "4px",
                          cursor:
                            removingTaskIds ||
                            appendingTaskIds ||
                            !taskIdsActionInput.trim() ||
                            !activeConfigTag
                              ? "not-allowed"
                              : "pointer",
                          whiteSpace: "nowrap",
                          fontWeight: 600,
                        }}
                        title="Remove tester_tag on JITA and drop task ID(s) from regression JITA link"
                      >
                        {removingTaskIds ? "Removing..." : "− Remove"}
                      </button>
                    </div>
                    {taskIdsActionStatus && (
                      <div
                        style={{
                          marginTop: "8px",
                          padding: "8px 10px",
                          borderRadius: "4px",
                          fontSize: "12px",
                          background:
                            taskIdsActionStatus.type === "ok"
                              ? "#e8f5e9"
                              : taskIdsActionStatus.type === "err"
                                ? "#fdecea"
                                : taskIdsActionStatus.type === "warn"
                                  ? "#fff8e1"
                                  : "#eef2f7",
                          color:
                            taskIdsActionStatus.type === "ok"
                              ? "#1b5e20"
                              : taskIdsActionStatus.type === "err"
                                ? "#b71c1c"
                                : taskIdsActionStatus.type === "warn"
                                  ? "#8d6e00"
                                  : "#334155",
                        }}
                      >
                        {taskIdsActionStatus.text}
                      </div>
                    )}
                    {!activeConfigTag && (
                      <small style={{ display: "block", marginTop: "6px", color: "#b45309", fontSize: "12px" }}>
                        Select a Default Tag Name first.
                      </small>
                    )}
                  </div>
                )}
              </div>
              )}
              
              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.triageCount || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        triageCount: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>Triage Count by Owner</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.triageAccuracy || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        triageAccuracy: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>Triage Accuracy Analyzer</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.triageGenieCoverage || false}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setAdvancedOptions(prev => ({
                        ...prev,
                        triageGenieCoverage: checked
                      }));
                      if (!checked) setTgCoverageOpen(false);
                    }}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>Triage Genie Coverage</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.qiSummaryReport || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        qiSummaryReport: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>QI Summary Report</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "not-allowed",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s",
                  opacity: 0.6
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.flakyTestInsights || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        flakyTestInsights: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "not-allowed" }}
                    disabled
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>(Future) Flaky Test Insights</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "not-allowed",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s",
                  opacity: 0.6
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.aiRootCauseSummary || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        aiRootCauseSummary: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "not-allowed" }}
                    disabled
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>(Future) AI Root Cause Summary</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "not-allowed",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s",
                  opacity: 0.6
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.regressionRiskScore || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        regressionRiskScore: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "not-allowed" }}
                    disabled
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>(Future) Regression Risk Score</span>
                </label>
              </div>

              <div style={{ marginBottom: "15px" }}>
                <label style={{ 
                  display: "flex", 
                  alignItems: "center", 
                  gap: "10px", 
                  marginBottom: "12px", 
                  cursor: "pointer",
                  padding: "8px",
                  borderRadius: "4px",
                  transition: "background 0.2s"
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = "#f8f9fa"}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                >
                  <input
                    type="checkbox"
                    checked={advancedOptions.bulkIssuesQiImpact || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        bulkIssuesQiImpact: e.target.checked
                      }));
                    }}
                    style={{ width: "18px", height: "18px", cursor: "pointer" }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>Bulk Issues QI Impacting Testcases</span>
                </label>
              </div>

              <div
                style={{
                  padding: "10px",
                  background: "#f8f9fa",
                  borderRadius: "4px",
                  border: "1px solid #dee2e6"
                }}
              >
                <label style={{ display: "flex", alignItems: "center", gap: "8px", cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={advancedOptions.tcmsOverview || false}
                    onChange={(e) => {
                      setAdvancedOptions(prev => ({
                        ...prev,
                        tcmsOverview: e.target.checked
                      }));
                    }}
                  />
                  <span style={{ fontSize: "14px", fontWeight: "500" }}>TCMS Overview & Comparison</span>
                </label>
              </div>
            </div>

            <div style={{ display: "flex", gap: "10px", justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowConfigModal(false)}
                style={{
                  padding: "8px 16px",
                  background: "#6c757d",
                  color: "white",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer"
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleSaveConfig}
                style={{
                  padding: "8px 16px",
                  background: "#007bff",
                  color: "white",
                  border: "none",
                  borderRadius: "4px",
                  cursor: "pointer"
                }}
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

        <h3 style={{ marginBottom: "10px" }}>Regression Summary</h3>
        <table className="dashboard-table">
          <thead>
            <tr>
            <th>{inputMode === "task_ids" ? "Task IDs" : "Tag"}</th>
              <th>Branch</th>
              <th>Start Date</th>
              <th>Status</th>
              <th>Jita Tasks</th>
              <th colSpan="2" style={{ textAlign: "center" }}>Tests Overview</th>
              <th style={{ textAlign: "center" }}>TCMS QI - Current</th>
              <th style={{ textAlign: "center" }}>TCMS QI - Overall</th>
            </tr>
          </thead>

          <tbody>
            {rows.map((row) => {
              return (
                <tr key={row.branch}>
                <td>
                  {inputMode === "task_ids" ? (
                    (() => {
                      const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
                      if (savedTaskIds) {
                        try {
                          const taskIds = JSON.parse(savedTaskIds);
                          return taskIds.length > 3 
                            ? `${taskIds.slice(0, 3).join(", ")}... (${taskIds.length} tasks)`
                            : taskIds.join(", ");
                        } catch (e) {
                          return "Task IDs";
                        }
                      }
                      return "Task IDs";
                    })()
                  ) : (
                    tag || "-"
                  )}
                </td>
                  <td>{row.branch}</td>
                  <td>{row.startDate || "-"}</td>
                  <td className={`status ${(row.status || "").toLowerCase()}`}>
                    {row.status}
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle" }}>
                    {renderTaskButton(
                      globalJitaTaskIds.length > 0 ? globalJitaTaskIds : row.actualTasks,
                      "Regression_Run_Tasks"
                    )}
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle", fontSize: "12px" }}>
                    <div style={{ fontWeight: "bold", marginBottom: "3px" }}>SUCCEEDED</div>
                    <div style={{ color: "#28a745", fontSize: "16px", fontWeight: "bold" }}>{row.succeeded || 0}</div>
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "8px", fontSize: "12px" }}>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>FAILED</div>
                        <div style={{ color: "#dc3545" }}>{row.failed || 0}</div>
                      </div>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>KILLED</div>
                        <div style={{ color: "#6c757d" }}>{row.killed || 0}</div>
                      </div>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>SKIPPED</div>
                        <div style={{ color: "#ffc107" }}>{row.skipped || 0}</div>
                      </div>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>PENDING</div>
                        <div style={{ color: "#17a2b8" }}>{row.pending || 0}</div>
                      </div>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>WARNING</div>
                        <div style={{ color: "#fd7e14" }}>{row.warning || 0}</div>
                      </div>
                      <div>
                        <div style={{ fontWeight: "bold", marginBottom: "3px" }}>RUNNING</div>
                        <div style={{ color: "#6f42c1" }}>{row.running || 0}</div>
                      </div>
                    </div>
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle", minWidth: "150px" }}>
                    {(() => {
                      const qiData = branchQiData[row.branch];
                      const customDateStr = row.startDate ? row.startDate.split(" ")[0] : null;
                      const currentLoading = customDateStr && branchQiLoading[`${row.branch}_${row.startDate}`];
                      const qiColor = (val) =>
                        val === "error" ? "#dc3545"
                        : val >= 80 ? "#28a745"
                        : val >= 50 ? "#fd7e14"
                        : "#dc3545";
                      const milestone = resolveTcmsMilestone(row.branch);
                      const teamName = (() => {
                        if (!teamConfig) return "CDP";
                        const cfg = teamConfig[tag] || teamConfig["default"];
                        return cfg ? cfg.team : "CDP";
                      })();
                      const tcmsSearch = JSON.stringify([
                        {"field": "Team", "op": "$eq", "value": [`${milestone}/${teamName}`]},
                        {"field": "Test Sets", "op": "$contains", "value": [`test_sets/milestones/${milestone}/${teamName}/`]}
                      ]);
                      const tcmsBaseUrl = `https://tcms.eng.nutanix.com/#/testcases/milestone/${milestone}?search=${encodeURIComponent(tcmsSearch)}&tab=package_type&pass=overall&type=Regression`;
                      const tcmsDateUrl = customDateStr ? `${tcmsBaseUrl}&timeFilter=${customDateStr}` : null;

                      if (!customDateStr) {
                        return <span style={{ color: "#999", fontSize: "11px" }}>No start date</span>;
                      }

                      return (
                        <div style={{ fontSize: "12px" }}>
                          {qiData?.current != null && qiData.current !== "error" ? (
                            <div>
                              <div style={{ fontWeight: "bold", color: qiColor(qiData.current), fontSize: "16px" }}>
                                {qiData.current}%
                              </div>
                              <div style={{ color: "#666", fontSize: "10px", marginBottom: "6px" }}>QI (from {customDateStr})</div>
                              <div style={{ display: "flex", gap: "4px", justifyContent: "center", flexWrap: "wrap" }}>
                                <button
                                  onClick={() => setTcmsDetailModal({ data: qiData.currentDetail, title: `TCMS QI - Current (${customDateStr})`, branch: row.branch })}
                                  style={{ padding: "2px 6px", fontSize: "10px", cursor: "pointer", background: "#17a2b8", color: "white", border: "none", borderRadius: "3px" }}
                                >
                                  Details
                                </button>
                                <a href={tcmsDateUrl} target="_blank" rel="noopener noreferrer"
                                  style={{ padding: "2px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                                >
                                  TCMS
                                </a>
                              </div>
                            </div>
                          ) : qiData?.current === "error" ? (
                            <div>
                              <div style={{ color: "#dc3545", fontSize: "11px", marginBottom: "4px" }}>Failed</div>
                              <a href={tcmsDateUrl} target="_blank" rel="noopener noreferrer"
                                style={{ padding: "2px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                              >
                                TCMS
                              </a>
                            </div>
                          ) : currentLoading ? (
                            <span style={{ color: "#666", fontStyle: "italic" }}>Loading...</span>
                          ) : (
                            <div style={{ display: "flex", gap: "4px", justifyContent: "center", flexWrap: "wrap" }}>
                              <button
                                onClick={() => fetchBranchQi(row.branch, row.startDate)}
                                style={{ padding: "3px 8px", fontSize: "11px", cursor: "pointer", background: "#17a2b8", color: "white", border: "none", borderRadius: "3px" }}
                              >
                                Load QI
                              </button>
                              <a href={tcmsDateUrl} target="_blank" rel="noopener noreferrer"
                                style={{ padding: "3px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                              >
                                TCMS
                              </a>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle", minWidth: "150px" }}>
                    {(() => {
                      const qiData = branchQiData[row.branch];
                      const overallLoading = branchQiLoading[`${row.branch}_all`];
                      const qiColor = (val) =>
                        val === "error" ? "#dc3545"
                        : val >= 80 ? "#28a745"
                        : val >= 50 ? "#fd7e14"
                        : "#dc3545";
                      const milestone = resolveTcmsMilestone(row.branch);
                      const teamName = (() => {
                        if (!teamConfig) return "CDP";
                        const cfg = teamConfig[tag] || teamConfig["default"];
                        return cfg ? cfg.team : "CDP";
                      })();
                      const tcmsSearch = JSON.stringify([
                        {"field": "Team", "op": "$eq", "value": [`${milestone}/${teamName}`]},
                        {"field": "Test Sets", "op": "$contains", "value": [`test_sets/milestones/${milestone}/${teamName}/`]}
                      ]);
                      const tcmsBaseUrl = `https://tcms.eng.nutanix.com/#/testcases/milestone/${milestone}?search=${encodeURIComponent(tcmsSearch)}&tab=package_type&pass=overall&type=Regression`;

                      return (
                        <div style={{ fontSize: "12px" }}>
                          {qiData?.overall != null && qiData.overall !== "error" ? (
                            <div>
                              <div style={{ fontWeight: "bold", color: qiColor(qiData.overall), fontSize: "16px" }}>
                                {qiData.overall}%
                              </div>
                              <div style={{ color: "#666", fontSize: "10px", marginBottom: "6px" }}>QI (All Time)</div>
                              <div style={{ display: "flex", gap: "4px", justifyContent: "center", flexWrap: "wrap" }}>
                                <button
                                  onClick={() => setTcmsDetailModal({ data: qiData.overallDetail, title: "TCMS QI - Overall", branch: row.branch })}
                                  style={{ padding: "2px 6px", fontSize: "10px", cursor: "pointer", background: "#007bff", color: "white", border: "none", borderRadius: "3px" }}
                                >
                                  Details
                                </button>
                                <a href={tcmsBaseUrl} target="_blank" rel="noopener noreferrer"
                                  style={{ padding: "2px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                                >
                                  TCMS
                                </a>
                              </div>
                            </div>
                          ) : qiData?.overall === "error" ? (
                            <div>
                              <div style={{ color: "#dc3545", fontSize: "11px", marginBottom: "4px" }}>Failed</div>
                              <a href={tcmsBaseUrl} target="_blank" rel="noopener noreferrer"
                                style={{ padding: "2px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                              >
                                TCMS
                              </a>
                            </div>
                          ) : overallLoading ? (
                            <span style={{ color: "#666", fontStyle: "italic" }}>Loading...</span>
                          ) : (
                            <div style={{ display: "flex", gap: "4px", justifyContent: "center", flexWrap: "wrap" }}>
                              <button
                                onClick={() => fetchBranchQi(row.branch, "all")}
                                style={{ padding: "3px 8px", fontSize: "11px", cursor: "pointer", background: "#007bff", color: "white", border: "none", borderRadius: "3px" }}
                              >
                                Load QI
                              </button>
                              <a href={tcmsBaseUrl} target="_blank" rel="noopener noreferrer"
                                style={{ padding: "3px 6px", fontSize: "10px", background: "#6c757d", color: "white", borderRadius: "3px", textDecoration: "none" }}
                              >
                                TCMS
                              </a>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

      {/* Triage Count Section */}
      {advancedOptions.triageCount && (
        <div style={{ marginTop: "40px", padding: "20px", background: "#f8f9fa", borderRadius: "8px" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", marginBottom: "15px" }}>
            <h3 style={{ marginTop: 0, marginBottom: 0, color: "#333" }}>Triage Count by Regression Owner</h3>
            <button
              type="button"
              onClick={handleRefreshOwnerTriageSection}
              disabled={loadingOwnerReport || loadingTriage}
              style={{
                padding: "7px 12px",
                fontSize: "12px",
                border: "1px solid #cbd5e1",
                borderRadius: "6px",
                background: (loadingOwnerReport || loadingTriage) ? "#e2e8f0" : "#ffffff",
                color: "#1e293b",
                cursor: (loadingOwnerReport || loadingTriage) ? "not-allowed" : "pointer",
                fontWeight: 600
              }}
              title="Refresh owner triage report and triage count"
            >
              {loadingOwnerReport || loadingTriage ? "Refreshing..." : "Refresh"}
            </button>
          </div>

          {ownerReportError && (
            <div style={{ color: "#dc3545", marginBottom: "12px", fontSize: "13px" }}>
              {ownerReportError}
            </div>
          )}

          {/* Notebook-schema owner table — 1-Click moves to top-right in Phase 4 */}
          <div style={{ marginBottom: "20px" }}>
            <h4 style={{ marginBottom: "10px" }}>Owner status breakdown (Failed / Skipped / Warning / Killed)</h4>
            {loadingOwnerReport && !ownerReportRows ? (
              <div style={{ color: "#666", fontStyle: "italic" }}>
                Loading owner triage report…
              </div>
            ) : ownerReportRows && ownerReportRows.length > 0 ? (
              <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "15px", background: "#fff" }}>
                <thead>
                  <tr style={{ background: "#e9ecef" }}>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Regression owner</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Total Triages</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Untriaged</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Failed</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Skipped</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Warning</th>
                    <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Killed</th>
                  </tr>
                </thead>
                <tbody>
                  {ownerReportRows.map((r) => (
                    <tr key={r.Regression_owner}>
                      <td style={{ padding: "8px", border: "1px solid #ddd" }}>{r.Regression_owner}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{r.Total}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center", color: "#dc3545", fontWeight: 600 }}>
                        {r["Total untriaged"]}
                      </td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{r.Failed}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{r.Skipped}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{r.Warning}</td>
                      <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{r.Killed}</td>
                    </tr>
                  ))}
                  {/* Totals Row */}
                  {ownerReportRows.length > 0 && (() => {
                    const totals = ownerReportRows.reduce((acc, r) => ({
                      total: acc.total + (r.Total || 0),
                      untriaged: acc.untriaged + (r["Total untriaged"] || 0),
                      failed: acc.failed + (r.Failed || 0),
                      skipped: acc.skipped + (r.Skipped || 0),
                      warning: acc.warning + (r.Warning || 0),
                      killed: acc.killed + (r.Killed || 0),
                    }), { total: 0, untriaged: 0, failed: 0, skipped: 0, warning: 0, killed: 0 });
                    
                    return (
                      <tr style={{ backgroundColor: "#e9ecef", fontWeight: "bold", borderTop: "2px solid #495057" }}>
                        <td style={{ padding: "8px", border: "1px solid #ddd" }}>TOTAL</td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{totals.total}</td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center", color: "#dc3545" }}>
                          {totals.untriaged}
                        </td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{totals.failed}</td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{totals.skipped}</td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{totals.warning}</td>
                        <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{totals.killed}</td>
                      </tr>
                    );
                  })()}
                </tbody>
              </table>
            ) : (
              <div style={{ color: "#666", fontSize: "13px", marginBottom: "15px" }}>
                No owner rows yet.
              </div>
            )}
          </div>

          {loadingTriage ? (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Loading triage count... This may take a minute as the backend processes data...
            </div>
          ) : triageCount ? (
            <div style={{ fontSize: "14px" }}>
              {triageCount.error ? (
                <div style={{ color: "#dc3545" }}>{triageCount.error}</div>
              ) : (
                <div>
                  {/* Display Bulk Issues Table - Always shown, QI Impact loaded on demand */}
                  {triageCount.bulk_issues && Object.keys(triageCount.bulk_issues).length > 0 && (
                    <div style={{ marginBottom: "20px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                        <h4 style={{ margin: 0 }}>Bulk Issues (tickets with &gt;5 testcases):</h4>
                        {(!triageCount.bulk_issues_with_qi || Object.keys(triageCount.bulk_issues_with_qi).length === 0) && (
                          <button
                            onClick={async () => {
                              await fetchBulkIssuesQi();
                            }}
                            disabled={loadingBulkQi}
                            style={{
                              padding: "6px 12px",
                              background: loadingBulkQi ? "#6c757d" : "#007bff",
                              color: "white",
                              border: "none",
                              borderRadius: "4px",
                              cursor: loadingBulkQi ? "not-allowed" : "pointer",
                              fontSize: "12px",
                              fontWeight: "500"
                            }}
                          >
                            {loadingBulkQi ? "Loading QI Impact..." : "Load QI Impact"}
                          </button>
                        )}
                      </div>
                      <div style={{ overflowX: "auto" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "10px" }}>
                          <thead>
                            <tr style={{ backgroundColor: "#f8f9fa" }}>
                              <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Bulk Issue Jita Ticket</th>
                              <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Testcase Impacted</th>
                              <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>QI Impact</th>
                              <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Risk Level</th>
                              <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Action</th>
                            </tr>
                          </thead>
                          <tbody>
                            {(() => {
                              const entries = Object.entries(triageCount.bulk_issues);
                              const hasQiData = triageCount.bulk_issues_with_qi && Object.keys(triageCount.bulk_issues_with_qi).length > 0;
                              
                              const sortedEntries = hasQiData
                                ? entries.sort((a, b) => {
                                    const qiA = triageCount.bulk_issues_with_qi[a[0]]?.overall_qi_impact ?? 0;
                                    const qiB = triageCount.bulk_issues_with_qi[b[0]]?.overall_qi_impact ?? 0;
                                    return qiA - qiB;
                                  })
                                : entries;
                              
                              const getRiskLevel = (qiImpact) => {
                                if (qiImpact === null || qiImpact === undefined) return null;
                                if (qiImpact <= -5) return { label: "Critical", color: "#dc3545", bg: "#f8d7da" };
                                if (qiImpact <= -2) return { label: "High", color: "#856404", bg: "#fff3cd" };
                                if (qiImpact <= -1) return { label: "Medium", color: "#0c5460", bg: "#d1ecf1" };
                                return { label: "Low", color: "#155724", bg: "#d4edda" };
                              };

                              return sortedEntries.map(([ticket, tests]) => {
                                const qiData = triageCount.bulk_issues_with_qi?.[ticket];
                                const showLoading = loadingBulkQi && !qiData;
                                const risk = qiData ? getRiskLevel(qiData.overall_qi_impact) : null;
                                const firstTest = tests[0] || "";
                                
                                return (
                                  <tr key={ticket}>
                                    <td style={{ padding: "8px", border: "1px solid #ddd" }}>
                                      <a
                                        href={`${JIRA_URL}${ticket}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        style={{ color: "#0066cc", textDecoration: "none" }}
                                      >
                                        {ticket}
                                      </a>
                                    </td>
                                    <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                      {qiData ? qiData.testcase_count : tests.length}
                                    </td>
                                    <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                      {showLoading ? (
                                        <span style={{ color: "#666", fontStyle: "italic" }}>Loading...</span>
                                      ) : qiData ? (
                                        qiData.overall_qi_impact.toFixed(2) + "%"
                                      ) : (
                                        "-"
                                      )}
                                    </td>
                                    <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                      {risk ? (
                                        <span style={{
                                          padding: "2px 8px", borderRadius: "12px", fontSize: "11px", fontWeight: "600",
                                          color: risk.color, background: risk.bg,
                                        }}>
                                          {risk.label}
                                        </span>
                                      ) : "-"}
                                    </td>
                                    <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                      <button
                                        onClick={() => openDeepAnalysisTab(ticket, firstTest, tests)}
                                        style={{
                                          padding: "3px 8px", fontSize: "10px", cursor: "pointer",
                                          background: "#6f42c1", color: "white", border: "none", borderRadius: "3px",
                                        }}
                                        title="Open Cursor AI deep analysis in a new tab"
                                      >
                                        Deep Analysis
                                      </button>
                                    </td>
                                  </tr>
                                );
                              });
                            })()}
                          </tbody>
                        </table>
                      </div>
                      {loadingBulkQi && (
                        <div style={{ color: "#666", fontStyle: "italic", padding: "10px", fontSize: "12px" }}>
                          Calculating QI impact for all bulk issues... This may take a few minutes...
                        </div>
                      )}

                      {/* AI Analysis for Bulk Issues */}
                      <div style={{ marginTop: "15px", display: "flex", alignItems: "center", gap: "10px" }}>
                        <button
                          onClick={fetchBulkIssuesAiAnalysis}
                          disabled={loadingBulkAi}
                          style={{
                            padding: "8px 16px",
                            background: loadingBulkAi ? "#6c757d" : "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                            color: "white",
                            border: "none",
                            borderRadius: "6px",
                            cursor: loadingBulkAi ? "not-allowed" : "pointer",
                            fontSize: "13px",
                            fontWeight: "600",
                            display: "flex",
                            alignItems: "center",
                            gap: "6px"
                          }}
                        >
                          {loadingBulkAi ? "Analyzing..." : "Load AI Analysis"}
                        </button>
                        {bulkIssuesAiAnalysis && !loadingBulkAi && (
                          <button
                            onClick={() => setBulkIssuesAiAnalysis(null)}
                            style={{
                              padding: "6px 10px",
                              background: "#dc3545",
                              color: "white",
                              border: "none",
                              borderRadius: "4px",
                              cursor: "pointer",
                              fontSize: "11px"
                            }}
                          >
                            Clear
                          </button>
                        )}
                      </div>

                      {loadingBulkAi && (
                        <div style={{ marginTop: "10px", color: "#667eea", fontStyle: "italic", fontSize: "12px" }}>
                          AI is analyzing bulk issue patterns and risk... This may take 30-60 seconds...
                        </div>
                      )}

                      {bulkIssuesAiAnalysis && (
                        <div style={{
                          marginTop: "15px",
                          padding: "16px",
                          background: "linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)",
                          borderRadius: "8px",
                          border: "1px solid #c4b5fd",
                          maxHeight: "500px",
                          overflowY: "auto"
                        }}>
                          <div style={{ fontWeight: "700", marginBottom: "8px", color: "#5b21b6", fontSize: "14px" }}>
                            AI Analysis — Bulk Issues
                          </div>
                          <AiMarkdown content={bulkIssuesAiAnalysis} />
                        </div>
                      )}
                    </div>
                  )}
                  
                  
                  {/* Display Owner Ticket Map as Table */}
                  {triageCount.owner_ticket_map && Object.keys(triageCount.owner_ticket_map).length > 0 && (() => {
                    // Aggregate bug types across every unique ticket in the current run.
                    const bugOrder = ["Product Bug", "Test Bug", "Environment", "Flaky", "Other"];
                    const bugTotals = { "Product Bug": 0, "Test Bug": 0, "Environment": 0, "Flaky": 0, "Other": 0 };
                    const bugTickets = { "Product Bug": [], "Test Bug": [], "Environment": [], "Flaky": [], "Other": [] };
                    const otherIssueTypes = {}; // issue_type -> count, for "Other" tooltip
                    const seenTickets = new Set();
                    Object.values(triageCount.owner_ticket_map).forEach((tks) => {
                      Object.keys(tks).forEach((t) => {
                        if (seenTickets.has(t)) return;
                        seenTickets.add(t);
                        const info = ownerJiraDetails[t];
                        const bt = bugTypeOf(info);
                        // Do not dump still-loading tickets into Other — that made
                        // Bugs Overview look like every ticket was untyped.
                        if (!info && (loadingJiraDetails || Object.keys(ownerJiraDetails).length === 0)) {
                          return;
                        }
                        const label = bt || "Other";
                        bugTotals[label] = (bugTotals[label] || 0) + 1;
                        bugTickets[label].push(t);
                        if (label === "Other") {
                          const it = info?.issue_type && info.issue_type !== "N/A"
                            ? info.issue_type
                            : "Not loaded / Unknown";
                          otherIssueTypes[it] = (otherIssueTypes[it] || 0) + 1;
                        }
                      });
                    });
                    const totalBugs = seenTickets.size;
                    const classifiedTotal = bugOrder.reduce((n, label) => n + (bugTotals[label] || 0), 0);
                    const otherTip = Object.keys(otherIssueTypes).length
                      ? "Other = non-bug Jira issue types: " +
                        Object.entries(otherIssueTypes).map(([k, v]) => `${k} (${v})`).join(", ")
                      : "Other = Jira issue types that are neither a bug nor a test issue";
                    const openBugType = (label) => openTickets(bugTickets[label] || []);
                    const donutSegments = bugOrder
                      .map((label) => ({ label, value: bugTotals[label] || 0, color: BUG_TYPE_COLORS[label] }))
                      .filter((s) => s.value > 0);
                    return (
                    <div style={{ marginTop: "20px" }}>
                      {/* Bug-type summary: pie on the left, count-pill legend on the right.
                          Click a slice or a legend row to open that bug type in Jira. */}
                      <div className="rh-bug-summary">
                        <BugPie segments={donutSegments} total={classifiedTotal} />
                        <div className="rh-bug-summary-legend">
                          <div className="rh-bug-summary-head">
                            <span className="rh-bug-summary-title">Bugs Overview</span>
                            <span className="rh-bug-summary-total-pill">{totalBugs}</span>
                          </div>
                          <ul className="rh-bug-summary-list">
                            {loadingJiraDetails && Object.values(bugTotals).every((n) => n === 0) && (
                              <li className="rh-bug-summary-item" style={{ cursor: "default" }}>
                                <span className="rh-bug-summary-name">Loading bug types…</span>
                              </li>
                            )}
                            {bugOrder.map((label) => (
                              bugTotals[label] > 0 ? (
                                <li
                                  key={label}
                                  className="rh-bug-summary-item"
                                  onClick={() => openBugType(label)}
                                  title={label === "Other" ? otherTip : `Open ${bugTotals[label]} ${label} ticket(s) in Jira`}
                                >
                                  <span className="rh-bug-summary-name">
                                    <span className="rh-bug-dot" style={{ background: BUG_TYPE_COLORS[label] }} />
                                    {label}
                                    {label === "Other" && <span className="rh-bug-summary-info">?</span>}
                                  </span>
                                  <span
                                    className="rh-bug-summary-pill"
                                    style={{ background: BUG_TYPE_COLORS[label] }}
                                  >
                                    {bugTotals[label]}
                                  </span>
                                </li>
                              ) : null
                            ))}
                          </ul>
                        </div>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                        <h4 style={{ margin: 0 }}>
                          Owner-wise Jira Ticket Breakdown:
                          {loadingJiraDetails && (
                            <span style={{ fontSize: "11px", color: "#6c757d", fontWeight: "normal", marginLeft: "10px" }}>
                              Loading JIRA details...
                            </span>
                          )}
                          {jiraDetailsError && !loadingJiraDetails && (
                            <span style={{ fontSize: "11px", color: "#b91c1c", fontWeight: "normal", marginLeft: "10px" }}>
                              {jiraDetailsError}
                            </span>
                          )}
                        </h4>
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          {(!triageCount.ticket_qi_map || Object.keys(triageCount.ticket_qi_map).length === 0) && (
                            <button
                              onClick={fetchBulkIssuesQi}
                              disabled={loadingBulkQi}
                              style={{
                                padding: "7px 14px",
                                background: loadingBulkQi ? "#6c757d" : "#007bff",
                                color: "white",
                                border: "none",
                                borderRadius: "6px",
                                cursor: loadingBulkQi ? "not-allowed" : "pointer",
                                fontSize: "12px",
                                fontWeight: "600"
                              }}
                            >
                              {loadingBulkQi ? "Loading QI Impact..." : "Load QI Impact"}
                            </button>
                          )}
                          <button
                            onClick={fetchOwnerJiraDetails}
                            disabled={loadingJiraDetails}
                            style={{
                              padding: "7px 14px",
                              background: loadingJiraDetails ? "#6c757d" : "linear-gradient(135deg, #36d1dc 0%, #5b86e5 100%)",
                              color: "white",
                              border: "none",
                              borderRadius: "6px",
                              cursor: loadingJiraDetails ? "not-allowed" : "pointer",
                              fontSize: "12px",
                              fontWeight: "600"
                            }}
                          >
                            {loadingJiraDetails ? "Fetching..." : Object.keys(ownerJiraDetails).length > 0 ? "Refresh Status" : "Load Status & Type"}
                          </button>
                          <button
                            onClick={fetchOwnerTicketsAiAnalysis}
                            disabled={loadingOwnerAi}
                            style={{
                              padding: "7px 14px",
                              background: loadingOwnerAi ? "#6c757d" : "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                              color: "white",
                              border: "none",
                              borderRadius: "6px",
                              cursor: loadingOwnerAi ? "not-allowed" : "pointer",
                              fontSize: "12px",
                              fontWeight: "600"
                            }}
                          >
                            {loadingOwnerAi ? "Analyzing..." : "Load AI Analysis"}
                          </button>
                          {ownerTicketsAiAnalysis && !loadingOwnerAi && (
                            <button
                              onClick={() => setOwnerTicketsAiAnalysis(null)}
                              style={{
                                padding: "5px 9px",
                                background: "#dc3545",
                                color: "white",
                                border: "none",
                                borderRadius: "4px",
                                cursor: "pointer",
                                fontSize: "11px"
                              }}
                            >
                              Clear
                            </button>
                          )}
                        </div>
                      </div>
                      <div className="rh-owner-grid">
                        {(() => {
                          // QI badges only after "Load QI Impact" — no placeholder before that
                          const qiImpactReady =
                            (triageCount.ticket_qi_map && Object.keys(triageCount.ticket_qi_map).length > 0) ||
                            (triageCount.bulk_issues_with_qi && Object.keys(triageCount.bulk_issues_with_qi).length > 0);
                          return Object.entries(triageCount.owner_ticket_map).map(([owner, tickets]) => {
                          // Highest testcase-impact ticket first.
                          const ticketEntries = Object.entries(tickets).sort((a, b) => b[1] - a[1]);
                          // Per-owner bug-type tallies for the tile header badges.
                          let ownerProductBugs = 0;
                          let ownerTestBugs = 0;
                          ticketEntries.forEach(([t]) => {
                            const bt = bugTypeOf(ownerJiraDetails[t]);
                            if (bt === "Product Bug") ownerProductBugs += 1;
                            else if (bt === "Test Bug") ownerTestBugs += 1;
                          });
                          const statusStyle = (status) => ({
                            background: status === "Closed" || status === "Resolved" ? "#d1fae5"
                              : status === "In Progress" ? "#dbeafe"
                              : status === "Open" || status === "To Do" ? "#fee2e2"
                              : "#f3f4f6",
                            color: status === "Closed" || status === "Resolved" ? "#065f46"
                              : status === "In Progress" ? "#1e40af"
                              : status === "Open" || status === "To Do" ? "#991b1b"
                              : "#374151"
                          });
                          return (
                            <div key={owner} className="rh-owner-card">
                              <div className="rh-owner-head">
                                <button
                                  type="button"
                                  className="rh-owner-name rh-owner-name-link"
                                  onClick={() => openTickets(ticketEntries.map(([t]) => t))}
                                  title={`Open ${owner}'s ${ticketEntries.length} ticket(s) in Jira`}
                                >
                                  {owner}
                                </button>
                                <div className="rh-owner-head-right">
                                  <div className="rh-owner-bugcounts">
                                    <span className="rh-owner-bugcount" title="Product Bugs">
                                      <span className="rh-bug-dot" style={{ background: BUG_TYPE_COLORS["Product Bug"] }} />
                                      {ownerProductBugs}
                                    </span>
                                    <span className="rh-owner-bugcount" title="Test Bugs">
                                      <span className="rh-bug-dot" style={{ background: BUG_TYPE_COLORS["Test Bug"] }} />
                                      {ownerTestBugs}
                                    </span>
                                  </div>
                                  <span className="rh-owner-count">{ticketEntries.length} ticket{ticketEntries.length !== 1 ? "s" : ""}</span>
                                </div>
                              </div>
                              <ul className="rh-owner-tickets">
                                {ticketEntries.map(([ticket, count]) => {
                                  const jiraInfo = ownerJiraDetails[ticket];
                                  const qiData = qiImpactReady
                                    ? (triageCount.ticket_qi_map?.[ticket] || triageCount.bulk_issues_with_qi?.[ticket])
                                    : null;
                                  const bt = bugTypeOf(jiraInfo);
                                  const risk = qiData ? riskFromQi(qiData.overall_qi_impact) : null;
                                  const hasStatus = jiraInfo && jiraInfo.status && jiraInfo.status !== "N/A";
                                  const dotColor = bt ? BUG_TYPE_COLORS[bt] : "#d1d5db";
                                  const dotTip = bt
                                    ? `${bt}${jiraInfo?.issue_type ? ` — Issue Type: ${jiraInfo.issue_type}` : ""}`
                                    : (jiraInfo ? `Other — Issue Type: ${jiraInfo.issue_type || "N/A"}` : "Loading bug type…");
                                  return (
                                    <li key={ticket}>
                                      <span className="rh-bug-dot rh-bug-dot-lg rh-bug-dot-spaced" style={{ background: dotColor }} title={dotTip} />
                                      <a className="rh-ticket-link" href={`${JIRA_URL}${ticket}`} target="_blank" rel="noreferrer">
                                        {ticket}
                                      </a>
                                      <span className="rh-ticket-state-wrap">
                                        <span
                                          className="rh-ticket-status"
                                          style={hasStatus ? statusStyle(jiraInfo.status) : { background: "#f3f4f6", color: "#9ca3af" }}
                                          title={jiraInfo?.issue_type ? `Type: ${jiraInfo.issue_type}` : undefined}
                                        >
                                          {hasStatus ? jiraInfo.status : (jiraInfo ? "N/A" : "…")}
                                        </span>
                                      </span>
                                      <span className="rh-ticket-meta">
                                        {qiData && (
                                          <span className="rh-qi-badge" title="QI Impact for this ticket">
                                            {qiData.overall_qi_impact.toFixed(1)}% QI
                                          </span>
                                        )}
                                        {risk && (
                                          <span
                                            className="rh-risk-badge"
                                            style={{ background: RISK_COLORS[risk].bg, color: RISK_COLORS[risk].color }}
                                            title="Risk Level"
                                          >
                                            {risk}
                                          </span>
                                        )}
                                        <span className="rh-ticket-count" title="Testcases affected">{count} tc</span>
                                      </span>
                                    </li>
                                  );
                                })}
                              </ul>
                            </div>
                          );
                        });
                        })()}
                      </div>

                      {loadingOwnerAi && (
                        <div style={{ marginTop: "10px", color: "#667eea", fontStyle: "italic", fontSize: "12px" }}>
                          AI is analyzing owner ticket patterns... This may take 30-60 seconds...
                        </div>
                      )}

                      {ownerTicketsAiAnalysis && (
                        <div style={{
                          marginTop: "15px",
                          padding: "16px",
                          background: "linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%)",
                          borderRadius: "8px",
                          border: "1px solid #c4b5fd",
                          maxHeight: "500px",
                          overflowY: "auto"
                        }}>
                          <div style={{ fontWeight: "700", marginBottom: "8px", color: "#5b21b6", fontSize: "14px" }}>
                            AI Analysis — Owner Ticket Breakdown
                          </div>
                          <AiMarkdown content={ownerTicketsAiAnalysis} />
                        </div>
                      )}
                    </div>
                    );
                  })()}
                </div>
              )}
            </div>
          ) : (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Click "Save" in Advanced Action to load triage count data.
            </div>
          )}
        </div>
      )}

      {/* Triage Accuracy Analyzer Section */}
      {advancedOptions.triageAccuracy && (
        <section className="rh-report-panel" aria-labelledby="rh-triage-accuracy-title">
          <header className="rh-report-header">
            <div className="rh-report-title-block">
              <p className="rh-report-eyebrow">Analysis</p>
              <h3 id="rh-triage-accuracy-title" className="rh-report-title">Triage Accuracy</h3>
              <p className="rh-report-subtitle">
                Compare completed triage against Triage Genie recommendations for failed and warning testcases.
              </p>
            </div>
            <div className="rh-report-actions">
              <button
                type="button"
                className="rh-report-btn rh-report-btn-primary"
                onClick={handleReloadTriageAccuracy}
                disabled={loadingTriageAccuracy}
              >
                {loadingTriageAccuracy ? "Reloading…" : "Reload data"}
              </button>
              <button
                type="button"
                className="rh-report-btn rh-report-btn-success"
                onClick={handleDownloadTriageAccuracyExcel}
                disabled={loadingTriageAccuracy || !triageAccuracyData || !!triageAccuracyData.error}
              >
                Download Excel
              </button>
            </div>
          </header>
          <div className="rh-report-body">
            {loadingTriageAccuracy ? (
              <div className="rh-report-loading">
                Loading triage accuracy… Triage Genie lookups can take several minutes for large runs.
              </div>
            ) : triageAccuracyData?.error ? (
              <div className="rh-report-error">{triageAccuracyData.error}</div>
            ) : triageAccuracyData?.triage_summary ? (
              <>
                <div className="rh-metric-grid">
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Failed / warning</div>
                    <div className="rh-metric-value">
                      {triageAccuracyData.triage_summary.total_failed_warning_count
                        ?? triageAccuracyData?.testcases?.length
                        ?? 0}
                    </div>
                    <div className="rh-metric-hint">Testcases in scope</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Triage completed</div>
                    <div className="rh-metric-value is-ok">
                      {triageAccuracyData.triage_summary.triage_completed_percent ?? 0}%
                    </div>
                    <div className="rh-metric-hint">
                      {triageAccuracyData.triage_summary.triaged_count ?? 0} triaged
                    </div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Genie tagged</div>
                    <div className="rh-metric-value is-info">
                      {triageAccuracyData.triage_summary.total_triage_genie_percent ?? 0}%
                    </div>
                    <div className="rh-metric-hint">
                      {triageAccuracyData.triage_summary.total_triage_genie_count ?? 0} testcases
                    </div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Matched</div>
                    <div className="rh-metric-value is-ok">
                      {triageAccuracyData.triage_summary.matched_percent ?? 0}%
                    </div>
                    <div className="rh-metric-hint">
                      {triageAccuracyData.triage_summary.matched_count ?? 0} aligned
                    </div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Unmatched</div>
                    <div className="rh-metric-value is-warn">
                      {triageAccuracyData.triage_summary.unmatched_percent ?? 0}%
                    </div>
                    <div className="rh-metric-hint">
                      {triageAccuracyData.triage_summary.unmatched_count ?? 0} diverge
                    </div>
                  </div>
                </div>

                <div className="rh-report-section">
                  <h4 className="rh-report-section-title">Breakdown</h4>
                  <div className="rh-report-table-wrap">
                    <table className="rh-report-table">
                      <thead>
                        <tr>
                          <th>Metric</th>
                          <th className="num">Count</th>
                          <th className="num">Percentage</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td>Triage Genie ticket rate (of completed triage)</td>
                          <td className="num">{triageAccuracyData.triage_summary.triage_genie_count ?? 0}</td>
                          <td className="num is-info">{triageAccuracyData.triage_summary.triage_genie_percent ?? 0}%</td>
                        </tr>
                        <tr>
                          <td>Matched with Triage Genie</td>
                          <td className="num">{triageAccuracyData.triage_summary.matched_count ?? 0}</td>
                          <td className="num is-ok">{triageAccuracyData.triage_summary.matched_percent ?? 0}%</td>
                        </tr>
                        <tr>
                          <td>Unmatched with Triage Genie</td>
                          <td className="num">{triageAccuracyData.triage_summary.unmatched_count ?? 0}</td>
                          <td className="num is-warn">{triageAccuracyData.triage_summary.unmatched_percent ?? 0}%</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : (
              <div className="rh-report-empty">
                Enable this option and save configuration to load triage accuracy data.
              </div>
            )}
          </div>
        </section>
      )}

      {/* QI Impacted Bulk issue Section - Separate from Triage Count */}
      {advancedOptions.qiImpactedBulkIssue && triageCount && (
        <div style={{ marginTop: "40px", padding: "20px", background: "#f8f9fa", borderRadius: "8px" }}>
          <h3 style={{ marginTop: 0, marginBottom: "15px", color: "#333" }}>QI Impacted Bulk issue</h3>
          {loadingBulkQi ? (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Loading QI Impacted Bulk issue data... This may take a few minutes as the backend calculates QI impact for each testcase...
            </div>
          ) : triageCount.error ? (
            <div style={{ color: "#dc3545" }}>{triageCount.error}</div>
          ) : triageCount.bulk_issues && Object.keys(triageCount.bulk_issues).length > 0 ? (
            <div style={{ fontSize: "14px" }}>
              {/* Display Bulk Issues Table */}
              <div style={{ marginBottom: "20px" }}>
                <h4 style={{ marginBottom: "10px" }}>Bulk Issues (tickets with &gt;5 testcases):</h4>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "10px" }}>
                    <thead>
                      <tr style={{ backgroundColor: "#f8f9fa" }}>
                        <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Bulk Issue Jita Ticket</th>
                        <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Testcase Impacted</th>
                        <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>QI Impact due to this bug</th>
                      </tr>
                    </thead>
                    <tbody>
                      {triageCount.bulk_issues_with_qi ? (
                        // Use QI impact data if available
                        Object.entries(triageCount.bulk_issues_with_qi)
                          .sort((a, b) => a[1].overall_qi_impact - b[1].overall_qi_impact) // Sort by QI impact (most negative first)
                          .map(([ticket, data]) => (
                            <tr key={ticket}>
                              <td style={{ padding: "8px", border: "1px solid #ddd" }}>
                                <a
                                  href={`${JIRA_URL}${ticket}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  style={{ color: "#0066cc", textDecoration: "none" }}
                                >
                                  {ticket}
                                </a>
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                {data.testcase_count}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                {data.overall_qi_impact.toFixed(2)}%
                              </td>
                            </tr>
                          ))
                      ) : (
                        // Fallback to simple list format if QI data not available
                        Object.entries(triageCount.bulk_issues).map(([ticket, tests]) => (
                          <tr key={ticket}>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>
                              <a
                                href={`${JIRA_URL}${ticket}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{ color: "#0066cc", textDecoration: "none" }}
                              >
                                {ticket}
                              </a>
                            </td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                              {tests.length}
                            </td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                              N/A
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Display Bulk Issues QI Impacting Testcases - Detailed Table */}
              {advancedOptions.bulkIssuesQiImpact && 
               triageCount.bulk_issues_with_qi && 
               Object.keys(triageCount.bulk_issues_with_qi).length > 0 && (
                <div style={{ marginBottom: "20px", marginTop: "30px" }}>
                  <h4 style={{ marginBottom: "10px" }}>Bulk Issues QI Impacting Testcases:</h4>
                  <div style={{ overflowX: "auto" }}>
                    <table style={{ width: "100%", borderCollapse: "collapse", marginTop: "10px" }}>
                      <thead>
                        <tr style={{ backgroundColor: "#f8f9fa" }}>
                          <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Bulk Issue Jita Ticket</th>
                          <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Testcase Impacted</th>
                          <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>QI Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(triageCount.bulk_issues_with_qi)
                          .sort((a, b) => a[1].overall_qi_impact - b[1].overall_qi_impact)
                          .map(([ticket, data]) => {
                            // Use testcase_qi_details if available, otherwise fallback to testcases array
                            const testcaseDetails = data.testcase_qi_details || 
                              (data.testcases ? data.testcases.map(tc => ({ testcase: tc, qi: 0 })) : []);
                            
                            return testcaseDetails.map((detail, index) => (
                              <tr key={`${ticket}-${index}`}>
                                {index === 0 && (
                                  <td 
                                    rowSpan={testcaseDetails.length}
                                    style={{ padding: "8px", border: "1px solid #ddd", verticalAlign: "top" }}
                                  >
                                    <a
                                      href={`${JIRA_URL}${ticket}`}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      style={{ color: "#0066cc", textDecoration: "none" }}
                                    >
                                      {ticket}
                                    </a>
                                    <div style={{ fontSize: "12px", color: "#666", marginTop: "4px" }}>
                                      Avg QI: {data.average_qi}% | Impact: {data.overall_qi_impact.toFixed(2)}%
                                    </div>
                                  </td>
                                )}
                                <td style={{ padding: "8px", border: "1px solid #ddd", fontFamily: "monospace", fontSize: "12px" }}>
                                  {detail.testcase}
                                </td>
                                <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>
                                  <span style={{ 
                                    color: detail.qi < 50 ? "#dc3545" : detail.qi < 100 ? "#ffc107" : "#28a745",
                                    fontWeight: "bold"
                                  }}>
                                    {detail.qi.toFixed(2)}%
                                  </span>
                                </td>
                              </tr>
                            ));
                          })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              No bulk issues found. Bulk issues are tickets with more than 5 testcases.
            </div>
          )}
        </div>
      )}

      {/* QI Summary Report Section */}
      {advancedOptions.qiSummaryReport && (
        <section className="rh-report-panel" aria-labelledby="rh-qi-summary-title">
          <header className="rh-report-header">
            <div className="rh-report-title-block">
              <h3 id="rh-qi-summary-title" className="rh-report-title">Current Run Summary Report</h3>
              <p className="rh-report-subtitle">
                Task and test outcome snapshot for the current tag or task ID set, including per-branch rollup.
              </p>
            </div>
          </header>
          <div className="rh-report-body">
            {loadingQiSummary ? (
              <div className="rh-report-loading">
                Loading QI summary… Backend is aggregating task and test results.
              </div>
            ) : qiSummaryReport?.error ? (
              <div className="rh-report-error">{qiSummaryReport.error}</div>
            ) : qiSummaryReport ? (
              <>
                <div className="rh-metric-grid">
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Total tasks</div>
                    <div className="rh-metric-value">{qiSummaryReport.total_tasks ?? 0}</div>
                  </div>
                  {qiSummaryReport.status_summary && (
                    <>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Completed</div>
                        <div className="rh-metric-value is-ok">{qiSummaryReport.status_summary.completed ?? 0}</div>
                      </div>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Testing</div>
                        <div className="rh-metric-value is-accent">{qiSummaryReport.status_summary.testing ?? 0}</div>
                      </div>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Pending</div>
                        <div className="rh-metric-value is-info">{qiSummaryReport.status_summary.pending ?? 0}</div>
                      </div>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Failed tasks</div>
                        <div className="rh-metric-value is-bad">{qiSummaryReport.status_summary.failed ?? 0}</div>
                      </div>
                    </>
                  )}
                  {qiSummaryReport.test_summary && (
                    <>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Total tests</div>
                        <div className="rh-metric-value">{qiSummaryReport.test_summary.total ?? 0}</div>
                      </div>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Succeeded</div>
                        <div className="rh-metric-value is-ok">{qiSummaryReport.test_summary.succeeded ?? 0}</div>
                      </div>
                      <div className="rh-metric-card">
                        <div className="rh-metric-label">Failed tests</div>
                        <div className="rh-metric-value is-bad">{qiSummaryReport.test_summary.failed ?? 0}</div>
                      </div>
                    </>
                  )}
                </div>

                <div className="rh-report-split">
                  {qiSummaryReport.status_summary && (
                    <div className="rh-report-section">
                      <h4 className="rh-report-section-title">Task status</h4>
                      <div className="rh-report-table-wrap">
                        <table className="rh-report-table">
                          <thead>
                            <tr>
                              <th>Status</th>
                              <th className="num">Count</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>Total tasks</td>
                              <td className="num">{qiSummaryReport.total_tasks ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Testing</td>
                              <td className="num is-accent">{qiSummaryReport.status_summary.testing ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Completed</td>
                              <td className="num is-ok">{qiSummaryReport.status_summary.completed ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Pending</td>
                              <td className="num is-info">{qiSummaryReport.status_summary.pending ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Failed</td>
                              <td className="num is-bad">{qiSummaryReport.status_summary.failed ?? 0}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {qiSummaryReport.test_summary && (
                    <div className="rh-report-section">
                      <h4 className="rh-report-section-title">Test outcomes</h4>
                      <div className="rh-report-table-wrap">
                        <table className="rh-report-table">
                          <thead>
                            <tr>
                              <th>Outcome</th>
                              <th className="num">Count</th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr>
                              <td>Total</td>
                              <td className="num">{qiSummaryReport.test_summary.total ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Succeeded</td>
                              <td className="num is-ok">{qiSummaryReport.test_summary.succeeded ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Failed</td>
                              <td className="num is-bad">{qiSummaryReport.test_summary.failed ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Pending</td>
                              <td className="num is-info">{qiSummaryReport.test_summary.pending ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Warning</td>
                              <td className="num is-warn">{qiSummaryReport.test_summary.warning ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Running</td>
                              <td className="num is-accent">{qiSummaryReport.test_summary.running ?? 0}</td>
                            </tr>
                            <tr>
                              <td>Skipped</td>
                              <td className="num is-muted">{qiSummaryReport.test_summary.skipped ?? 0}</td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </div>

                {qiSummaryReport.branch_summary && Object.keys(qiSummaryReport.branch_summary).length > 0 && (
                  <div className="rh-report-section">
                    <h4 className="rh-report-section-title">Branch rollup</h4>
                    <div className="rh-report-table-wrap">
                      <table className="rh-report-table">
                        <thead>
                          <tr>
                            <th>Branch</th>
                            <th className="num">Tasks</th>
                            <th className="num">Tests</th>
                            <th className="num">Failed tests</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(qiSummaryReport.branch_summary).map(([branch, stats]) => (
                            <tr key={branch}>
                              <td>{branch}</td>
                              <td className="num">{stats.total_tasks}</td>
                              <td className="num">{stats.total_tests}</td>
                              <td className="num is-bad">{stats.failed_tests}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="rh-report-empty">
                Save configuration with this option enabled to load the QI summary report.
              </div>
            )}
          </div>
        </section>
      )}

      {/* TCMS Overview Section */}
      {advancedOptions.tcmsOverview && (
        <section className="rh-report-panel" aria-labelledby="rh-tcms-overview-title">
          <header className="rh-report-header">
            <div className="rh-report-title-block">
              <h3 id="rh-tcms-overview-title" className="rh-report-title">TCMS Overview</h3>
              <p className="rh-report-subtitle">Quality Index metrics from TCMS for verification</p>
            </div>
            <div style={{ display: "flex", gap: "10px" }}>
              <button
                className="rh-btn-secondary"
                onClick={() => window.open(tcmsOverviewData?.tcms_ui_url, "_blank")}
                disabled={!tcmsOverviewData?.tcms_ui_url}
                style={{
                  padding: "8px 16px",
                  borderRadius: "4px",
                  border: "1px solid #6c757d",
                  background: tcmsOverviewData?.tcms_ui_url ? "#6c757d" : "#e9ecef",
                  color: tcmsOverviewData?.tcms_ui_url ? "white" : "#6c757d",
                  cursor: tcmsOverviewData?.tcms_ui_url ? "pointer" : "not-allowed"
                }}
              >
                Open TCMS
              </button>
              <button
                className="rh-btn-primary"
                onClick={fetchJitaTcmsComparison}
                disabled={loadingComparison || !tcmsOverviewData}
                style={{
                  padding: "8px 16px",
                  borderRadius: "4px",
                  border: "none",
                  background: (loadingComparison || !tcmsOverviewData) ? "#e9ecef" : "#007bff",
                  color: (loadingComparison || !tcmsOverviewData) ? "#6c757d" : "white",
                  cursor: (loadingComparison || !tcmsOverviewData) ? "not-allowed" : "pointer"
                }}
              >
                {loadingComparison ? "Comparing..." : "Compare Jita vs TCMS"}
              </button>
            </div>
          </header>

          <div className="rh-report-body">
            {loadingTcmsOverview ? (
              <div className="rh-report-loading">
                Loading TCMS overview data...
              </div>
            ) : tcmsOverviewData ? (
              <>
                <div className="rh-metric-grid">
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">QI (avg_total_op_success_%)</div>
                    <div className="rh-metric-value" style={{ 
                      color: qiColor(tcmsOverviewData.qi_value),
                      fontWeight: "bold"
                    }}>
                      {tcmsOverviewData.qi_value != null ? `${tcmsOverviewData.qi_value}%` : "-"}
                    </div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Total Tests</div>
                    <div className="rh-metric-value">{tcmsOverviewData.total_tests ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Run</div>
                    <div className="rh-metric-value">{tcmsOverviewData.run ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Passed</div>
                    <div className="rh-metric-value is-ok">{tcmsOverviewData.passed ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Failed</div>
                    <div className="rh-metric-value is-bad">{tcmsOverviewData.failed ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Not Run</div>
                    <div className="rh-metric-value">{tcmsOverviewData.not_run ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Run %</div>
                    <div className="rh-metric-value">
                      {tcmsOverviewData.run_percentage != null ? `${tcmsOverviewData.run_percentage}%` : "-"}
                    </div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Total Triaged</div>
                    <div className="rh-metric-value">{tcmsOverviewData.total_triaged ?? "-"}</div>
                  </div>
                  <div className="rh-metric-card">
                    <div className="rh-metric-label">Triage %</div>
                    <div className="rh-metric-value">
                      {tcmsOverviewData.triage_percentage != null ? `${tcmsOverviewData.triage_percentage}%` : "-"}
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: "16px", padding: "12px", background: "#f8f9fa", borderRadius: "4px" }}>
                  <div style={{ fontSize: "12px", color: "#666" }}>
                    <strong>Milestone:</strong> {tcmsOverviewData.milestone} | {" "}
                    <strong>Team:</strong> {tcmsOverviewData.team_name} | {" "}
                    <strong>Branch:</strong> {tcmsOverviewData.branch_name}
                  </div>
                </div>
              </>
            ) : (
              <div className="rh-report-empty">
                Save configuration with this option enabled to load TCMS overview data.
              </div>
            )}
          </div>
        </section>
      )}

      {/* TCMS Detail Modal */}
      </>}
      {tcmsDetailModal && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.5)", zIndex: 9999,
          display: "flex", alignItems: "center", justifyContent: "center",
        }} onClick={() => setTcmsDetailModal(null)}>
          <div style={{
            background: "white", borderRadius: "8px", padding: "24px",
            maxWidth: "600px", width: "90%", maxHeight: "80vh", overflowY: "auto",
            boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
          }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <h3 style={{ margin: 0 }}>{tcmsDetailModal.title} — {tcmsDetailModal.branch}</h3>
              <button onClick={() => setTcmsDetailModal(null)}
                style={{ background: "none", border: "none", fontSize: "20px", cursor: "pointer", color: "#666" }}>✕</button>
            </div>
            {tcmsDetailModal.data ? (
              <div>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                  <tbody>
                    {[
                      ["QI (avg_total_op_success_%)", tcmsDetailModal.data.qi_value != null ? `${tcmsDetailModal.data.qi_value}%` : "-", "#007bff"],
                      ["Total Tests", tcmsDetailModal.data.total_tests],
                      ["Run", tcmsDetailModal.data.run],
                      ["Passed", tcmsDetailModal.data.passed, "#28a745"],
                      ["Failed", tcmsDetailModal.data.failed, "#dc3545"],
                      ["Not Run", tcmsDetailModal.data.not_run, "#6c757d"],
                      ["Run %", tcmsDetailModal.data.run_percentage != null ? `${tcmsDetailModal.data.run_percentage}%` : "-"],
                      ["Total Triaged", tcmsDetailModal.data.total_triaged],
                      ["Triage %", tcmsDetailModal.data.triage_percentage != null ? `${tcmsDetailModal.data.triage_percentage}%` : "-"],
                      ["Product Issues", tcmsDetailModal.data.total_product_issues],
                      ["Test Issues", tcmsDetailModal.data.total_test_issues],
                      ["Other Issues", tcmsDetailModal.data.total_other_issues],
                      ["Infra Issues", tcmsDetailModal.data.total_infra_issues],
                      ["Framework Issues", tcmsDetailModal.data.total_framework_issues],
                      ["Open Bugs", tcmsDetailModal.data.openBugs, "#dc3545"],
                      ["Overall Effectiveness", tcmsDetailModal.data.overall_effectiveness != null ? `${tcmsDetailModal.data.overall_effectiveness}%` : "-"],
                      ["Overall Stability", tcmsDetailModal.data.overall_stability != null ? `${tcmsDetailModal.data.overall_stability}%` : "-"],
                    ].map(([label, value, color]) => (
                      <tr key={label}>
                        <td style={{ padding: "6px 8px", borderBottom: "1px solid #eee", fontWeight: "500" }}>{label}</td>
                        <td style={{ padding: "6px 8px", borderBottom: "1px solid #eee", color: color || "inherit", fontWeight: color ? "bold" : "normal" }}>
                          {value != null ? value : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {tcmsDetailModal.data.unique_tickets && tcmsDetailModal.data.unique_tickets.length > 0 && (
                  <div style={{ marginTop: "16px" }}>
                    <strong>Unique Tickets ({tcmsDetailModal.data.unique_tickets.length}):</strong>
                    <div style={{ marginTop: "8px", display: "flex", gap: "8px", alignItems: "center" }}>
                      {(() => {
                        const jiraUrl = jiraJqlUrl(tcmsDetailModal.data.unique_tickets);
                        const urlLength = jiraUrl ? jiraUrl.length : 0;
                        const isUrlTooLong = urlLength > 2000;
                        
                        if (isUrlTooLong) {
                          return (
                            <>
                              <button
                                onClick={() => openTickets(tcmsDetailModal.data.unique_tickets)}
                                style={{ padding: "4px 10px", fontSize: "12px", background: "#007bff", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                                title="Open tickets in JIRA (URL too long for direct link)"
                              >
                                View All in JIRA ({tcmsDetailModal.data.unique_tickets.length} tickets)
                              </button>
                              <span style={{ fontSize: "10px", color: "#dc3545" }}>
                                (URL too long, using popup)
                              </span>
                            </>
                          );
                        }
                        
                        return (
                          <a
                            href={jiraUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ padding: "4px 10px", fontSize: "12px", background: "#007bff", color: "white", borderRadius: "4px", textDecoration: "none", display: "inline-block" }}
                          >
                            View All in JIRA ({tcmsDetailModal.data.unique_tickets.length} tickets)
                          </a>
                        );
                      })()}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ color: "#666", fontStyle: "italic" }}>No detail data available.</div>
            )}
          </div>
        </div>
      )}

      {/* JITA vs TCMS Comparison Modal */}
      {showComparisonModal && jitaTcmsComparison && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.5)", zIndex: 9999,
          display: "flex", alignItems: "center", justifyContent: "center",
        }} onClick={() => setShowComparisonModal(false)}>
          <div style={{
            background: "white", borderRadius: "8px", padding: "0",
            maxWidth: "1400px", width: "95%", maxHeight: "90vh",
            boxShadow: "0 4px 20px rgba(0,0,0,0.3)",
            display: "flex", flexDirection: "column"
          }} onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div style={{ 
              padding: "20px 24px", 
              borderBottom: "1px solid #dee2e6",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center"
            }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "20px" }}>Jita vs TCMS Testcase Comparison</h3>
                <p style={{ margin: "4px 0 0 0", fontSize: "13px", color: "#666" }}>
                  Milestone: {jitaTcmsComparison.milestone} | Team: {jitaTcmsComparison.team_name} | Branch: {jitaTcmsComparison.branch_name}
                </p>
              </div>
              <button onClick={() => setShowComparisonModal(false)}
                style={{ 
                  background: "none", border: "none", fontSize: "24px", 
                  cursor: "pointer", color: "#666", padding: "0 8px"
                }}>✕</button>
            </div>

            {/* Summary Stats */}
            <div style={{ padding: "20px 24px", borderBottom: "1px solid #dee2e6" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: "16px" }}>
                <div className="stat-card">
                  <div className="stat-label">Jita Testcases</div>
                  <div className="stat-value">{jitaTcmsComparison.summary.total_jita}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">TCMS Testcases</div>
                  <div className="stat-value">{jitaTcmsComparison.summary.total_tcms}</div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Matched</div>
                  <div className="stat-value" style={{ color: "#28a745" }}>
                    {jitaTcmsComparison.summary.matched_count}
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Missing in Jita</div>
                  <div className="stat-value" style={{ color: "#ffc107" }}>
                    {jitaTcmsComparison.summary.missing_in_jita_count}
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Match Rate</div>
                  <div className="stat-value" style={{ color: "#007bff" }}>
                    {jitaTcmsComparison.summary.exact_match_percentage}%
                  </div>
                </div>
              </div>
            </div>

            {/* Tabs */}
            <div className="comparison-tabs" style={{ 
              display: "flex", 
              gap: "0", 
              borderBottom: "1px solid #dee2e6",
              padding: "0 24px",
              background: "#f8f9fa"
            }}>
              <button
                className={comparisonActiveTab === "matched" ? "active" : ""}
                onClick={() => setComparisonActiveTab("matched")}
                style={{
                  padding: "12px 20px",
                  border: "none",
                  background: comparisonActiveTab === "matched" ? "white" : "transparent",
                  cursor: "pointer",
                  borderBottom: comparisonActiveTab === "matched" ? "2px solid #007bff" : "2px solid transparent",
                  color: comparisonActiveTab === "matched" ? "#007bff" : "#666",
                  fontWeight: comparisonActiveTab === "matched" ? "600" : "normal",
                  fontSize: "14px"
                }}
              >
                Matched ({jitaTcmsComparison.summary.matched_count})
              </button>
              <button
                className={comparisonActiveTab === "missing_jita" ? "active" : ""}
                onClick={() => setComparisonActiveTab("missing_jita")}
                style={{
                  padding: "12px 20px",
                  border: "none",
                  background: comparisonActiveTab === "missing_jita" ? "white" : "transparent",
                  cursor: "pointer",
                  borderBottom: comparisonActiveTab === "missing_jita" ? "2px solid #007bff" : "2px solid transparent",
                  color: comparisonActiveTab === "missing_jita" ? "#007bff" : "#666",
                  fontWeight: comparisonActiveTab === "missing_jita" ? "600" : "normal",
                  fontSize: "14px"
                }}
              >
                Missing in Jita ({jitaTcmsComparison.summary.missing_in_jita_count})
              </button>
              <button
                className={comparisonActiveTab === "missing_tcms" ? "active" : ""}
                onClick={() => setComparisonActiveTab("missing_tcms")}
                style={{
                  padding: "12px 20px",
                  border: "none",
                  background: comparisonActiveTab === "missing_tcms" ? "white" : "transparent",
                  cursor: "pointer",
                  borderBottom: comparisonActiveTab === "missing_tcms" ? "2px solid #007bff" : "2px solid transparent",
                  color: comparisonActiveTab === "missing_tcms" ? "#007bff" : "#666",
                  fontWeight: comparisonActiveTab === "missing_tcms" ? "600" : "normal",
                  fontSize: "14px"
                }}
              >
                Missing in TCMS ({jitaTcmsComparison.summary.missing_in_tcms_count})
              </button>
            </div>

            {/* Tab Content */}
            <div style={{ 
              flex: 1, 
              overflowY: "auto", 
              padding: "20px 24px" 
            }}>
              {/* Matched Tab */}
              {comparisonActiveTab === "matched" && (
                <div>
                  <p style={{ marginTop: 0, fontSize: "13px", color: "#666" }}>
                    Testcases present in both Jita run and TCMS registry
                  </p>
                  {jitaTcmsComparison.matched.length > 0 ? (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ 
                        width: "100%", 
                        borderCollapse: "collapse", 
                        fontSize: "12px",
                        border: "1px solid #dee2e6"
                      }}>
                        <thead>
                          <tr style={{ background: "#f8f9fa" }}>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", minWidth: "300px" }}>Testcase Name</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>Jita Status</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>TCMS Status</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "80px" }}>TCMS QI</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", width: "150px" }}>Test Area</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", width: "120px" }}>Owner</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>Status Match</th>
                          </tr>
                        </thead>
                        <tbody>
                          {jitaTcmsComparison.matched.slice(0, 500).map((item, idx) => (
                            <tr key={idx} style={{ background: idx % 2 === 0 ? "white" : "#f8f9fa" }}>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px", fontFamily: "monospace" }}>
                                {item.testcase_name}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: item.jita_status === "Succeeded" ? "#28a745" : item.jita_status === "Failed" ? "#dc3545" : "#666"
                              }}>
                                {item.jita_status}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: item.tcms_status === "Passed" ? "#28a745" : item.tcms_status === "Failed" ? "#dc3545" : "#666"
                              }}>
                                {item.tcms_status}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: qiColor(item.tcms_qi)
                              }}>
                                {item.tcms_qi != null ? `${item.tcms_qi.toFixed(1)}%` : "-"}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px" }}>
                                {item.test_area || "-"}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px" }}>
                                {item.owner || "-"}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", textAlign: "center" }}>
                                {item.status_match ? (
                                  <span style={{ color: "#28a745" }}>✓</span>
                                ) : (
                                  <span style={{ color: "#dc3545" }}>✗</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {jitaTcmsComparison.matched.length > 500 && (
                        <p style={{ fontSize: "12px", color: "#666", marginTop: "10px" }}>
                          Showing first 500 of {jitaTcmsComparison.matched.length} matched testcases
                        </p>
                      )}
                    </div>
                  ) : (
                    <p style={{ color: "#999", textAlign: "center", padding: "40px" }}>No matched testcases found</p>
                  )}
                </div>
              )}

              {/* Missing in Jita Tab */}
              {comparisonActiveTab === "missing_jita" && (
                <div>
                  <p style={{ marginTop: 0, fontSize: "13px", color: "#666" }}>
                    Testcases registered in TCMS but not triggered in Jita run
                  </p>
                  {jitaTcmsComparison.missing_in_jita.length > 0 ? (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ 
                        width: "100%", 
                        borderCollapse: "collapse", 
                        fontSize: "12px",
                        border: "1px solid #dee2e6"
                      }}>
                        <thead>
                          <tr style={{ background: "#f8f9fa" }}>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", minWidth: "300px" }}>Testcase Name</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>TCMS QI</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>TCMS Status</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", width: "150px" }}>Test Area</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>Last Run Date</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "100px" }}>Deprecated</th>
                          </tr>
                        </thead>
                        <tbody>
                          {jitaTcmsComparison.missing_in_jita.slice(0, 500).map((item, idx) => (
                            <tr key={idx} style={{ background: idx % 2 === 0 ? "white" : "#f8f9fa" }}>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px", fontFamily: "monospace" }}>
                                {item.testcase_name}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: qiColor(item.tcms_qi)
                              }}>
                                {item.tcms_qi != null ? `${item.tcms_qi.toFixed(1)}%` : "-"}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: item.tcms_status === "Passed" ? "#28a745" : item.tcms_status === "Failed" ? "#dc3545" : "#666"
                              }}>
                                {item.tcms_status}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px" }}>
                                {item.test_area || "-"}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", textAlign: "center", fontSize: "11px" }}>
                                {item.last_run_date || "-"}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", textAlign: "center" }}>
                                {item.deprecated ? (
                                  <span style={{ color: "#dc3545" }}>Yes</span>
                                ) : (
                                  <span style={{ color: "#28a745" }}>No</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {jitaTcmsComparison.missing_in_jita.length > 500 && (
                        <p style={{ fontSize: "12px", color: "#666", marginTop: "10px" }}>
                          Showing first 500 of {jitaTcmsComparison.missing_in_jita.length} testcases
                        </p>
                      )}
                    </div>
                  ) : (
                    <p style={{ color: "#999", textAlign: "center", padding: "40px" }}>All TCMS testcases are present in Jita run</p>
                  )}
                </div>
              )}

              {/* Missing in TCMS Tab */}
              {comparisonActiveTab === "missing_tcms" && (
                <div>
                  <p style={{ marginTop: 0, fontSize: "13px", color: "#666" }}>
                    Testcases triggered in Jita but not registered in TCMS
                  </p>
                  {jitaTcmsComparison.missing_in_tcms.length > 0 ? (
                    <div style={{ overflowX: "auto" }}>
                      <table style={{ 
                        width: "100%", 
                        borderCollapse: "collapse", 
                        fontSize: "12px",
                        border: "1px solid #dee2e6"
                      }}>
                        <thead>
                          <tr style={{ background: "#f8f9fa" }}>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", minWidth: "300px" }}>Testcase Name</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "center", width: "120px" }}>Jita Status</th>
                            <th style={{ padding: "10px", border: "1px solid #dee2e6", textAlign: "left", width: "200px" }}>Jita Task ID</th>
                          </tr>
                        </thead>
                        <tbody>
                          {jitaTcmsComparison.missing_in_tcms.slice(0, 500).map((item, idx) => (
                            <tr key={idx} style={{ background: idx % 2 === 0 ? "white" : "#f8f9fa" }}>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px", fontFamily: "monospace" }}>
                                {item.testcase_name}
                              </td>
                              <td style={{ 
                                padding: "8px", 
                                border: "1px solid #dee2e6", 
                                textAlign: "center",
                                color: item.jita_status === "Succeeded" ? "#28a745" : item.jita_status === "Failed" ? "#dc3545" : "#666"
                              }}>
                                {item.jita_status}
                              </td>
                              <td style={{ padding: "8px", border: "1px solid #dee2e6", fontSize: "11px", fontFamily: "monospace" }}>
                                {item.jita_task_id || "-"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      {jitaTcmsComparison.missing_in_tcms.length > 500 && (
                        <p style={{ fontSize: "12px", color: "#666", marginTop: "10px" }}>
                          Showing first 500 of {jitaTcmsComparison.missing_in_tcms.length} testcases
                        </p>
                      )}
                    </div>
                  ) : (
                    <p style={{ color: "#999", textAlign: "center", padding: "40px" }}>All Jita testcases are registered in TCMS</p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------
   Helpers
--------------------------------*/

function aggregateByBranch(runs, branchStartDates = {}) {
  const map = {};

  runs.forEach((run) => {
    // Handle different branch name variations for master branch
    let branch = run.branch;
    if (!branch || branch === "" || branch === null || branch === undefined) {
      branch = "unknown";
    } else {
      // Normalize branch name - handle case variations
      branch = branch.trim();
      // Check if it's a master branch variant
      if (branch.toLowerCase() === "master" || branch.toLowerCase() === "main") {
        branch = "master";
      }
    }

    if (!map[branch]) {
      map[branch] = {
        branch,
        succeeded: 0,
        failed: 0,
        skipped: 0,
        pending: 0,
        warning: 0,
        running: 0,
        killed: 0,
        statuses: new Set(),
        actualTasks: [],
        mergedTasks: [],
        startDate: branchStartDates[branch] || null  // Add start date from backend
      };
    }

    // Aggregate all test counts from backend
    const counts = run.test_counts || {};
    map[branch].succeeded += counts.Succeeded || counts.succeeded || 0;
    map[branch].failed += counts.Failed || counts.failed || 0;
    map[branch].skipped += counts.Skipped || counts.skipped || 0;
    map[branch].pending += counts.Pending || counts.pending || 0;
    map[branch].warning += counts.Warning || counts.warning || 0;
    map[branch].running += counts.Running || counts.running || 0;
    map[branch].killed += counts.Killed || counts.killed || 0;
    
    map[branch].statuses.add(run.status);

    map[branch].actualTasks.push(run.task_id);
    map[branch].mergedTasks.push(run.task_id);
  });

  return Object.values(map).map((b) => ({
    branch: b.branch,
    succeeded: b.succeeded,
    failed: b.failed,
    skipped: b.skipped,
    pending: b.pending,
    warning: b.warning,
    running: b.running,
    killed: b.killed,
    status: deriveStatus([...b.statuses]),
    actualTasks: b.actualTasks,
    mergedTasks: b.mergedTasks,
    startDate: b.startDate
  }));
}

function deriveStatus(statuses) {
  if (statuses.includes("testing")) return "Running";
  if (statuses.includes("pending")) return "Pending";
  return "Completed";
}

function renderTaskButton(taskIds, buttonName) {
  const ids = normalizeJitaTaskIdList(taskIds);
  if (!ids.length) return "-";

  const urls = buildJitaResultsUrls(ids);
  if (!urls.length) return "-";
  const isFullRegression = buttonName === "Regression_Run_Tasks";
  const dataAttrs = isFullRegression
    ? { "data-regression-run-tasks": "1", "data-task-ids": ids.join(",") }
    : {};
  const btnStyle = {
    display: "inline-block",
    padding: "6px 12px",
    background: "#007bff",
    color: "white",
    textDecoration: "none",
    borderRadius: "4px",
    fontSize: "13px",
  };

  if (urls.length === 1) {
    return (
      <a
        href={urls[0]}
        target="_blank"
        rel="noreferrer"
        className="task-btn"
        title={urls[0]}
        {...dataAttrs}
        style={btnStyle}
      >
        {buttonName}
      </a>
    );
  }

  return (
    <span
      {...dataAttrs}
      style={{ display: "inline-flex", flexDirection: "column", alignItems: "center", gap: "4px" }}
    >
      <span style={{ ...btnStyle, cursor: "default" }}>
        {buttonName} ({ids.length})
      </span>
      <span style={{ display: "flex", flexWrap: "wrap", gap: "4px", justifyContent: "center" }}>
        {urls.map((url, i) => (
          <a
            key={`${i}-${url.slice(-12)}`}
            href={url}
            target="_blank"
            rel="noreferrer"
            className="task-btn"
            title={`JITA part ${i + 1} of ${urls.length} (URL length limit)`}
            style={{ ...btnStyle, padding: "4px 8px", fontSize: "11px", background: "#2563eb" }}
          >
            JITA {i + 1}/{urls.length}
          </a>
        ))}
      </span>
    </span>
  );
}

