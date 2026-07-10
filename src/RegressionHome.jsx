import React, { useEffect, useState } from "react";
import api from "./api";
import { API_BASE_URL } from "./config";
import AiMarkdown from "./components/AiMarkdown";
import "./RegressionHome.css";

const API_URL = `${API_BASE_URL}/mcp/regression/home`;
const CONFIG_API = `${API_BASE_URL}/mcp/regression/config`;
const CONFIG_TAGS_API = `${API_BASE_URL}/mcp/regression/config/tags`;
const TCMS_OVERALL_QI_API = `${API_BASE_URL}/mcp/regression/tcms-overall-qi`;
const TEAM_CONFIG_API = `${API_BASE_URL}/mcp/regression/team-config`;
const DEFAULT_TAG = "cdp_master_full_reg";
const JITA_RESULTS_URL = "https://jita.eng.nutanix.com/results?task_ids=";
const JIRA_URL = "https://jira.nutanix.com/browse/";

// Load tag from localStorage or use default
const getStoredTag = () => {
  const stored = localStorage.getItem("regressionDashboardTag");
  return stored || DEFAULT_TAG;
};

// Load hidden branches from localStorage
const getStoredHiddenBranches = () => {
  const stored = localStorage.getItem("regressionDashboardHiddenBranches");
  return stored ? JSON.parse(stored) : [];
};

// Load advanced action options from localStorage
const getStoredAdvancedOptions = () => {
  const stored = localStorage.getItem("regressionDashboardAdvancedOptions");
  return stored ? JSON.parse(stored) : {
    triageCount: true, // Load by default
    triageAccuracy: false, // Triage Accuracy Analyzer
    qiSummaryReport: false,
    flakyTestInsights: false,
    aiRootCauseSummary: false,
    regressionRiskScore: false,
    bulkIssuesQiImpact: false,
    qiImpactedBulkIssue: false // QI Impacted Bulk issue - not loaded by default
  };
};

export default function RegressionHome() {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tag, setTag] = useState(getStoredTag());
  const [showConfigModal, setShowConfigModal] = useState(false);
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
  // Track task IDs as string to trigger useEffect when they change
  const [taskIdsKey, setTaskIdsKey] = useState(() => {
    const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
    return savedTaskIds ? savedTaskIds : null; // Store as string for comparison
  });
  const [hiddenBranches, setHiddenBranches] = useState(getStoredHiddenBranches()); // Branches to hide
  const [newBranchTagInput, setNewBranchTagInput] = useState("");
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [availableBranches, setAvailableBranches] = useState([]);
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

  // Deep Analysis tabs state
  const [activeTab, setActiveTab] = useState("home");
  const [deepAnalysisTabs, setDeepAnalysisTabs] = useState([]);
  const [deepAnalysisResults, setDeepAnalysisResults] = useState({});
  const [deepAnalysisLoading, setDeepAnalysisLoading] = useState({});
  const [deepAnalysisSessions, setDeepAnalysisSessions] = useState({});
  const [deepAnalysisFollowUp, setDeepAnalysisFollowUp] = useState({});
  const [deepAnalysisFollowUpLoading, setDeepAnalysisFollowUpLoading] = useState({});
  const [deepAnalysisHistory, setDeepAnalysisHistory] = useState({});

  // Parse JITA task link or comma-separated task IDs
  const parseTaskIds = (input) => {
    if (!input || !input.trim()) return null;
    
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
        console.log("Hidden branches:", hiddenBranches);
        
        // Filter out hidden branches
        const hiddenSet = new Set(hiddenBranches);
        const filtered = aggregated.filter(row => {
          const isHidden = hiddenSet.has(row.branch);
          if (isHidden) {
            console.log(`Branch "${row.branch}" is hidden, filtering out`);
          }
          return !isHidden;
        });
        console.log("After filtering hidden branches:", filtered);
        
        // If no rows after filtering, check if all were filtered out
        if (filtered.length === 0 && aggregated.length > 0) {
          console.warn("All branches were filtered out! Aggregated branches:", aggregated.map(r => r.branch));
        }
        
        setRows(filtered);
        
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
  }, [tag, hiddenBranches, inputMode, taskIdsKey, configLoaded]);

  // Load Triage Count automatically on page load and when tag/task_ids change
  useEffect(() => {
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    
    // Only load if we have valid parameters
    if (savedMode === "tag" && tag) {
      fetchTriageCount(tag, null);
    } else if (savedMode === "task_ids") {
      const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
      if (savedTaskIds) {
        try {
          const taskIds = JSON.parse(savedTaskIds);
          if (taskIds && taskIds.length > 0) {
            fetchTriageCount(null, taskIds.join(","));
          }
        } catch (e) {
          console.error("Error parsing saved task IDs:", e);
        }
      }
    }
  }, [tag, inputMode, taskIdsKey]); // Re-run when tag, inputMode, or taskIdsKey changes

  // Load Triage Accuracy Analyzer when enabled and config changes
  useEffect(() => {
    if (!advancedOptions.triageAccuracy) return;
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && tag) {
      fetchTriageAccuracy(tag, null);
    } else if (savedMode === "task_ids") {
      const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
      if (savedTaskIds) {
        try {
          const taskIds = JSON.parse(savedTaskIds);
          if (taskIds && taskIds.length > 0) {
            fetchTriageAccuracy(null, taskIds.join(","));
          }
        } catch (e) {
          console.error("Error parsing saved task IDs:", e);
        }
      }
    }
  }, [advancedOptions.triageAccuracy, tag, inputMode, taskIdsKey]);

  // Fetch JIRA details (status, issue type) for all tickets in owner_ticket_map
  const fetchOwnerJiraDetails = async () => {
    if (!triageCount || !triageCount.owner_ticket_map) return;
    const allTickets = new Set();
    Object.values(triageCount.owner_ticket_map).forEach(tickets => {
      Object.keys(tickets).forEach(t => allTickets.add(t));
    });
    if (allTickets.size === 0) return;
    setLoadingJiraDetails(true);
    try {
      const resp = await api.post(`${API_BASE_URL}/mcp/regression/jira-ticket-details`, {
        ticket_ids: Array.from(allTickets)
      }, { timeout: 120000 });
      if (resp.data.success && resp.data.details) {
        setOwnerJiraDetails(resp.data.details);
      }
    } catch (err) {
      console.error("Error fetching JIRA details:", err);
    } finally {
      setLoadingJiraDetails(false);
    }
  };

  // Auto-fetch JIRA details when owner_ticket_map becomes available
  useEffect(() => {
    if (!triageCount || !triageCount.owner_ticket_map) return;
    if (Object.keys(ownerJiraDetails).length > 0) return;
    fetchOwnerJiraDetails();
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
        
        // Update local state
        setTag(selectedTag || null);
        setConfigTagInput(selectedTag || "");
        localStorage.setItem("regressionDashboardTag", selectedTag || "");
        localStorage.setItem("regressionDashboardInputMode", "tag");
        localStorage.removeItem("regressionDashboardTaskIds");
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
        
        // Store task IDs and clear tag
        setTag(null);
        setDefaultTag(null);
        localStorage.removeItem("regressionDashboardTag");
        localStorage.setItem("regressionDashboardInputMode", "task_ids");
        const taskIdsString = JSON.stringify(taskIds);
        localStorage.setItem("regressionDashboardTaskIds", taskIdsString);
        
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
      setAvailableBranches([]);
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

  // Fetch branches from tag
  const fetchBranchesFromTag = async (tagName) => {
    if (!tagName.trim()) {
      alert("Tag name cannot be empty");
      return;
    }
    
    setLoadingBranches(true);
    try {
      const response = await api.get(`${API_BASE_URL}/mcp/regression/branches`, {
        params: { tag: tagName.trim() }
      });
      setAvailableBranches(response.data.branches || []);
    } catch (err) {
      console.error("Error fetching branches:", err);
      alert("Failed to fetch branches. Please check if the tag name is correct.");
      setAvailableBranches([]);
    } finally {
      setLoadingBranches(false);
    }
  };

  // Add new branch
  const handleAddNewBranch = (branchName) => {
    if (!branchName || !branchName.trim()) {
      alert("Please select a branch");
      return;
    }
    
    const branch = branchName.trim();
    
    // Remove from hidden branches if it was hidden
    setHiddenBranches(prev => {
      const updated = prev.filter(b => b !== branch);
      localStorage.setItem("regressionDashboardHiddenBranches", JSON.stringify(updated));
      return updated;
    });
    
    setNewBranchTagInput("");
    setAvailableBranches([]);
    
    // The table will automatically refresh due to useEffect dependency on hiddenBranches
    alert(`Branch "${branch}" will be shown in the table.`);
  };

  // Delete branch (hide it)
  const handleDeleteBranch = (branchName) => {
    if (window.confirm(`Are you sure you want to hide branch "${branchName}" from the table?`)) {
      setHiddenBranches(prev => {
        if (!prev.includes(branchName)) {
          const updated = [...prev, branchName];
          localStorage.setItem("regressionDashboardHiddenBranches", JSON.stringify(updated));
          return updated;
        }
        return prev;
      });
      alert(`Branch "${branchName}" has been hidden from the table.`);
    }
  };

  // Fetch Triage Accuracy Analyzer - supports both tag and task_ids; reload=true invalidates cache
  const fetchTriageAccuracy = async (tagToUse = null, taskIdsToUse = null, reload = false) => {
    setLoadingTriageAccuracy(true);
    try {
      const params = {};
      if (tagToUse || tag) {
        params.tag = tagToUse || tag;
      } else if (taskIdsToUse) {
        params.task_ids = Array.isArray(taskIdsToUse) ? taskIdsToUse.join(",") : taskIdsToUse;
      } else {
        const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
        if (savedMode === "tag" && tag) {
          params.tag = tag;
        } else if (savedMode === "task_ids") {
          const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
          if (savedTaskIds) {
            params.task_ids = JSON.parse(savedTaskIds).join(",");
          } else {
            setLoadingTriageAccuracy(false);
            return;
          }
        } else {
          setLoadingTriageAccuracy(false);
          return;
        }
      }
      if (reload) {
        params.reload = "true";
        params._t = Date.now(); // Cache-bust to avoid any HTTP caching
      }
      const response = await api.get(`${API_BASE_URL}/mcp/regression/triage-accuracy`, {
        params,
        timeout: 900000, // 15 minutes - Triage Genie lookups can be slow for large runs
        headers: reload ? { "Cache-Control": "no-cache", "Pragma": "no-cache" } : {}
      });
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

  // Reload Triage Accuracy data (invalidate cache + refetch from JITA/Triage Genie)
  // Uses same param resolution as initial load (useEffect) to ensure correct tag/task_ids
  const handleReloadTriageAccuracy = () => {
    const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
    if (savedMode === "tag" && (tag || defaultTag)) {
      const effectiveTag = tag || defaultTag;
      fetchTriageAccuracy(effectiveTag, null, true);
    } else if (savedMode === "task_ids") {
      const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
      if (savedTaskIds) {
        try {
          const taskIds = JSON.parse(savedTaskIds);
          if (taskIds && taskIds.length > 0) {
            fetchTriageAccuracy(null, taskIds.join(","), true);
          } else {
            alert("No task IDs configured. Configure JITA Task IDs in Configuration first.");
          }
        } catch (e) {
          alert("Invalid task IDs in config.");
        }
      } else {
        alert("No task IDs configured. Configure JITA Task IDs in Configuration first.");
      }
    } else {
      alert("No tag or task IDs configured. Configure in Configuration first.");
    }
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

  // Fetch Triage Count - supports both tag and task_ids
  // By default, exclude bulk issues QI calculation for faster loading
  const fetchTriageCount = async (tagToUse = null, taskIdsToUse = null, includeBulkQi = false) => {
    setLoadingTriage(true);
    try {
      const params = {};
      if (tagToUse || tag) {
        params.tag = tagToUse || tag;
      } else if (taskIdsToUse) {
        params.task_ids = Array.isArray(taskIdsToUse) ? taskIdsToUse.join(",") : taskIdsToUse;
      } else {
        // Try to get from localStorage
        const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
        if (savedMode === "tag" && tag) {
          params.tag = tag;
        } else if (savedMode === "task_ids") {
          const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
          if (savedTaskIds) {
            params.task_ids = JSON.parse(savedTaskIds).join(",");
          } else {
            setLoadingTriage(false);
            return;
          }
        } else {
          setLoadingTriage(false);
          return;
        }
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
      const params = {};
      const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
      
      if (savedMode === "tag" && tag) {
        params.tag = tag;
      } else if (savedMode === "task_ids") {
        const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
        if (savedTaskIds) {
          params.task_ids = JSON.parse(savedTaskIds).join(",");
        } else {
          setLoadingBulkQi(false);
          return;
        }
      } else {
        setLoadingBulkQi(false);
        return;
      }
      
      // Request bulk QI calculation
      params.include_bulk_qi = "true";
      
      const response = await api.get(`${API_BASE_URL}/mcp/regression/triage-count`, {
        params,
        timeout: 300000 // 5 minutes timeout for QI calculation
      });
      
      // Update triage count with bulk issues QI data
      if (response.data.bulk_issues_with_qi) {
        setTriageCount(prev => ({
          ...prev,
          bulk_issues_with_qi: response.data.bulk_issues_with_qi
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
      let resp;
      if (sessionId) {
        resp = await api.post(`${API_BASE_URL}/mcp/regression/cursor-ai/follow-up`, {
          session_id: sessionId,
          question,
        });
      } else {
        const tab = deepAnalysisTabs.find(t => t.ticket === ticket);
        const prevResult = deepAnalysisResults[ticket] || {};
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
      setDeepAnalysisHistory(prev => ({
        ...prev,
        [ticket]: [...(prev[ticket] || []), { role: "error", text: err.message || "Follow-up failed" }]
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
      const params = {};
      if (tagToUse || tag) {
        params.tag = tagToUse || tag;
      } else if (taskIdsToUse) {
        params.task_ids = Array.isArray(taskIdsToUse) ? taskIdsToUse.join(",") : taskIdsToUse;
      } else {
        // Try to get from localStorage
        const savedMode = localStorage.getItem("regressionDashboardInputMode") || "tag";
        if (savedMode === "tag" && tag) {
          params.tag = tag;
        } else if (savedMode === "task_ids") {
          const savedTaskIds = localStorage.getItem("regressionDashboardTaskIds");
          if (savedTaskIds) {
            params.task_ids = JSON.parse(savedTaskIds).join(",");
          } else {
            setLoadingQiSummary(false);
            return;
          }
        } else {
          setLoadingQiSummary(false);
          return;
        }
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
                    placeholder="Ask a follow-up question about this analysis..."
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
              {defaultTag && (
                <div style={{ marginTop: "10px" }}>
                  <button
                    type="button"
                    onClick={() => fetchBranchesFromTag(defaultTag)}
                    disabled={loadingBranches}
                    style={{
                      padding: "6px 12px",
                      fontSize: "12px",
                      background: loadingBranches ? "#ccc" : "#17a2b8",
                      color: "white",
                      border: "none",
                      borderRadius: "4px",
                      cursor: loadingBranches ? "not-allowed" : "pointer"
                    }}
                  >
                    {loadingBranches ? "Loading..." : "Fetch Branches"}
                  </button>
                  {availableBranches.length > 0 && (
                    <select
                      onChange={(e) => {
                        if (e.target.value) handleAddNewBranch(e.target.value);
                      }}
                      style={{
                        marginLeft: "10px",
                        padding: "6px",
                        fontSize: "13px",
                        border: "1px solid #ddd",
                        borderRadius: "4px"
                      }}
                    >
                      <option value="">-- Select branch to show --</option>
                      {availableBranches.map((b) => (
                        <option key={b} value={b}>{b}</option>
                      ))}
                    </select>
                  )}
                </div>
              )}
            </div>
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontWeight: "bold" }}>
                2. Added Tag List:
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
                  {loadingBranches ? "Adding..." : "Fetch & Add"}
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
                You can enter either comma-separated task IDs or paste a JITA results link. The link will be automatically parsed to extract task IDs.
              </small>
            </div>
            )}

            {/* Delete Branch */}
            <div style={{ marginBottom: "20px" }}>
              <label style={{ display: "block", marginBottom: "5px", fontWeight: "bold" }}>
                {modalInputMode === "tag" ? "3" : "2"}. Hide Branch:
              </label>
              {rows.length > 0 ? (
                <select
                  onChange={(e) => {
                    if (e.target.value) {
                      handleDeleteBranch(e.target.value);
                      e.target.value = ""; // Reset selection
                    }
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
                  <option value="">-- Select a branch to hide --</option>
                  {rows.map((row) => (
                    <option key={row.branch} value={row.branch}>
                      {row.branch}
                    </option>
                  ))}
                </select>
              ) : (
                <div style={{ color: "#666", fontSize: "13px" }}>No branches available</div>
              )}
            </div>

            {/* Advanced Options */}
            <div style={{ marginBottom: "20px", paddingTop: "20px", borderTop: "1px solid #ddd" }}>
              <label style={{ display: "block", marginBottom: "15px", fontWeight: "bold", fontSize: "16px" }}>
                {modalInputMode === "tag" ? "4" : "3"}. Advanced Options:
              </label>
              
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
                  <td>
                    {renderTaskButton(row.actualTasks, "Regression_Run_Tasks")}
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle", fontSize: "12px" }}>
                    <div style={{ marginBottom: "10px" }}>
                      <div style={{ fontWeight: "bold", marginBottom: "3px" }}>SUCCEEDED</div>
                    <div style={{ color: "#28a745" }}>{row.succeeded || 0}</div>
                    </div>
                    <div>
                      <div style={{ fontWeight: "bold", marginBottom: "3px" }}>FAILED</div>
                      <div style={{ color: "#dc3545" }}>{row.failed || 0}</div>
                    </div>
                  </td>
                  <td style={{ textAlign: "center", verticalAlign: "middle" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", fontSize: "12px" }}>
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
                      const milestone = (() => {
                        const b = row.branch?.toLowerCase();
                        if (b === "master" || b === "main") return "master";
                        const m = row.branch?.match(/(\d+\.\d+(?:\.\d+)?)/);
                        return m ? m[1] : row.branch;
                      })();
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
                      const milestone = (() => {
                        const b = row.branch?.toLowerCase();
                        if (b === "master" || b === "main") return "master";
                        const m = row.branch?.match(/(\d+\.\d+(?:\.\d+)?)/);
                        return m ? m[1] : row.branch;
                      })();
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
          <h3 style={{ marginTop: 0, marginBottom: "15px", color: "#333" }}>Triage Count by Regression Owner</h3>
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
                  {/* Display Triage Summary */}
                  {triageCount.triage_summary && (
                    <div style={{ marginBottom: "20px" }}>
                      <h4 style={{ marginBottom: "10px" }}>Triage Summary:</h4>
                      {(() => {
                        const owners = Object.values(triageCount.triage_summary || {});
                        const sum = (k) => owners.reduce((acc, s) => acc + (Number(s?.[k]) || 0), 0);
                        const totalFailed = sum("Total Failed");
                        const triaged = sum("Triaged");
                        const untriaged = sum("UnTriaged");
                        const bulk = sum("Bulk Issues");
                        const pending = Number(triageCount.pending_tests) || 0;
                        const triagedPct = totalFailed ? Math.round((triaged / totalFailed) * 100) : 0;
                        const spark = (pts) => {
                          const max = Math.max(...pts, 1);
                          const min = Math.min(...pts, 0);
                          const range = max - min || 1;
                          const coords = pts.map((p, i) => {
                            const x = (i / (pts.length - 1)) * 100;
                            const y = 24 - ((p - min) / range) * 22 - 1;
                            return `${x.toFixed(1)},${y.toFixed(1)}`;
                          });
                          return (
                            <svg className="rh-stat-spark" viewBox="0 0 100 26" preserveAspectRatio="none">
                              <polyline points={coords.join(" ")} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          );
                        };
                        const cards = [
                          { label: "Total Failed/Warning", value: totalFailed, icon: "\u26A0", bg: "linear-gradient(135deg, #3a6ea5 0%, #2b5278 100%)", pts: [3, 5, 4, 6, 5, 7, 6] },
                          { label: "Triaged", value: triaged, sub: `${triagedPct}% of failures`, icon: "\u2713", bg: "linear-gradient(135deg, #27ae60 0%, #1e8449 100%)", pts: [2, 3, 5, 4, 6, 7, 8] },
                          { label: "UnTriaged", value: untriaged, icon: "\u29D7", bg: "linear-gradient(135deg, #e74c3c 0%, #c0392b 100%)", pts: [7, 6, 6, 4, 5, 3, 2] },
                          { label: "Bulk Issues", value: bulk, icon: "\u2637", bg: "linear-gradient(135deg, #f5a623 0%, #e8890c 100%)", pts: [4, 5, 4, 5, 6, 5, 6] },
                          { label: "Pending/Running", value: pending, icon: "\u27F3", bg: "linear-gradient(135deg, #4aa3df 0%, #2e86c1 100%)", pts: [5, 4, 5, 6, 4, 5, 4] },
                        ];
                        return (
                          <div className="rh-stat-cards">
                            {cards.map((c) => (
                              <div key={c.label} className="rh-stat-card" style={{ background: c.bg }}>
                                <div className="rh-stat-icon">{c.icon}</div>
                                <div className="rh-stat-label">{c.label}</div>
                                {spark(c.pts)}
                                <div className="rh-stat-value">{c.value}</div>
                                {c.sub && <div className="rh-stat-sub">{c.sub}</div>}
                              </div>
                            ))}
                          </div>
                        );
                      })()}
                      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "15px" }}>
                        <thead>
                          <tr style={{ background: "#e9ecef" }}>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Owner</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Total Failed</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Triaged</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>UnTriaged</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(triageCount.triage_summary).map(([owner, stats]) => (
                            <tr key={owner}>
                              <td style={{ padding: "8px", border: "1px solid #ddd" }}>{owner}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{stats["Total Failed"]}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center", color: "#28a745" }}>{stats["Triaged"]}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center", color: "#dc3545" }}>{stats["UnTriaged"]}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

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
                  
                  {/* Display Pending Tests */}
                  {triageCount.pending_tests !== undefined && (
                    <div style={{ marginBottom: "10px", color: "#17a2b8" }}>
                      <strong>Pending/Running Tests:</strong> {triageCount.pending_tests}
                    </div>
                  )}

                  {/* Display Bulk Issues Count */}
                  {triageCount.bulk_issues_count !== undefined && (
                    <div style={{ marginBottom: "10px", color: "#ffc107" }}>
                      <strong>Total Bulk Issues (tickets with &gt;5 testcases):</strong> {triageCount.bulk_issues_count}
                    </div>
                  )}
                  
                  {/* Display Owner Ticket Map as Table */}
                  {triageCount.owner_ticket_map && Object.keys(triageCount.owner_ticket_map).length > 0 && (
                    <div style={{ marginTop: "20px" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "10px" }}>
                        <h4 style={{ margin: 0 }}>
                          Owner-wise Jira Ticket Breakdown:
                          {loadingJiraDetails && (
                            <span style={{ fontSize: "11px", color: "#6c757d", fontWeight: "normal", marginLeft: "10px" }}>
                              Loading JIRA details...
                            </span>
                          )}
                        </h4>
                        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                          {(!triageCount.bulk_issues_with_qi || Object.keys(triageCount.bulk_issues_with_qi).length === 0) && (
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
                        {Object.entries(triageCount.owner_ticket_map).map(([owner, tickets]) => {
                          const ticketEntries = Object.entries(tickets);
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
                                <span>{owner}</span>
                                <span className="rh-owner-count">{ticketEntries.length} ticket{ticketEntries.length !== 1 ? "s" : ""}</span>
                              </div>
                              <ul className="rh-owner-tickets">
                                {ticketEntries.map(([ticket, count]) => {
                                  const jiraInfo = ownerJiraDetails[ticket];
                                  const qiData = triageCount.bulk_issues_with_qi?.[ticket];
                                  return (
                                    <li key={ticket}>
                                      {jiraInfo ? (
                                        <span className="rh-ticket-status" style={statusStyle(jiraInfo.status)} title={jiraInfo.issue_type ? `Type: ${jiraInfo.issue_type}` : undefined}>
                                          {jiraInfo.status}
                                        </span>
                                      ) : (
                                        <span className="rh-ticket-status" style={{ background: "#f3f4f6", color: "#9ca3af" }}>—</span>
                                      )}
                                      <a className="rh-ticket-link" href={`${JIRA_URL}${ticket}`} target="_blank" rel="noreferrer">
                                        {ticket}
                                      </a>
                                      {qiData && (
                                        <span className="rh-ticket-count" title="QI Impact">{qiData.overall_qi_impact.toFixed(1)}% QI</span>
                                      )}
                                      <span className="rh-ticket-count">{count} tc</span>
                                    </li>
                                  );
                                })}
                              </ul>
                            </div>
                          );
                        })}
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
                  )}
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
        <div style={{ marginTop: "40px", padding: "20px", background: "#f8f9fa", borderRadius: "8px" }}>
          <h3 style={{ marginTop: 0, marginBottom: "15px", color: "#333" }}>Triage Accuracy Analyzer</h3>
          {loadingTriageAccuracy ? (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Loading triage accuracy... This may take several minutes as Triage Genie tickets are fetched for each testcase...
            </div>
          ) : triageAccuracyData ? (
            <div style={{ fontSize: "14px" }}>
              {triageAccuracyData.error ? (
                <div style={{ color: "#dc3545" }}>{triageAccuracyData.error}</div>
              ) : (
                <div>
                  {/* Triage Summary */}
                  {triageAccuracyData.triage_summary && (
                    <div style={{ marginBottom: "20px" }}>
                      <h4 style={{ marginBottom: "10px" }}>Triage Summary:</h4>
                      {/* Summary message above table */}
                      <p style={{ marginBottom: "12px", lineHeight: "1.6", color: "#333" }}>
                        Total failed/warning testcases: <strong>{triageAccuracyData?.triage_summary?.total_failed_warning_count ?? triageAccuracyData?.testcases?.length ?? 0}</strong>.
                        Triage Completed: <strong>{(triageAccuracyData?.triage_summary?.triage_completed_percent ?? 0)}%</strong> ({(triageAccuracyData?.triage_summary?.triaged_count ?? 0)} testcases).
                        Total Triage Genie Tagged: <strong>{(triageAccuracyData?.triage_summary?.total_triage_genie_percent ?? 0)}%</strong> ({(triageAccuracyData?.triage_summary?.total_triage_genie_count ?? 0)} testcases).
                      </p>
                      {/* Table with Metric | Count | Percentage */}
                      <table style={{ width: "100%", maxWidth: "450px", borderCollapse: "collapse", marginBottom: "15px" }}>
                        <thead>
                          <tr style={{ background: "#e9ecef" }}>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Metric</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Count</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Percentage</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>Triage Genie Ticket %(based on completed triaged)</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.triage_genie_count ?? 0}</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.triage_genie_percent ?? 0}%</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>Matched %</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.matched_count ?? 0}</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.matched_percent ?? 0}%</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>Unmatched %</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.unmatched_count ?? 0}</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{triageAccuracyData?.triage_summary?.unmatched_percent ?? 0}%</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  )}
                  {/* Reload Data and Download Excel Report Buttons */}
                  <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
                    <button
                      onClick={handleReloadTriageAccuracy}
                      disabled={loadingTriageAccuracy}
                      style={{
                        padding: "8px 16px",
                        background: loadingTriageAccuracy ? "#ccc" : "#17a2b8",
                        color: "white",
                        border: "none",
                        borderRadius: "4px",
                        cursor: loadingTriageAccuracy ? "not-allowed" : "pointer",
                        fontSize: "14px",
                        fontWeight: "500"
                      }}
                    >
                      {loadingTriageAccuracy ? "Reloading..." : "Reload Data"}
                    </button>
                    <button
                      onClick={handleDownloadTriageAccuracyExcel}
                      style={{
                        padding: "8px 16px",
                        background: "#28a745",
                        color: "white",
                        border: "none",
                        borderRadius: "4px",
                        cursor: "pointer",
                        fontSize: "14px",
                        fontWeight: "500"
                      }}
                    >
                      Download Excel Report
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Enable this option and click "Save" in Advanced Action to load triage accuracy data.
            </div>
          )}
        </div>
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
        <div style={{ marginTop: "40px", padding: "20px", background: "#f8f9fa", borderRadius: "8px" }}>
          <h3 style={{ marginTop: 0, marginBottom: "15px", color: "#333" }}>QI Summary Report</h3>
          {loadingQiSummary ? (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Loading QI Summary Report... This may take a minute as the backend processes data...
            </div>
          ) : qiSummaryReport ? (
            <div style={{ fontSize: "14px" }}>
              {qiSummaryReport.error ? (
                <div style={{ color: "#dc3545" }}>{qiSummaryReport.error}</div>
              ) : (
                <div>
                  {/* Display Status Summary */}
                  {qiSummaryReport.status_summary && (
                    <div style={{ marginBottom: "20px" }}>
                      <h4 style={{ marginBottom: "10px" }}>Status Summary:</h4>
                      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "15px" }}>
                        <tbody>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Total Tasks:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>{qiSummaryReport.total_tasks}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Testing:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#6f42c1" }}>{qiSummaryReport.status_summary.testing}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Completed:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#28a745" }}>{qiSummaryReport.status_summary.completed}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Pending:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#17a2b8" }}>{qiSummaryReport.status_summary.pending}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Failed:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#dc3545" }}>{qiSummaryReport.status_summary.failed}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  )}
                  
                  {/* Display Test Summary */}
                  {qiSummaryReport.test_summary && (
                    <div style={{ marginBottom: "20px" }}>
                      <h4 style={{ marginBottom: "10px" }}>Test Summary:</h4>
                      <table style={{ width: "100%", borderCollapse: "collapse", marginBottom: "15px" }}>
                        <tbody>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Total:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd" }}>{qiSummaryReport.test_summary.total}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Succeeded:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#28a745" }}>{qiSummaryReport.test_summary.succeeded}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Failed:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#dc3545" }}>{qiSummaryReport.test_summary.failed}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Pending:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#17a2b8" }}>{qiSummaryReport.test_summary.pending}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Warning:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#fd7e14" }}>{qiSummaryReport.test_summary.warning}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Running:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#6f42c1" }}>{qiSummaryReport.test_summary.running}</td>
                          </tr>
                          <tr>
                            <td style={{ padding: "8px", border: "1px solid #ddd", fontWeight: "bold" }}>Skipped:</td>
                            <td style={{ padding: "8px", border: "1px solid #ddd", color: "#ffc107" }}>{qiSummaryReport.test_summary.skipped}</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  )}
                  
                  {/* Display Branch Summary */}
                  {qiSummaryReport.branch_summary && Object.keys(qiSummaryReport.branch_summary).length > 0 && (
                    <div style={{ marginTop: "20px" }}>
                      <h4 style={{ marginBottom: "10px" }}>Branch Summary:</h4>
                      <table style={{ width: "100%", borderCollapse: "collapse" }}>
                        <thead>
                          <tr style={{ background: "#e9ecef" }}>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "left" }}>Branch</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Total Tasks</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Total Tests</th>
                            <th style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>Failed Tests</th>
                          </tr>
                        </thead>
                        <tbody>
                          {Object.entries(qiSummaryReport.branch_summary).map(([branch, stats]) => (
                            <tr key={branch}>
                              <td style={{ padding: "8px", border: "1px solid #ddd" }}>{branch}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{stats.total_tasks}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center" }}>{stats.total_tests}</td>
                              <td style={{ padding: "8px", border: "1px solid #ddd", textAlign: "center", color: "#dc3545" }}>{stats.failed_tests}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>
          ) : (
            <div style={{ color: "#666", fontStyle: "italic" }}>
              Click "Save" in Advanced Action to load QI Summary Report data.
            </div>
          )}
        </div>
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
                    <div style={{ marginTop: "8px" }}>
                      <a
                        href={`https://jira.nutanix.com/issues/?jql=issuekey%20in%20(${tcmsDetailModal.data.unique_tickets.join("%2C")})`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ padding: "4px 10px", fontSize: "12px", background: "#007bff", color: "white", borderRadius: "4px", textDecoration: "none" }}
                      >
                        View All in JIRA
                      </a>
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
  if (!taskIds || taskIds.length === 0) return "-";
  
  const taskIdsString = taskIds.join(",");
  const url = `${JITA_RESULTS_URL}${taskIdsString}&active_tab=1&merge_tests=true`;
  
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer"
      className="task-btn"
      style={{
        display: "inline-block",
        padding: "6px 12px",
        background: "#007bff",
        color: "white",
        textDecoration: "none",
        borderRadius: "4px",
        fontSize: "13px"
      }}
    >
      {buttonName}
    </a>
  );
}

