import React, { useState, useEffect, useRef, useMemo } from "react";
import api from "../api";
import "./Handover.css";

// Relative paths: the shared `api` axios instance (src/api.js) already prepends
// API_BASE_URL and attaches the JWT, matching the rest of the dashboard.
const JITA_ANALYSIS_API = "/mcp/regression/jita-analysis";
const CREATE_LST_CR_API = "/mcp/regression/create-lst-cr";
const VALIDATE_LST_API = "/mcp/regression/validate-lst";
const CHECK_LST_TESTCASES_API = "/mcp/regression/check-lst-testcases";
const DEPRECATE_LST_CR_API = "/mcp/regression/deprecate-lst-cr";
const HANDOVER_RECORD_API = "/mcp/regression/handover-record";
const HANDOVER_RECORD_DELETE_API = "/mcp/regression/handover-record-delete";
const DEPRECATION_SEARCH_API = "/mcp/regression/deprecation-search";
const JIRA_VALIDATE_API = "/mcp/regression/validate-jira-ticket";
const SEARCH_LST_FILE_API = "/mcp/regression/search-lst-file";
const SUGGEST_LST_FILE_API = "/mcp/regression/suggest-lst-file";
const SEARCH_REVIEWERS_API = "/mcp/regression/search-reviewers";
const SEARCH_BRANCHES_API = "/mcp/regression/search-branches";
const JIRA_URL = "https://jira.nutanix.com/browse/";

const btnBase = { fontSize: "13px", fontWeight: "500", border: "none", borderRadius: "8px", cursor: "pointer", transition: "all 0.15s ease", boxSizing: "border-box" };
const btnPrimary = { ...btnBase, padding: "10px 20px", background: "#059669", color: "white", boxShadow: "0 1px 2px rgba(0,0,0,0.05)" };
const btnPrimaryDisabled = { ...btnPrimary, background: "#94a3b8", cursor: "not-allowed", boxShadow: "none" };
const btnSecondary = { ...btnBase, padding: "10px 20px", background: "#0d9488", color: "white", boxShadow: "0 1px 2px rgba(0,0,0,0.05)" };
const btnTertiary = { ...btnBase, padding: "9px 18px", background: "#2563eb", color: "white", boxShadow: "0 1px 2px rgba(0,0,0,0.05)" };
const btnTertiaryDisabled = { ...btnTertiary, background: "#94a3b8", cursor: "not-allowed", boxShadow: "none" };
const btnValidate = { ...btnBase, padding: "9px 18px", background: "#0891b2", color: "white", boxShadow: "0 1px 2px rgba(0,0,0,0.05)" };
const btnValidateDisabled = { ...btnValidate, background: "#94a3b8", cursor: "not-allowed", boxShadow: "none" };

function formatByWhom(s) {
  if (s == null || s === "") return "-";
  const str = String(s).trim();
  if (!str) return "-";
  const at = str.indexOf("@");
  if (at === -1) return str;
  const beforeAt = str.slice(0, at).trim().replace(/\./g, " ");
  return beforeAt || str;
}

function getDeprecationRecordKey(r) {
  return `${(r.test_name || "").trim()}\0${r.handover_date || ""}\0${(r.lst_file || "").trim()}`;
}

function ReviewerAutocomplete({ value, onChange, placeholder, disabled, style }) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const debounceRef = useRef(null);
  const containerRef = useRef(null);
  const selectedEmails = useMemo(
    () => (value || "").split(",").map((e) => e.trim()).filter(Boolean),
    [value]
  );
  const selectedEmailsKey = useMemo(() => selectedEmails.join("|"), [selectedEmails]);
  const addReviewer = (emailOrUsername, name) => {
    const id = (emailOrUsername || "").trim();
    if (!id || selectedEmails.includes(id)) return;
    const next = [...selectedEmails, id];
    onChange(next.join(", "));
    setQuery("");
    setSuggestions([]);
    setShowDropdown(false);
  };
  const tryAddManualEmail = () => {
    const trimmed = query.trim();
    if (trimmed && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed) && !selectedEmails.includes(trimmed)) {
      addReviewer(trimmed);
    }
  };
  const removeReviewer = (email) => {
    onChange(selectedEmails.filter((e) => e !== email).join(", "));
  };
  useEffect(() => {
    if (!query || query.length < 2) {
      setSuggestions([]);
      setShowDropdown(false);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setLoading(true);
      setShowDropdown(true);
      setSearchError(null);
      api.get(SEARCH_REVIEWERS_API, { params: { q: query } })
        .then((res) => {
          const raw = res.data?.results || [];
          const results = raw.filter((r) => {
            const id = (r.email || r.username || "").trim();
            return id && (r.name || r.username) && !selectedEmails.includes(id);
          });
          setSuggestions(results);
          setSearchError(res.data?.error || null);
        })
        .catch((err) => {
          setSuggestions([]);
          const msg = err.response?.data?.error || err.message || "Could not fetch reviewers.";
          const hint = err.code === "ERR_NETWORK" || err.message === "Network Error"
            ? " Ensure backend is running on port 5001."
            : "";
          setSearchError(msg + hint);
        })
        .finally(() => { setLoading(false); });
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, value, selectedEmails, selectedEmailsKey]);
  useEffect(() => {
    const h = (e) => { if (containerRef.current && !containerRef.current.contains(e.target)) setShowDropdown(false); };
    document.addEventListener("click", h);
    return () => document.removeEventListener("click", h);
  }, []);
  return (
    <div ref={containerRef} style={{ position: "relative", ...style }}>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginBottom: "6px" }}>
        {selectedEmails.map((email) => (
          <span key={email} className="ho-chip" style={{ display: "inline-flex", alignItems: "center", gap: "4px", padding: "4px 10px", background: "#e0f2fe", borderRadius: "999px", fontSize: "12px", color: "#0c4a6e", fontWeight: 500 }}>
            {email}
            {!disabled && <button type="button" onClick={() => removeReviewer(email)} style={{ background: "none", border: "none", cursor: "pointer", padding: "0 2px", fontSize: "14px", lineHeight: 1, color: "#0369a1" }}>×</button>}
          </span>
        ))}
      </div>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => query.length >= 2 && setShowDropdown(true)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); tryAddManualEmail(); } }}
        placeholder={placeholder || "Type name (e.g. john) to search, or paste email and press Enter"}
        disabled={disabled}
        style={{ padding: "8px 12px", fontSize: "13px", width: "100%", maxWidth: "400px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box", backgroundColor: disabled ? "#f3f4f6" : "white", opacity: disabled ? 0.7 : 1 }}
      />
      {showDropdown && query.length >= 2 && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, maxWidth: "400px", maxHeight: "200px", overflowY: "auto", background: "white", border: "1px solid #d1d5db", borderRadius: "4px", boxShadow: "0 4px 6px rgba(0,0,0,0.1)", zIndex: 1000, marginTop: "2px" }}>
          {loading ? (
            <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>Searching...</div>
          ) : suggestions.length === 0 ? (
            <div style={{ padding: "8px 12px", fontSize: "13px", color: searchError ? "#dc2626" : "#64748b" }}>
              {searchError || "No reviewers found. Try a different name or add email manually."}
            </div>
          ) : (
            suggestions.map((r, i) => (
              <div key={r.email || r.username || i} onClick={() => addReviewer(r.email || r.username, r.name)} style={{ padding: "8px 12px", fontSize: "13px", cursor: "pointer", borderBottom: i < suggestions.length - 1 ? "1px solid #f1f5f9" : "none" }} onMouseEnter={(e) => { e.currentTarget.style.background = "#f1f5f9"; }} onMouseLeave={(e) => { e.currentTarget.style.background = "white"; }}>
                <strong>{r.name || r.username || "-"}</strong> {(r.email || r.username) && <span style={{ color: "#64748b" }}>({r.email || r.username})</span>}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function formatDateIST(isoDateStr) {
  if (!isoDateStr) return "-";
  try {
    // Backend stores dates in UTC without timezone indicator (e.g., "2026-01-30T06:14:00.000000")
    // We need to explicitly treat it as UTC by appending 'Z' if it doesn't have a timezone
    let dateStr = isoDateStr.trim();
    // Check if it already has timezone info (Z, +, or - after the time part)
    const hasTimezone = dateStr.endsWith('Z') || dateStr.match(/[+-]\d{2}:\d{2}$/);
    if (!hasTimezone && dateStr.includes('T')) {
      // ISO format without timezone - treat as UTC
      dateStr = dateStr + 'Z';
    }
    const d = new Date(dateStr);
    if (Number.isNaN(d.getTime())) return "-";
    // Format as "30 Jan, 11:44 AM" in IST (UTC+5:30)
    const options = {
      timeZone: "Asia/Kolkata",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: true
    };
    return d.toLocaleString("en-IN", options);
  } catch {
    return "-";
  }
}

export default function Handover({ userInfo }) {
  const [handoverJitaUrls, setHandoverJitaUrls] = useState([""]);
  const [handoverAnalysis, setHandoverAnalysis] = useState(null);
  const [loadingHandover, setLoadingHandover] = useState(false);
  const [handoverCreateLstBranch, setHandoverCreateLstBranch] = useState("");
  const [handoverBranchSuggestions, setHandoverBranchSuggestions] = useState([]);
  const [handoverBranchLoading, setHandoverBranchLoading] = useState(false);
  const [handoverShowBranchDropdown, setHandoverShowBranchDropdown] = useState(false);
  const [handoverCreateLstFile, setHandoverCreateLstFile] = useState("");
  const [handoverCreateLstFiles, setHandoverCreateLstFiles] = useState([]);
  const [handoverLstSuggestion, setHandoverLstSuggestion] = useState(null);
  const [handoverSuggestingLst, setHandoverSuggestingLst] = useState(false);
  const [handoverCommitMessage, setHandoverCommitMessage] = useState("");
  const [handoverCreateLstLoading, setHandoverCreateLstLoading] = useState(false);
  const [handoverManualLstInstructions, setHandoverManualLstInstructions] = useState(null);
  const [handoverCrResult, setHandoverCrResult] = useState(null);
  const [handoverValidation, setHandoverValidation] = useState(null);
  const [handoverValidating, setHandoverValidating] = useState(false);
  const [handoverOverrideSave, setHandoverOverrideSave] = useState(false);
  const [handoverTicketsExtra, setHandoverTicketsExtra] = useState("");
  const [handoverReviewers, setHandoverReviewers] = useState("");
  const [handoverCrPreviewOpen, setHandoverCrPreviewOpen] = useState(false);
  const [handoverCrSubject, setHandoverCrSubject] = useState("Testcase Handover");
  const [handoverCrDescription, setHandoverCrDescription] = useState("");
  const [handoverTestTickets, setHandoverTestTickets] = useState({});
  const [handoverBugTypeMap, setHandoverBugTypeMap] = useState({}); // Hidden state for bug type logic
  const [handoverJiraTicketValidation, setHandoverJiraTicketValidation] = useState({});
  const [handoverJiraValidating, setHandoverJiraValidating] = useState(false);
  // eslint-disable-next-line no-unused-vars
  const [handoverJiraOverride, setHandoverJiraOverride] = useState(false);
  const [handoverJiraSkippedMessage, setHandoverJiraSkippedMessage] = useState(null);
  const [handoverValidatedProductBugTests, setHandoverValidatedProductBugTests] = useState(new Set()); // Test cases validated as Product Bug
  const [handoverSelectedTests, setHandoverSelectedTests] = useState(new Set());
  const [handoverFetchingOverride, setHandoverFetchingOverride] = useState(false);
  const [handoverOverrideResult, setHandoverOverrideResult] = useState(null);
  const handoverLstSuggestCacheRef = useRef(new Map());
  const handoverBranchSuggestTimerRef = useRef(null);
  const handoverBranchContainerRef = useRef(null);
  // eslint-disable-next-line no-unused-vars
  const [handoverSearchingLst, setHandoverSearchingLst] = useState({});
  // eslint-disable-next-line no-unused-vars
  const [handoverLstFileResults, setHandoverLstFileResults] = useState({});
  const [handoverDataLocked, setHandoverDataLocked] = useState(false);

  // Deprecation tab
  const [activeTab, setActiveTab] = useState("handover");
  const [deprecationSearchQueries, setDeprecationSearchQueries] = useState([""]);
  const [deprecationResults, setDeprecationResults] = useState(null);
  const [loadingDeprecationSearch, setLoadingDeprecationSearch] = useState(false);
  const [deprecationEditMode, setDeprecationEditMode] = useState(false);
  const [deprecationSelectedRecordKeys, setDeprecationSelectedRecordKeys] = useState(new Set());
  const [deprecationLstFile, setDeprecationLstFile] = useState("");
  const [deprecationLstBranch, setDeprecationLstBranch] = useState("");
  const [deprecationCommitMessage, setDeprecationCommitMessage] = useState("");
  const [deprecationTicketsExtra, setDeprecationTicketsExtra] = useState("");
  const [deprecationReviewers, setDeprecationReviewers] = useState("");
  const [deprecationValidation, setDeprecationValidation] = useState(null);
  const [deprecationCrResult, setDeprecationCrResult] = useState(null);
  const [deprecationCreateLstLoading, setDeprecationCreateLstLoading] = useState(false);
  const [deprecationValidating, setDeprecationValidating] = useState(false);
  const [deprecationManualLstInstructions, setDeprecationManualLstInstructions] = useState(null);

  const getAuthHeaders = () => {
    if (userInfo?.email) return { "X-User-Email": userInfo.email };
    return {};
  };

  const getSelectedHandoverTests = () => {
    if (!handoverAnalysis?.test_cases?.length) return [];
    return handoverSelectedTests.size > 0
      ? Array.from(handoverSelectedTests).filter((name) => handoverAnalysis.test_cases.some((tc) => tc.test_name === name))
      : handoverAnalysis.test_cases.map((tc) => tc.test_name).filter(Boolean);
  };

  const getSelectedPassedHandoverTests = () => {
    if (!handoverAnalysis?.test_cases?.length) return [];
    const selected = new Set(getSelectedHandoverTests());
    return (handoverAnalysis.test_cases || [])
      .filter((tc) => {
        if (!selected.has(tc.test_name)) return false;
        const status = (tc.status || "").toLowerCase();
        const passCount = tc.passed_count || 0;
        return status === "succeeded" || passCount >= 2;
      })
      .map((tc) => tc.test_name)
      .filter(Boolean);
  };

  const getResolvedLstFiles = () => {
    const set = new Set();
    (handoverCreateLstFiles || []).forEach((f) => {
      const v = (f || "").trim();
      if (v) set.add(v);
    });
    const current = (handoverCreateLstFile || "").trim();
    if (current) set.add(current);
    return Array.from(set);
  };

  const buildDefaultCrDescription = () => {
    const reviewersLine = (handoverReviewers || "").split(",").map((r) => r.trim()).filter(Boolean).join(", ");
    const ticketsLine = (handoverTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean).join(", ");
    const targetRelease = (handoverCreateLstBranch || "master").trim() || "master";
    return (
      `Reviewers               : ${reviewersLine}\n` +
      `Tickets resolved        : ${ticketsLine}\n` +
      "Tests run               : \n" +
      `Target release          : ${targetRelease}\n` +
      `Code review URL         : `
    );
  };

  const handleSuggestLstFile = async ({ silent = false } = {}) => {
    const branch = (handoverCreateLstBranch || "").trim();
    const test_names = getSelectedPassedHandoverTests().slice(0, 20);
    if (!branch) {
      if (!silent) alert("Please enter Branch before suggesting LST.");
      return;
    }
    if (!test_names.length) {
      if (!silent) alert("Please select at least one passed testcase before suggesting an LST file.");
      return;
    }
    const cacheKey = `${branch}::${[...test_names].sort().join("|")}`;
    const cached = handoverLstSuggestCacheRef.current.get(cacheKey);
    if (cached) {
      setHandoverLstSuggestion(cached);
      if (cached.suggested_lst_file && getResolvedLstFiles().length === 0 && !(handoverCreateLstFile || "").trim()) {
        setHandoverCreateLstFiles([cached.suggested_lst_file]);
      }
      return;
    }
    setHandoverSuggestingLst(true);
    if (!handoverLstSuggestion) setHandoverLstSuggestion(null);
    try {
      const res = await api.post(
        SUGGEST_LST_FILE_API,
        { branch, test_names },
        { headers: getAuthHeaders(), timeout: 60000 }
      );
      const data = res.data || {};
      handoverLstSuggestCacheRef.current.set(cacheKey, data);
      setHandoverLstSuggestion(data);
      if (data.suggested_lst_file) {
        if (getResolvedLstFiles().length === 0 && !(handoverCreateLstFile || "").trim()) {
          setHandoverCreateLstFiles([data.suggested_lst_file]);
        }
      }
      if (data.error) {
        setHandoverCrResult({ success: false, error: data.error, message: data.message });
      }
    } catch (err) {
      const msg = err.response?.data?.error || err.message || "Failed to suggest LST file.";
      setHandoverLstSuggestion({ error: msg, suggested_lst_file: "", candidates: [] });
    } finally {
      setHandoverSuggestingLst(false);
    }
  };

  useEffect(() => {
    const branch = (handoverCreateLstBranch || "").trim();
    const passed = getSelectedPassedHandoverTests();
    if (!branch || !passed.length || handoverDataLocked) return undefined;
    const t = setTimeout(() => {
      handleSuggestLstFile({ silent: true });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoverCreateLstBranch, handoverSelectedTests, handoverAnalysis, handoverDataLocked]);

  useEffect(() => {
    const q = (handoverCreateLstBranch || "").trim();
    if (handoverBranchSuggestTimerRef.current) clearTimeout(handoverBranchSuggestTimerRef.current);
    if (!q || handoverDataLocked) {
      setHandoverBranchSuggestions([]);
      setHandoverShowBranchDropdown(false);
      return undefined;
    }
    handoverBranchSuggestTimerRef.current = setTimeout(async () => {
      setHandoverBranchLoading(true);
      try {
        const res = await api.get(SEARCH_BRANCHES_API, { params: { q }, headers: getAuthHeaders(), timeout: 20000 });
        const results = (res.data?.results || []).filter(Boolean);
        setHandoverBranchSuggestions(results);
        setHandoverShowBranchDropdown(results.length > 0);
      } catch {
        setHandoverBranchSuggestions([]);
        setHandoverShowBranchDropdown(false);
      } finally {
        setHandoverBranchLoading(false);
      }
    }, 220);
    return () => {
      if (handoverBranchSuggestTimerRef.current) clearTimeout(handoverBranchSuggestTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoverCreateLstBranch, handoverDataLocked]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (handoverBranchContainerRef.current && !handoverBranchContainerRef.current.contains(e.target)) {
        setHandoverShowBranchDropdown(false);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const openCrPreview = () => {
    const selectedTests = getSelectedHandoverTests();
    if (!selectedTests.length) {
      alert("Please select at least one testcase.");
      return;
    }
    if (!(handoverCreateLstBranch || "").trim()) {
      alert("Please enter Branch before previewing CR.");
      return;
    }
    if (!(handoverTicketsExtra || "").trim()) {
      alert("Please enter Handover ticket(s) before previewing CR.");
      return;
    }
    if (!(handoverReviewers || "").trim()) {
      alert("Please add at least one reviewer before previewing CR.");
      return;
    }
    setHandoverCrSubject((prev) => prev || "Testcase Handover");
    if (!(handoverCrDescription || "").trim()) {
      setHandoverCrDescription(buildDefaultCrDescription());
    }
    setHandoverCrPreviewOpen(true);
  };


  const handleHandoverAnalyze = async () => {
    const urls = (handoverJitaUrls || [""]).map((u) => (u || "").trim()).filter(Boolean);
    if (urls.length === 0) {
      alert("Enter at least one JITA results URL or task ID(s). Use + to add more links.");
      return;
    }
    setLoadingHandover(true);
    setHandoverAnalysis(null);
    setHandoverDataLocked(false);
    setHandoverTestTickets({});
    setHandoverBugTypeMap({});
    setHandoverOverrideSave(false);
    setHandoverJiraTicketValidation({});
    setHandoverJiraOverride(false);
    setHandoverManualLstInstructions(null);
    setHandoverCrResult(null);
    setHandoverSelectedTests(new Set());
    setHandoverOverrideResult(null);
    setHandoverLstFileResults({});
    setHandoverTicketsExtra(""); // Clear handover tickets from previous search
    setHandoverCreateLstFile(""); // Clear LST file from previous search
    setHandoverCreateLstFiles([]);
    handoverLstSuggestCacheRef.current.clear();
    setHandoverLstSuggestion(null); // Clear LST suggestion
    setHandoverCreateLstBranch(""); // Clear branch from previous search
    setHandoverBranchSuggestions([]);
    setHandoverShowBranchDropdown(false);
    setHandoverCommitMessage(""); // Clear commit message from previous search
    setHandoverCrPreviewOpen(false);
    setHandoverCrSubject("Testcase Handover");
    setHandoverCrDescription("");
    setHandoverValidatedProductBugTests(new Set()); // Clear validated Product Bug tests
    setHandoverValidation(null); // Clear LST validation
    setHandoverJiraTicketValidation({}); // Clear Jira validation
    try {
      const res = await api.post(JITA_ANALYSIS_API, { urls, min_passes_for_success: 2 }, { timeout: 120000, headers: { "Content-Type": "application/json" } });
      if (res.data?.error) {
        setHandoverAnalysis({ error: res.data.error });
        return;
      }
      setHandoverAnalysis(res.data);
      
      // Auto-populate tickets and bug types from backend analysis
      if (res.data?.test_cases) {
        const ticketsMap = {};
        const bugTypeMap = {};
        
        res.data.test_cases.forEach((tc) => {
          // Store bug type from backend (for logic, not displayed in UI)
          if (tc.bug_type) {
            bugTypeMap[tc.test_name] = tc.bug_type.trim();
          }
          
          // Pre-populate tickets: ONLY use jira_tickets from test case itself
          // Do NOT include assigned_tickets here - those are separate handover-level tickets
          const testcaseTickets = [];
          (tc.jira_tickets || []).forEach((t) => {
            if (t && t.trim()) {
              const trimmed = t.trim();
              if (!testcaseTickets.includes(trimmed)) {
                testcaseTickets.push(trimmed);
              }
            }
          });
          
          if (testcaseTickets.length > 0) {
            ticketsMap[tc.test_name] = testcaseTickets.join(", ");
          }
        });
        
        setHandoverTestTickets(ticketsMap);
        setHandoverBugTypeMap(bugTypeMap);
        
        // Auto-select ALL passed test cases (status from backend respects min_passes_for_success=2)
        const autoSelected = new Set();
        res.data.test_cases.forEach((tc) => {
          const status = (tc.status || "").toLowerCase();
          const passCount = tc.passed_count || 0;
          const isPassed = status === "succeeded" || passCount >= 2;
          
          // Auto-select all passed test cases
          if (isPassed) {
            autoSelected.add(tc.test_name);
          }
        });
        setHandoverSelectedTests(autoSelected);
      }
    } catch (err) {
      console.error("Handover analysis error:", err);
      let errorMsg = "Failed to fetch JITA analysis.";
      
      if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
        errorMsg = "Request timed out after 2 minutes. The JITA task may be large or the server is slow. Please try again or check the JITA URL.";
      } else if (err.message?.includes("Network Error") || err.code === "ERR_NETWORK" || err.code === "ECONNREFUSED") {
        errorMsg = "Network error: Unable to connect to the backend server. Please ensure:\n1. The backend is running (python3 backend/test_flask.py on port 5001)\n2. Your VPN is connected\n3. The backend server is accessible";
      } else if (err.response?.data?.error) {
        errorMsg = err.response.data.error;
      } else if (err.response?.status === 500) {
        errorMsg = "Server error: " + (err.response?.data?.error || err.message || "Internal server error. Check backend logs.");
      } else if (err.response?.status === 400) {
        errorMsg = "Invalid request: " + (err.response?.data?.error || err.message || "Please check the JITA URL format.");
      } else if (err.message) {
        errorMsg = err.message;
      }
      
      setHandoverAnalysis({ error: errorMsg });
    } finally {
      setLoadingHandover(false);
    }
  };

  const handleValidateJiraTickets = async () => {
    // Priority: Table input (user's latest changes) > Backend analysis
    // Extra tickets (handoverTicketsExtra) are validated separately and NOT used for Product Bug validation
    const fromTable = [];
    const ticketsByTest = {}; // Track which tickets belong to which test case (excludes extra tickets)
    Object.entries(handoverTestTickets || {}).forEach(([testName, val]) => {
      const testTickets = (val || "").split(",").map((t) => t.trim().toUpperCase()).filter((t) => /^[A-Z]+-\d+$/.test(t));
      testTickets.forEach((t) => {
        fromTable.push(t);
        if (!ticketsByTest[testName]) ticketsByTest[testName] = [];
        ticketsByTest[testName].push(t);
      });
    });
    
    // Only include backend tickets if user hasn't entered tickets in table for that test case
    const fromAnalysis = [];
    if (handoverAnalysis?.test_cases) {
      handoverAnalysis.test_cases.forEach((tc) => {
        const testName = tc.test_name;
        // Only use backend tickets if user hasn't entered tickets in table for this test
        const hasUserInput = handoverTestTickets[testName] && handoverTestTickets[testName].trim();
        if (!hasUserInput) {
          (tc.jira_tickets || []).forEach((t) => {
            const ticket = (t || "").trim().toUpperCase();
            if (ticket && /^[A-Z]+-\d+$/.test(ticket)) {
              fromAnalysis.push(ticket);
              if (!ticketsByTest[testName]) ticketsByTest[testName] = [];
              ticketsByTest[testName].push(ticket);
            }
          });
        }
      });
    }
    
    // Combine tickets for validation: Only Table input + Backend (skip handover tickets)
    // Note: Handover tickets (handoverTicketsExtra) are NOT validated - they are not bug tickets
    const tickets = [...new Set([...fromTable, ...fromAnalysis])].filter((t) => /^[A-Z]+-\d+$/.test(t));
    if (tickets.length === 0) {
      alert("Enter at least one Jira ticket (e.g. ENG-123) in the Ticket(s) column or handover tickets field.");
      return;
    }
    setHandoverJiraValidating(true);
    setHandoverJiraTicketValidation({});
    setHandoverJiraSkippedMessage(null);
    const results = {};
    for (const ticket of tickets) {
      try {
        const res = await api.post(JIRA_VALIDATE_API, { ticket }, { timeout: 10000, headers: { "Content-Type": "application/json" } });
        if (res.data?.skipped) {
          setHandoverJiraSkippedMessage(res.data.message || "Jira validation is not configured.");
          setHandoverJiraTicketValidation({});
          break;
        }
        results[ticket] = { valid: res.data.valid, issuetype: res.data.issuetype, error: res.data.error };
      } catch (err) {
        results[ticket] = { valid: false, issuetype: null, error: err.response?.data?.error || err.message || "Request failed" };
      }
    }
    if (Object.keys(results).length > 0) setHandoverJiraTicketValidation(results);
    
    // Track which test cases have all their tickets validated as Product Bugs
    // NOTE: Extra tickets (handoverTicketsExtra) are NOT included in this check - they are kept separate
    const validatedProductBugTests = new Set();
    Object.entries(ticketsByTest).forEach(([testName, testTickets]) => {
      // Check if all tickets for this test case are validated as Product Bugs
      // Only considers tickets from table input or backend analysis, NOT extra tickets
      const allValid = testTickets.length > 0 && testTickets.every((ticket) => {
        const validation = results[ticket.toUpperCase()];
        return validation && validation.valid === true;
      });
      if (allValid) {
        validatedProductBugTests.add(testName);
      }
    });
    setHandoverValidatedProductBugTests((prev) => {
      const next = new Set(prev);
      validatedProductBugTests.forEach((testName) => next.add(testName));
      return next;
    });
    
    setHandoverJiraValidating(false);
  };

  const handleOverrideFetch = async () => {
    if (!handoverAnalysis?.test_cases?.length) {
      alert("No test cases to validate.");
      return;
    }
    
    setHandoverFetchingOverride(true);
    setHandoverOverrideResult(null);
    
    try {
      // Get selected test cases or all if none selected
      const testCasesToCheck = handoverSelectedTests.size > 0
        ? handoverAnalysis.test_cases.filter((tc) => handoverSelectedTests.has(tc.test_name))
        : handoverAnalysis.test_cases;
      
      if (testCasesToCheck.length === 0) {
        alert("Please select at least one test case.");
        setHandoverFetchingOverride(false);
        return;
      }
      
      // Collect all unique tickets from test cases only (NOT handover-level tickets)
      // IMPORTANT: Table input (user's latest changes) ALWAYS overrides backend-fetched tickets
      // If user changes ticket in table, use that new ticket instead of the old backend ticket
      // Do NOT include handoverTicketsExtra - those are handover-level, not test-case-specific
      const allTickets = new Set();
      
      // First, collect from table input (user's latest input per test case) - this OVERRIDES backend
      // If user entered "ENG-999" in table, use that instead of backend "ENG-123"
      testCasesToCheck.forEach((tc) => {
        const fromTable = (handoverTestTickets[tc.test_name] || "").split(",").map((t) => t.trim().toUpperCase()).filter((t) => /^[A-Z]+-\d+$/.test(t));
        fromTable.forEach((t) => allTickets.add(t));
      });
      
      // Then, add from test case jira_tickets (from backend analysis) ONLY if user hasn't entered tickets in table
      // If user has entered tickets in table, ignore backend tickets for that test case
      // Do NOT include handoverTicketsExtra - override validation should only consider test-case-specific tickets
      testCasesToCheck.forEach((tc) => {
        const testName = tc.test_name;
        const hasUserInput = handoverTestTickets[testName] && handoverTestTickets[testName].trim();
        // Only use backend tickets if user hasn't entered tickets in table for this test
        // This ensures user's latest input always takes priority
        if (!hasUserInput) {
          (tc.jira_tickets || []).forEach((t) => {
            const ticket = (t || "").trim().toUpperCase();
            if (/^[A-Z]+-\d+$/.test(ticket)) {
              allTickets.add(ticket); // Set will automatically deduplicate
            }
          });
        }
      });
      
      if (allTickets.size === 0) {
        setHandoverOverrideResult({
          allowed: false,
          message: "No Jira tickets found. Override is only allowed with Product Bug tickets.",
        });
        setHandoverFetchingOverride(false);
        return;
      }
      
      // Validate all unique tickets (each ticket validated only once)
      // Convert Set to Array to ensure we only validate each ticket once
      const uniqueTicketsArray = Array.from(allTickets);
      const ticketValidations = {};
      let hasTestBug = false;
      let hasUntriaged = false;
      let productBugCount = 0;
      let testBugCount = 0;
      
      for (const ticket of uniqueTicketsArray) {
        // Skip if already validated (shouldn't happen with Set, but double-check)
        if (ticketValidations[ticket]) {
          continue;
        }
        
        try {
          const res = await api.post(JIRA_VALIDATE_API, { ticket }, { timeout: 10000, headers: { "Content-Type": "application/json" } });
          if (res.data?.skipped) {
            setHandoverOverrideResult({
              allowed: false,
              message: "Jira validation is not configured. Cannot determine bug types.",
            });
            setHandoverFetchingOverride(false);
            return;
          }
          
          ticketValidations[ticket] = {
            valid: res.data.valid,
            issuetype: res.data.issuetype,
            error: res.data.error,
          };
          
          if (res.data.valid) {
            productBugCount++;
          } else {
            const issuetype = (res.data.issuetype || "").toLowerCase();
            if (issuetype.includes("test bug") || issuetype.includes("testbed")) {
              hasTestBug = true;
              testBugCount++;
            } else if (!issuetype || issuetype === "" || issuetype === "—") {
              hasUntriaged = true;
            }
          }
        } catch (err) {
          ticketValidations[ticket] = {
            valid: false,
            issuetype: null,
            error: err.response?.data?.error || err.message || "Request failed",
          };
        }
      }
      
      // Only validate SELECTED test cases - user can uncheck problematic test cases to proceed
      // Only block if SELECTED test cases have Test Bug or Environment in the Bug Type dropdown.
      // Empty/unset bug type is not blocking when all tickets are Product Bug (Jira-validated).
      let hasTestBugOrEnvironmentInMap = false;
      const problematicTests = [];
      testCasesToCheck.forEach((tc) => {
        const bugType = (handoverBugTypeMap[tc.test_name] || "").trim();
        if (!bugType) return; // No bug type selected – don't block; Jira validation decides
        const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
        const hasBlocked = bugTypes.some(
          (bt) => bt.includes("Test Bug") || bt.includes("Environment")
        );
        if (hasBlocked) {
          hasTestBugOrEnvironmentInMap = true;
          problematicTests.push(tc.test_name);
        }
      });
      
      // Check conditions: if out of multiple bug types, even 1 is testbug, then block
      // Use the count of unique validated tickets (not total tickets collected)
      const totalTickets = uniqueTicketsArray.length;
      
      // First check bug types from backend categorization
      // Only validate SELECTED test cases - user can uncheck problematic test cases
      if (hasTestBugOrEnvironmentInMap) {
        setHandoverOverrideResult({
          allowed: false,
          message: `Override not allowed: The following SELECTED test case(s) contain Test Bug or Environment bug types: ${problematicTests.slice(0, 3).join(", ")}${problematicTests.length > 3 ? "..." : ""}. Please uncheck these test cases if you want to proceed with override for the remaining test cases. Only Product Bug (without Test Bug or Environment) is allowed for override.`,
          ticketValidations,
        });
        setHandoverOverrideSave(false);
      } else if (hasTestBug || hasUntriaged) {
        // Also check from ticket validation
        setHandoverOverrideResult({
          allowed: false,
          message: `Override not allowed: Found ${testBugCount} Test Bug(s) and ${hasUntriaged ? "untriaged" : ""} ticket(s). Only Product Bug tickets are allowed for override.`,
          ticketValidations,
        });
        setHandoverOverrideSave(false);
      } else if (productBugCount > 0 && productBugCount === totalTickets) {
        // All tickets are Product Bugs AND no Test Bug/Environment in bug type map
        setHandoverOverrideResult({
          allowed: true,
          message: `Override allowed: All ${productBugCount} ticket(s) are Product Bugs and no Test Bug/Environment found in bug types.`,
          ticketValidations,
        });
        setHandoverOverrideSave(true);
      } else if (productBugCount === 0) {
        setHandoverOverrideResult({
          allowed: false,
          message: "Override not allowed: No Product Bug tickets found. Override is only allowed with Product Bug tickets.",
          ticketValidations,
        });
        setHandoverOverrideSave(false);
      } else {
        setHandoverOverrideResult({
          allowed: false,
          message: `Override not allowed: Found ${totalTickets - productBugCount} non-Product Bug ticket(s). Only Product Bug tickets are allowed for override.`,
          ticketValidations,
        });
        setHandoverOverrideSave(false);
      }
    } catch (err) {
      setHandoverOverrideResult({
        allowed: false,
        message: `Error validating override: ${err.message}`,
      });
    } finally {
      setHandoverFetchingOverride(false);
    }
  };

  // eslint-disable-next-line no-unused-vars
  const handleSearchLstFile = async (testName) => {
    if (!testName) return;
    setHandoverSearchingLst((prev) => ({ ...prev, [testName]: true }));
    try {
      const res = await api.post(SEARCH_LST_FILE_API, { test_name: testName }, { timeout: 20000, headers: { "Content-Type": "application/json" } });
      setHandoverLstFileResults((prev) => ({
        ...prev,
        [testName]: res.data,
      }));
    } catch (err) {
      setHandoverLstFileResults((prev) => ({
        ...prev,
        [testName]: { error: err.response?.data?.error || err.message || "Search failed" },
      }));
    } finally {
      setHandoverSearchingLst((prev) => ({ ...prev, [testName]: false }));
    }
  };

  const handleValidateLst = async () => {
    // Validate all mandatory fields
    const lst_files = getResolvedLstFiles();
    const branch = (handoverCreateLstBranch || "").trim();
    const handoverTickets = (handoverTicketsExtra || "").trim();
    
    if (lst_files.length === 0) {
      alert("Please enter the LST file path to validate.");
      return;
    }
    if (!branch) {
      alert("Please enter the Branch.");
      return;
    }
    if (!handoverTickets) {
      alert("Please enter Handover ticket(s), comma-separated.");
      return;
    }
    setHandoverValidating(true);
    setHandoverValidation(null);
    setHandoverCrResult(null);
    try {
      const responses = await Promise.all(
        lst_files.map((lst_file) =>
          api.post(
            VALIDATE_LST_API,
            { branch, lst_file, repo_name: "nugerrit.ntnxdpro.com/nutest-py3-tests" },
            { timeout: 30000 }
          ).then((r) => ({ lst_file, ...(r.data || {}) }))
        )
      );
      const resolvedBranch = responses.find((r) => (r.resolved_branch || "").trim())?.resolved_branch;
      if (resolvedBranch && resolvedBranch !== branch) {
        setHandoverCreateLstBranch(resolvedBranch);
      }
      const allValid = responses.length > 0 && responses.every((r) => r.file_valid === true && r.branch_valid === true && !r.error);
      setHandoverValidation({
        all_valid: allValid,
        files: responses,
        branch_valid: allValid,
        file_valid: allValid,
        branch_error: allValid ? null : responses.find((r) => r.branch_error)?.branch_error || null,
        file_error: allValid ? null : responses.find((r) => r.file_error)?.file_error || null,
      });
    } catch (err) {
      console.error("LST validation error:", err);
      let errorMsg = "Validation failed";
      if (err.response?.data?.error) {
        errorMsg = err.response.data.error;
      } else if (err.message) {
        errorMsg = err.message;
      } else if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
        errorMsg = "Request timed out. Please check your network connection and try again.";
      } else if (err.message?.includes("Network Error") || err.code === "ERR_NETWORK") {
        errorMsg = "Network error: Unable to connect to the backend server. Please ensure the backend is running.";
      }
      setHandoverValidation({ error: errorMsg, branch_valid: null, file_valid: null });
    } finally {
      setHandoverValidating(false);
    }
  };

  // eslint-disable-next-line no-unused-vars
  const handleHandoverCreateLstCr = async (manualOnly) => {
    if (!handoverAnalysis?.test_cases?.length) {
      alert("Analyze JITA results first.");
      return;
    }
    const test_names = getSelectedHandoverTests();

    if (test_names.length === 0) {
      alert("Please select at least one test case.");
      return;
    }
    const branch = (handoverCreateLstBranch || "master").trim() || "master";
    const lst_files = getResolvedLstFiles();
    const lst_file = lst_files[0] || "";
    const reviewersList = (handoverReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const handoverTicketsList = (handoverTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);

    if (!reviewersList.length) {
      alert("Please add reviewer(s) before creating CR.");
      return;
    }
    if (!handoverTicketsList.length) {
      alert("Please enter handover ticket(s) before creating CR.");
      return;
    }
    if (!lst_files.length) {
      alert("Please add at least one LST file path.");
      return;
    }
    if (!manualOnly) {
      const canProceed = handoverAnalysis?.all_tests_passed || handoverOverrideSave;
      if (!canProceed) {
        alert("All test cases must pass before creating LST CR, or select Override to save handover data.");
        return;
      }
    }
    setHandoverCreateLstLoading(true);
    setHandoverManualLstInstructions(null);
    setHandoverCrResult(null);
    const commitMsg = "Add " + test_names.length + " test(s) to " + lst_file + (handoverCommitMessage.trim() ? "\n\n" + handoverCommitMessage.trim() : "");
    const finalCrSubject = (handoverCrSubject || "Testcase Handover").trim() || "Testcase Handover";
    const finalCrDescription = (handoverCrDescription || "").trim() || buildDefaultCrDescription();
    try {
      const res = await api.post(
        CREATE_LST_CR_API,
        {
          branch,
          test_names,
          lst_file,
          commit_message: commitMsg,
          manual_only: !!manualOnly,
          user_email: userInfo?.email,
          user_name: userInfo?.name,
          handover_tickets: handoverTicketsList,
          reviewers: reviewersList.length ? reviewersList : undefined,
          cr_subject: finalCrSubject,
          cr_description: finalCrDescription,
        },
        { headers: getAuthHeaders() }
      );
      if ((res.data.manual || manualOnly) && res.data.instructions) {
        setHandoverManualLstInstructions(res.data.instructions);
        setHandoverCrResult({ success: true, manual: true, message: res.data.message || "Manual CR steps generated below." });
        setHandoverDataLocked(true);
      } else if (res.data.success) {
        setHandoverCrResult({ success: true, cr_url: res.data.cr_url, message: res.data.message, already_present: res.data.already_present || [], to_add: res.data.to_add || [] });
        setHandoverDataLocked(true);
      } else if (res.data.already_present?.length > 0 && (!res.data.to_add || res.data.to_add.length === 0)) {
        setHandoverCrResult({ success: false, message: res.data.message || "All tests already in LST file.", already_present: res.data.already_present, to_add: [] });
      } else {
        if (res.data.instructions) setHandoverManualLstInstructions(res.data.instructions);
        if (res.data.message) alert(res.data.message);
      }
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.require_key_setup && errData?.missing_key === "gerrit_http_password") {
        setHandoverCrResult({
          success: false,
          error: "Gerrit HTTP password is missing. Please add it in Settings → API Key Configuration.",
          message: errData?.message || errData?.error,
          require_key_setup: true,
        });
        return;
      }
      setHandoverCrResult({
        success: false,
        error: errData?.error || "Failed to create LST CR.",
        message: errData?.message,
        vpn_required: errData?.vpn_required,
        git_error: errData?.git_error,
        raw_error: errData?.raw_error,
      });
      if (errData?.instructions) setHandoverManualLstInstructions(errData.instructions);
    } finally {
      setHandoverCreateLstLoading(false);
    }
  };

  const handleDeprecationSearch = async () => {
    const parts = (deprecationSearchQueries || [""])
      .map((s) => (s || "").trim())
      .filter(Boolean);
    if (!parts.length) {
      alert("Enter one or more test names to search.");
      return;
    }
    setLoadingDeprecationSearch(true);
    setDeprecationResults(null);
    try {
      // Use POST with body to avoid URL length/encoding issues with long test names
      const res = await api.post(DEPRECATION_SEARCH_API, { q: parts });
      setDeprecationResults(res.data);
      setDeprecationSelectedRecordKeys(new Set());
    } catch (err) {
      setDeprecationResults({ error: err.response?.data?.error || "Search failed.", results: [], count: 0 });
      setDeprecationSelectedRecordKeys(new Set());
    } finally {
      setLoadingDeprecationSearch(false);
    }
  };

  const handleDeprecationDeleteAll = async (testName, records) => {
    if (!deprecationResults?.results || !records?.length) return;
    if (!window.confirm(`Delete ${records.length} handover record(s) for "${testName}"?`)) return;
    const toRemove = new Set(records.map((r) => getDeprecationRecordKey(r)));
    let deleted = 0;
    for (const r of records) {
      try {
        const res = await api.post(HANDOVER_RECORD_DELETE_API, {
          test_name: r.test_name,
          handover_date: r.handover_date,
          lst_file: r.lst_file || "",
        });
        if (res.data?.success) deleted++;
      } catch (err) {
        console.error("Delete handover record error:", err);
      }
    }
    setDeprecationResults((prev) => ({
      ...prev,
      results: (prev?.results || []).filter((x) => !toRemove.has(getDeprecationRecordKey(x))),
      count: Math.max(0, (prev?.count ?? 0) - deleted),
    }));
    setDeprecationSelectedRecordKeys((prev) => {
      const next = new Set(prev);
      records.forEach((r) => next.delete(getDeprecationRecordKey(r)));
      return next;
    });
  };

  const handleDeprecationValidateLst = async () => {
    const branch = (deprecationLstBranch || "master").trim() || "master";
    const lst_file = deprecationLstFile.trim();
    if (!lst_file) {
      alert("Enter the LST file path.");
      return;
    }
    const test_names = [...new Set((deprecationResults?.results || []).filter((r) => deprecationSelectedRecordKeys.has(getDeprecationRecordKey(r))).map((r) => (r.test_name || "").trim()))];
    if (!test_names.length) {
      alert("Select at least one test case (checkbox) to check in the LST file.");
      return;
    }
    setDeprecationValidating(true);
    setDeprecationValidation(null);
    setDeprecationCrResult(null);
    try {
      const res = await api.post(CHECK_LST_TESTCASES_API, { branch, lst_file, test_names }, { timeout: 30000 });
      setDeprecationValidation(res.data);
    } catch (err) {
      let errorMsg = "Check failed";
      if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
        errorMsg = "Request timed out. Please check your network connection and try again, or paste the LST file content below.";
      } else if (err.message?.includes("Network Error") || err.code === "ERR_NETWORK") {
        errorMsg = "Network error: Unable to connect to the backend. Please check your VPN connection and ensure the backend is running.";
      } else {
        errorMsg = err.response?.data?.error || err.message || "Check failed";
      }
      setDeprecationValidation({ error: errorMsg, present: [], not_present: test_names });
    } finally {
      setDeprecationValidating(false);
    }
  };

  const handleDeprecationCreateLstCr = async (manualOnly) => {
    const test_names = [...new Set((deprecationResults?.results || []).filter((r) => deprecationSelectedRecordKeys.has(getDeprecationRecordKey(r))).map((r) => (r.test_name || "").trim()))];
    if (!test_names.length) {
      alert("Select at least one test case (checkbox) for deprecation.");
      return;
    }
    const branch = (deprecationLstBranch || "master").trim() || "master";
    const lst_file = deprecationLstFile.trim();
    if (!lst_file) {
      alert("Please enter the LST file path.");
      return;
    }
    setDeprecationCreateLstLoading(true);
    setDeprecationManualLstInstructions(null);
    setDeprecationCrResult(null);
    const ticketsList = (deprecationTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    const reviewersList = (deprecationReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const commitMsg = "Deprecated " + test_names.length + " test(s) from " + lst_file + (ticketsList.length ? "\n\nJira: " + ticketsList.join(", ") : "") + (deprecationCommitMessage.trim() ? "\n\n" + deprecationCommitMessage.trim() : "");
    try {
      const res = await api.post(
        DEPRECATE_LST_CR_API,
        { branch, lst_file, test_names, commit_message: commitMsg, jira_tickets: ticketsList.length ? ticketsList : undefined, reviewers: reviewersList.length ? reviewersList : undefined },
        { headers: getAuthHeaders() }
      );
      if (res.data.manual && res.data.instructions) {
        setDeprecationManualLstInstructions(res.data.instructions);
        setDeprecationCrResult({ success: true, manual: true, message: res.data.message || "Manual CR steps generated below." });
      } else if (res.data.success) {
        setDeprecationCrResult({ success: true, cr_url: res.data.cr_url, message: res.data.message });
      } else {
        setDeprecationCrResult({ success: false, message: res.data.message, error: res.data.error });
      }
    } catch (err) {
      const errData = err.response?.data;
      setDeprecationCrResult({ success: false, error: errData?.error || "Failed to create CR", message: errData?.message });
    } finally {
      setDeprecationCreateLstLoading(false);
    }
  };

  // eslint-disable-next-line no-unused-vars
  const handleRecordHandover = async () => {
    if (!handoverAnalysis?.test_cases?.length) return;
    const test_names = getSelectedHandoverTests();
    
    if (test_names.length === 0) {
      alert("Please select at least one test case.");
      return;
    }
    
    // Only validate SELECTED test cases - user can uncheck problematic test cases to proceed
    // Only block when SELECTED test cases have Test Bug or Environment
    // Empty/unset bug type is allowed (same as Override: Jira-validated Product Bug is enough).
    const selectedTestCases = handoverAnalysis.test_cases.filter((tc) => test_names.includes(tc.test_name));
    const problematicTests = [];
    selectedTestCases.forEach((tc) => {
      const bugType = (handoverBugTypeMap[tc.test_name] || "").trim();
      if (!bugType) return;
      const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
      const hasBlocked = bugTypes.some((bt) => bt.includes("Test Bug") || bt.includes("Environment"));
      if (hasBlocked) {
        problematicTests.push(tc.test_name);
      }
    });
    
    if (problematicTests.length > 0) {
      alert(`Cannot record handover: The following SELECTED test case(s) contain Test Bug or Environment bug types:\n${problematicTests.join("\n")}\n\nPlease uncheck these test cases if you want to proceed with handover for the remaining test cases. Only Product Bug (without Test Bug or Environment) is allowed.`);
      return;
    }
    
    const handoverTicketsList = (handoverTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    // Separate bug tickets (from test cases) from handover tickets
    // Priority: Table input (user's latest changes) overrides backend-fetched tickets
    const test_bug_tickets = {};  // Bug tickets: from table input (if provided) or test case jira_tickets
    handoverAnalysis.test_cases.forEach((tc) => {
      if (!tc.test_name) return;
      const fromTable = (handoverTestTickets[tc.test_name] || "").split(",").map((t) => t.trim()).filter(Boolean);
      // If user has entered tickets in table, use those (override backend)
      // Otherwise, use backend tickets
      const fromAnalysis = fromTable.length > 0 ? [] : (tc.jira_tickets || []);
      // Bug tickets: prioritize table input, fallback to backend analysis
      const bugTickets = fromTable.length > 0 ? fromTable : [...new Set(fromAnalysis)];
      if (bugTickets.length) test_bug_tickets[tc.test_name] = bugTickets;
    });
    const hasPerTestBugTickets = Object.keys(test_bug_tickets).length > 0;
    const ticketsList = hasPerTestBugTickets ? undefined : [...new Set([...(handoverAnalysis.assigned_tickets || []), ...handoverTicketsList])];
    try {
      await api.post(HANDOVER_RECORD_API, {
        test_names,
        test_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,  // Keep for backward compatibility
        tickets: ticketsList?.length ? ticketsList : undefined,  // Keep for backward compatibility
        test_bug_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,  // Bug tickets (from test cases)
        handover_tickets: handoverTicketsList.length > 0 ? handoverTicketsList : undefined,  // Handover-level tickets only
        by_whom: userInfo?.email || userInfo?.name || "unknown",
        branch: (handoverCreateLstBranch || "master").trim(),
        lst_file: (handoverCreateLstFile || "").trim(),
      });
      return { success: true, message: "Handover saved. You can search by test name on the Deprecation page." };
    } catch (err) {
      return { success: false, error: err.response?.data?.error || "Failed to save handover." };
    }
  };

  const handleRecordHandoverAndCreateCR = async () => {
    if (!handoverAnalysis?.test_cases?.length) {
      alert("No test cases available.");
      return;
    }

    // Use selected tests if any, otherwise all tests
    const test_names = handoverSelectedTests.size > 0
      ? Array.from(handoverSelectedTests).filter((name) => handoverAnalysis.test_cases.some((tc) => tc.test_name === name))
      : handoverAnalysis.test_cases.map((tc) => tc.test_name).filter(Boolean);
    
    if (test_names.length === 0) {
      alert("Please select at least one test case.");
      return;
    }

    // Validate test cases for handover (check for Test Bug/Environment)
    const selectedTestCases = handoverAnalysis.test_cases.filter((tc) => test_names.includes(tc.test_name));
    const problematicTests = [];
    selectedTestCases.forEach((tc) => {
      const bugType = (handoverBugTypeMap[tc.test_name] || "").trim();
      if (!bugType) return;
      const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
      const hasBlocked = bugTypes.some((bt) => bt.includes("Test Bug") || bt.includes("Environment"));
      if (hasBlocked) {
        problematicTests.push(tc.test_name);
      }
    });
    
    if (problematicTests.length > 0) {
      alert(`Cannot record handover: The following SELECTED test case(s) contain Test Bug or Environment bug types:\n${problematicTests.join("\n")}\n\nPlease uncheck these test cases if you want to proceed with handover for the remaining test cases. Only Product Bug (without Test Bug or Environment) is allowed.`);
      return;
    }

    // Check if CR can be created: allow when all tests passed, OR override saved, OR user selected only passed tests (no Jira needed)
    const allSelectedArePassed = selectedTestCases.every((tc) => {
      const passCount = tc.passed_count || 0;
      const status = (tc.status || "").toLowerCase();
      return status === "succeeded" || passCount >= 2;
    });
    const canProceedCR = handoverAnalysis?.all_tests_passed || handoverOverrideSave || allSelectedArePassed;
    if (!canProceedCR) {
      alert("All test cases must pass before creating LST CR, or select Override to save handover data.");
      return;
    }

    const branch = (handoverCreateLstBranch || "master").trim() || "master";
    const lst_files = getResolvedLstFiles();
    const lst_file = lst_files[0] || "";
    const reviewersList = (handoverReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const handoverTicketsList = (handoverTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    if (!reviewersList.length) {
      alert("Please add reviewer(s) before creating CR.");
      return;
    }
    if (!handoverTicketsList.length) {
      alert("Please enter handover ticket(s) before creating CR.");
      return;
    }
    if (!lst_files.length) {
      alert("Please add at least one LST file path.");
      return;
    }

    // Set loading states
    setHandoverCreateLstLoading(true);
    setHandoverManualLstInstructions(null);
    setHandoverCrResult(null);

    // Prepare handover data
    const test_bug_tickets = {};
    handoverAnalysis.test_cases.forEach((tc) => {
      if (!tc.test_name) return;
      const fromTable = (handoverTestTickets[tc.test_name] || "").split(",").map((t) => t.trim()).filter(Boolean);
      const fromAnalysis = fromTable.length > 0 ? [] : (tc.jira_tickets || []);
      const bugTickets = fromTable.length > 0 ? fromTable : [...new Set(fromAnalysis)];
      if (bugTickets.length) test_bug_tickets[tc.test_name] = bugTickets;
    });
    const hasPerTestBugTickets = Object.keys(test_bug_tickets).length > 0;
    const ticketsList = hasPerTestBugTickets ? undefined : [...new Set([...(handoverAnalysis.assigned_tickets || []), ...handoverTicketsList])];

    // Prepare CR data
    const commitMsg = "Add " + test_names.length + " test(s) to " + lst_file + (handoverCommitMessage.trim() ? "\n\n" + handoverCommitMessage.trim() : "");
    const finalCrSubject = (handoverCrSubject || "Testcase Handover").trim() || "Testcase Handover";
    const finalCrDescription = (handoverCrDescription || "").trim() || buildDefaultCrDescription();

    // Execute both operations independently
    let handoverResult = null;
    let crResult = null;

    // 1. Record Handover (independent)
    try {
      await api.post(HANDOVER_RECORD_API, {
        test_names,
        test_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        tickets: ticketsList?.length ? ticketsList : undefined,
        test_bug_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        handover_tickets: handoverTicketsList.length > 0 ? handoverTicketsList : undefined,
        by_whom: userInfo?.email || userInfo?.name || "unknown",
        branch,
        lst_file: lst_file || "",
      });
      handoverResult = { success: true, message: "Handover saved successfully." };
    } catch (err) {
      handoverResult = { success: false, error: err.response?.data?.error || "Failed to save handover." };
    }

    // 2. Create CR (independent)
    try {
      const res = await api.post(
        CREATE_LST_CR_API,
        {
          branch,
          test_names,
          lst_file: lst_file || "",
          lst_files,
          commit_message: commitMsg,
          manual_only: false,
          user_email: userInfo?.email,
          user_name: userInfo?.name,
          handover_tickets: handoverTicketsList,
          reviewers: reviewersList.length ? reviewersList : undefined,
          cr_subject: finalCrSubject,
          cr_description: finalCrDescription,
        },
        { headers: getAuthHeaders(), timeout: 300000 }
      );
      if (res.data.manual && res.data.instructions) {
        setHandoverManualLstInstructions(res.data.instructions);
        crResult = { success: true, manual: true, message: res.data.message || "Manual CR steps generated below." };
      } else if (res.data.success) {
        crResult = { success: true, cr_url: res.data.cr_url, message: res.data.message, already_present: res.data.already_present || [], to_add: res.data.to_add || [] };
      } else if (res.data.already_present?.length > 0 && (!res.data.to_add || res.data.to_add.length === 0)) {
        crResult = { success: false, message: res.data.message || "All tests already in LST file.", already_present: res.data.already_present, to_add: [] };
      } else {
        if (res.data.instructions) setHandoverManualLstInstructions(res.data.instructions);
        crResult = { success: false, error: res.data.error, message: res.data.message || res.data.error || "Failed to create CR." };
      }
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.require_key_setup && errData?.missing_key === "gerrit_http_password") {
        crResult = {
          success: false,
          error: "Gerrit HTTP password is missing. Please add it in Settings → API Key Configuration.",
          message: errData?.message || errData?.error,
          require_key_setup: true,
        };
        setHandoverCrResult(crResult);
        setHandoverCreateLstLoading(false);
        alert(crResult.error);
        return;
      }
      let errMsg = errData?.error || errData?.message;
      if (!errMsg) {
        const isConnReset = err.code === "ECONNRESET" || err.code === "ETIMEDOUT" || err.message === "Network Error"
          || (err.message && (String(err.message).includes("hang up") || String(err.message).includes("ECONNRESET") || String(err.message).includes("timeout")));
        if (isConnReset) {
          errMsg = "Request was interrupted (connection reset or timeout). The backend may have restarted during git clone. Try again and avoid editing files while CR is being created.";
        } else if (err.response?.status >= 500) {
          errMsg = "Backend error. Check the backend terminal for details.";
        } else {
          errMsg = err.message || "Failed to create LST CR.";
        }
      }
      crResult = {
        success: false,
        error: errMsg,
        message: errData?.message || errMsg,
        vpn_required: errData?.vpn_required,
        git_error: errData?.git_error,
        raw_error: errData?.raw_error,
      };
      if (errData?.instructions) setHandoverManualLstInstructions(errData.instructions);
    }

    // Set CR result state
    setHandoverCrResult(crResult);

    // Show combined message
    let message = "";
    if (handoverResult.success && crResult.manual) {
      message = "✓ Handover recorded. Follow the manual git steps shown below to push the CR for review.";
    } else if (handoverResult.success && crResult.success) {
      message = "✓ Handover recorded and CR created successfully!";
      if (crResult.cr_url) {
        message += ` CR: ${crResult.cr_url}`;
      }
    } else if (handoverResult.success && !crResult.success) {
      message = `✓ Handover recorded successfully, but CR failed: ${crResult.error || crResult.message || "Unknown error"}`;
    } else if (!handoverResult.success && crResult.success) {
      message = `✓ CR created successfully, but handover failed: ${handoverResult.error || "Unknown error"}`;
    } else {
      message = `✗ Both operations failed. Handover: ${handoverResult.error || "Unknown error"}. CR: ${crResult.error || crResult.message || "Unknown error"}`;
    }
    alert(message);
    if (handoverResult.success || crResult.success) {
      setHandoverDataLocked(true);
    }

    setHandoverCreateLstLoading(false);
  };

  return (
    <div className="ho-page">
      <div className="ho-header">
        <div className="ho-header__titles">
          <h1 className="ho-title">Handover &amp; Deprecation</h1>
          <p className="ho-subtitle">
            Onboard new test cases into LST files and deprecate existing ones —
            backed by JITA results, Jira validation and Gerrit reviews.
          </p>
        </div>
        <div className="ho-tabs" role="tablist" aria-label="Handover or Deprecation">
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "handover"}
            className={`ho-tab${activeTab === "handover" ? " is-active" : ""}`}
            onClick={() => setActiveTab("handover")}
          >
            Handover
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "deprecation"}
            className={`ho-tab${activeTab === "deprecation" ? " is-active" : ""}`}
            onClick={() => setActiveTab("deprecation")}
          >
            Deprecation
          </button>
        </div>
      </div>

      {activeTab === "handover" && (
        <>
      <p className="ho-subtitle ho-intro">
        Enter JITA results URL(s). A test is <strong>Passed</strong> only if it passed in <strong>both of the 2 latest runs</strong> (consecutive); otherwise <strong>Failed</strong>. Product Bug failures can be selected manually. Record handover and optionally create a Gerrit CR to add tests to an LST file.
      </p>

      <div className="ho-card">
        <div className="ho-card__title">JITA results</div>
        {(handoverJitaUrls || [""]).map((link, idx) => (
          <div key={idx} style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px", flexWrap: "wrap" }}>
            <input
              type="text"
              value={link}
              onChange={(e) => {
                const next = [...(handoverJitaUrls || [""])];
                next[idx] = e.target.value;
                setHandoverJitaUrls(next);
              }}
              placeholder={idx === 0 ? "JITA URL or task ID(s)" : "Another JITA URL or task ID(s)"}
              style={{ flex: 1, minWidth: "280px", padding: "8px 12px", fontSize: "14px", border: "1px solid #ddd", borderRadius: "4px", boxSizing: "border-box" }}
            />
            {idx === (handoverJitaUrls || [""]).length - 1 ? (
              <button type="button" onClick={() => setHandoverJitaUrls((prev) => [...(prev || [""]), ""])} style={{ padding: "8px 14px", background: "#0d9488", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>+</button>
            ) : (handoverJitaUrls || [""]).length > 1 ? (
              <button type="button" onClick={() => setHandoverJitaUrls((prev) => prev.filter((_, i) => i !== idx))} style={{ padding: "6px 10px", background: "#f87171", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>×</button>
            ) : null}
          </div>
        ))}
        <div style={{ display: "flex", gap: "12px", marginTop: "12px", flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button onClick={() => handleHandoverAnalyze()} disabled={loadingHandover} style={loadingHandover ? { ...btnValidateDisabled } : { ...btnSecondary }}>
            {loadingHandover ? "Loading..." : "Fetch from URL(s)"}
          </button>
        </div>
      </div>

      {handoverAnalysis && (
        <div style={{ marginTop: "20px" }}>
          {handoverDataLocked && !handoverAnalysis.error && (
            <div style={{ marginBottom: "12px", padding: "12px 16px", background: "#f1f5f9", borderRadius: "8px", border: "1px solid #cbd5e1", color: "#475569", fontSize: "14px" }}>
              ✓ Data saved. Change JITA URL and click <strong>Fetch from URL(s)</strong> to make new changes.
            </div>
          )}
          {handoverAnalysis.error ? (
            <div style={{ color: "#dc3545", padding: "12px", background: "#fef2f2", borderRadius: "8px" }}>{handoverAnalysis.error}</div>
          ) : (
            <>
              <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "12px", alignItems: "center", fontSize: "14px" }}>
                <span style={{ fontWeight: "bold" }}>All tests passed: <span style={{ color: handoverAnalysis.all_tests_passed ? "#28a745" : "#dc3545" }}>{handoverAnalysis.all_tests_passed ? "Yes" : "No"}</span></span>
                {handoverAnalysis.total_executions != null && (
                  <span style={{ color: "#0c5460", background: "#e0f2fe", padding: "4px 10px", borderRadius: "6px" }}>
                    {handoverAnalysis.total_executions} executions, {handoverAnalysis.total_passed ?? 0} passed
                  </span>
                )}
              </div>

              <table className="ho-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginBottom: "16px" }}>
                <thead>
                  <tr style={{ background: "#f1f5f9" }}>
                    <th style={{ padding: "8px", border: "1px solid #e2e8f0", width: "40px", textAlign: "center" }}>
                      <input
                        type="checkbox"
                        checked={(() => {
                          // Get all Product Bug test cases
                          const productBugTestCases = (handoverAnalysis.test_cases || []).filter((tc) => {
                            const isValidated = handoverValidatedProductBugTests.has(tc.test_name);
                            if (isValidated) return true;
                            
                            const bugType = (handoverBugTypeMap[tc.test_name] || tc.bug_type || "").trim();
                            if (!bugType) return false;
                            const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
                            const hasTestBug = bugTypes.some((bt) => {
                              const btLower = bt.toLowerCase();
                              return btLower.includes("test bug") || btLower.includes("testbed") || btLower.includes("environment");
                            });
                            const hasProductBug = bugTypes.some((bt) => {
                              const btLower = bt.toLowerCase();
                              return btLower.includes("product bug") || (btLower.includes("product") && btLower.includes("bug") && !btLower.includes("test"));
                            });
                            return hasProductBug && !hasTestBug;
                          });
                          
                          // Get all passed test cases
                          const passedTestCases = (handoverAnalysis.test_cases || []).filter((tc) => {
                            const passCount = tc.passed_count || 0;
                            const status = (tc.status || "").toLowerCase();
                            return status === "succeeded" || passCount >= 2;
                          });
                          
                          // Combine both sets
                          const allSelectableTestCases = new Set([
                            ...productBugTestCases.map((tc) => tc.test_name),
                            ...passedTestCases.map((tc) => tc.test_name)
                          ]);
                          
                          // Check if all selectable test cases are selected
                          return allSelectableTestCases.size > 0 && Array.from(allSelectableTestCases).every((testName) => handoverSelectedTests.has(testName));
                        })()}
                        onChange={(e) => {
                          if (e.target.checked) {
                            // Select all Product Bug test cases AND all passed test cases
                            const productBugTestCases = (handoverAnalysis.test_cases || []).filter((tc) => {
                              const isValidated = handoverValidatedProductBugTests.has(tc.test_name);
                              if (isValidated) return true;
                              
                              const bugType = (handoverBugTypeMap[tc.test_name] || tc.bug_type || "").trim();
                              if (!bugType) return false;
                              const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
                              const hasTestBug = bugTypes.some((bt) => {
                                const btLower = bt.toLowerCase();
                                return btLower.includes("test bug") || btLower.includes("testbed") || btLower.includes("environment");
                              });
                              const hasProductBug = bugTypes.some((bt) => {
                                const btLower = bt.toLowerCase();
                                return btLower.includes("product bug") || (btLower.includes("product") && btLower.includes("bug") && !btLower.includes("test"));
                              });
                              return hasProductBug && !hasTestBug;
                            });
                            
                            const passedTestCases = (handoverAnalysis.test_cases || []).filter((tc) => {
                              const passCount = tc.passed_count || 0;
                              const status = (tc.status || "").toLowerCase();
                              return status === "succeeded" || passCount >= 2;
                            });
                            
                            // Combine both sets
                            const allSelectable = new Set([
                              ...productBugTestCases.map((tc) => tc.test_name),
                              ...passedTestCases.map((tc) => tc.test_name)
                            ]);
                            
                            setHandoverSelectedTests(new Set(allSelectable));
                          } else {
                            setHandoverSelectedTests(new Set());
                          }
                        }}
                        style={{ width: "16px", height: "16px", cursor: handoverDataLocked ? "not-allowed" : "pointer", opacity: handoverDataLocked ? 0.6 : 1 }}
                        title={handoverDataLocked ? "Data saved. Change JITA URL and Fetch to edit." : "Select all Product Bug and passed test cases"}
                      />
                    </th>
                    <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left", minWidth: "130ch" }}>Test name</th>
                    <th style={{ padding: "8px", border: "1px solid #e2e8f0" }}>Passed / Total</th>
                    <th style={{ padding: "8px", border: "1px solid #e2e8f0" }}>Status</th>
                    <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left" }}>Ticket(s)</th>
                  </tr>
                </thead>
                <tbody>
                  {(handoverAnalysis.test_cases || []).map((tc) => {
                    const isSelected = handoverSelectedTests.has(tc.test_name);
                    // Check if this test case is allowed for checkbox
                    // Allow: Product Bug test cases OR passed test cases
                    // Block: Test Bug/Environment/Untriaged that are NOT passed
                    const bugType = (handoverBugTypeMap[tc.test_name] || tc.bug_type || "").trim();
                    const isValidatedAsProductBug = handoverValidatedProductBugTests.has(tc.test_name);
                    const passCount = tc.passed_count || 0;
                    const status = (tc.status || "").toLowerCase();
                    const isPassed = status === "succeeded" || passCount >= 2;
                    
                    const isAllowedForCheckbox = (() => {
                      // If validated as Product Bug via Jira validation, allow checkbox
                      if (isValidatedAsProductBug) return true;
                      
                      // If test case is passed, allow checkbox (regardless of bug type)
                      if (isPassed) return true;
                      
                      // For non-passed test cases, only allow Product Bug
                      if (!bugType) return false; // Untriaged and not passed - not allowed
                      const bugTypes = bugType.split(",").map((bt) => bt.trim()).filter(Boolean);
                      // Case-insensitive check for Test Bug or Environment
                      const hasTestBug = bugTypes.some((bt) => {
                        const btLower = bt.toLowerCase();
                        return btLower.includes("test bug") || btLower.includes("testbed") || btLower.includes("environment");
                      });
                      // Case-insensitive check for Product Bug (also check for "product" and "bug" together)
                      const hasProductBug = bugTypes.some((bt) => {
                        const btLower = bt.toLowerCase();
                        return btLower.includes("product bug") || (btLower.includes("product") && btLower.includes("bug") && !btLower.includes("test"));
                      });
                      return hasProductBug && !hasTestBug; // Only Product Bug without Test Bug/Environment
                    })();
                    return (
                      <tr key={tc.test_name}>
                        <td style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "center" }}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            disabled={!isAllowedForCheckbox}
                            onChange={() => {
                              if (!isAllowedForCheckbox) return; // Prevent changes if disabled
                              setHandoverSelectedTests((prev) => {
                                const next = new Set(prev);
                                if (next.has(tc.test_name)) {
                                  next.delete(tc.test_name);
                                } else {
                                  next.add(tc.test_name);
                                }
                                return next;
                              });
                            }}
                            style={{ 
                              width: "16px", 
                              height: "16px", 
                              cursor: (isAllowedForCheckbox && !handoverDataLocked) ? "pointer" : "not-allowed",
                              opacity: (isAllowedForCheckbox && !handoverDataLocked) ? 1 : 0.5
                            }}
                            title={handoverDataLocked ? "Data saved. Change JITA URL and Fetch to edit." : (isAllowedForCheckbox ? "Select test case" : "Only Product Bug test cases can be selected")}
                          />
                        </td>
                        <td style={{ padding: "8px", border: "1px solid #e2e8f0", wordBreak: "break-word", overflowWrap: "break-word", wordWrap: "break-word", minWidth: "130ch" }}>{tc.test_name}</td>
                        <td style={{ padding: "8px", border: "1px solid #e2e8f0" }}>{tc.passed_count != null && tc.total_count != null ? `${tc.passed_count} / ${tc.total_count}` : "-"}</td>
                        <td style={{ padding: "8px", border: "1px solid #e2e8f0", color: tc.status === "Succeeded" ? "#28a745" : "#dc3545" }}>{tc.status}</td>
                        <td style={{ padding: "8px", border: "1px solid #e2e8f0" }}>
                          <input
                            type="text"
                            value={handoverTestTickets[tc.test_name] ?? ""}
                            onChange={(e) => {
                              setHandoverTestTickets((prev) => ({ ...prev, [tc.test_name]: e.target.value }));
                              // Clear Jira validation when test tickets change (they affect Jira validation)
                              setHandoverJiraTicketValidation({});
                              setHandoverJiraSkippedMessage(null);
                            }}
                            placeholder="Jira ticket(s), comma-separated"
                            disabled={isPassed || handoverDataLocked}
                            style={{ 
                              padding: "4px 8px", 
                              fontSize: "12px", 
                              width: "100%", 
                              minWidth: "140px", 
                              maxWidth: "220px", 
                              border: "1px solid #d1d5db", 
                              borderRadius: "4px", 
                              boxSizing: "border-box",
                              backgroundColor: (isPassed || handoverDataLocked) ? "#f3f4f6" : "white",
                              cursor: (isPassed || handoverDataLocked) ? "not-allowed" : "text",
                              opacity: (isPassed || handoverDataLocked) ? 0.6 : 1
                            }}
                            title={handoverDataLocked ? "Data saved. Change JITA URL and Fetch to edit." : (isPassed ? "Ticket entry disabled for passed test cases" : "Enter Jira ticket(s), comma-separated")}
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>

              <div style={{ marginTop: "12px", display: "flex", justifyContent: "flex-end" }}>
                <button type="button" onClick={handleValidateJiraTickets} disabled={handoverJiraValidating || handoverDataLocked} style={(handoverJiraValidating || handoverDataLocked) ? { ...btnValidateDisabled } : { ...btnValidate }}>
                  {handoverJiraValidating ? "Validating..." : "Validate Jira tickets (Product Bug)"}
                </button>
              </div>
              {handoverJiraSkippedMessage && (
                <div style={{ fontSize: "13px", background: "#eff6ff", color: "#1e40af", padding: "10px 12px", borderRadius: "6px", border: "1px solid #93c5fd", marginTop: "8px" }}>
                  {handoverJiraSkippedMessage}
                </div>
              )}
              {Object.keys(handoverJiraTicketValidation).length > 0 && (
                <div style={{ fontSize: "12px", background: "#f8fafc", padding: "10px 12px", borderRadius: "6px", border: "1px solid #e2e8f0", marginTop: "8px" }}>
                  {Object.entries(handoverJiraTicketValidation).map(([ticket, v]) => (
                    <div key={ticket} style={{ marginBottom: "4px" }}>
                      <a href={`${JIRA_URL}${ticket}`} target="_blank" rel="noreferrer">{ticket}</a>
                      {v.error ? <span style={{ color: "#dc2626" }}> — {v.error}</span> : v.valid ? <span style={{ color: "#16a34a" }}> ✓ Product Bug</span> : <span style={{ color: "#b45309" }}> Not Product Bug ({v.issuetype || "—"})</span>}
                    </div>
                  ))}
                </div>
              )}

              {/* List of selected test cases for handover - show always when test cases are selected */}
              {handoverSelectedTests.size > 0 && (
                <div style={{ marginTop: "16px", padding: "10px", background: "#ffffff", borderRadius: "6px", border: "1px solid #cbd5e1" }}>
                  <div style={{ fontSize: "13px", fontWeight: "600", marginBottom: "8px", color: "#475569" }}>
                    Selected Test Cases for Handover ({handoverSelectedTests.size}):
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: "4px", fontSize: "12px", color: "#334155" }}>
                    {Array.from(handoverSelectedTests)
                      .filter((testName) => handoverAnalysis.test_cases.some((tc) => tc.test_name === testName))
                      .map((testName) => {
                        const tc = handoverAnalysis.test_cases.find((t) => t.test_name === testName);
                        return (
                          <div key={testName} style={{ padding: "4px 8px", background: "#f1f5f9", borderRadius: "4px", display: "flex", alignItems: "center", gap: "8px" }}>
                            <span style={{ flex: 1, minWidth: "130ch", wordBreak: "break-word", overflowWrap: "break-word", wordWrap: "break-word" }}>{testName}</span>
                            {tc && (
                              <span style={{ fontSize: "11px", color: "#64748b" }}>
                                ({tc.passed_count != null && tc.total_count != null ? `${tc.passed_count}/${tc.total_count}` : "-"})
                              </span>
                            )}
                          </div>
                        );
                      })}
                  </div>
                </div>
              )}

              {(() => {
                // Check selected test cases
                const selectedTestCases = handoverAnalysis.test_cases?.filter((tc) => 
                  handoverSelectedTests.has(tc.test_name)
                ) || [];
                
                // If no test cases selected, hide override section
                if (selectedTestCases.length === 0) {
                  return null;
                }
                
                // Check if ALL selected test cases are passed
                const allSelectedArePassed = selectedTestCases.every((tc) => {
                  const passCount = tc.passed_count || 0;
                  const status = (tc.status || "").toLowerCase();
                  return status === "succeeded" || passCount >= 2;
                });
                
                // Show override section ONLY if there are FAILED test cases (i.e., NOT all are passed)
                // If all selected are passed, don't show override section
                if (allSelectedArePassed) {
                  return null;
                }
                
                return (
                  <div style={{ marginTop: "16px", padding: "12px 16px", background: "#f8fafc", borderRadius: "8px", border: "1px solid #e2e8f0" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap" }}>
                      <span style={{ fontSize: "14px", fontWeight: "600" }}>Override (Only with Product Bugs):</span>
                      <button
                        type="button"
                        onClick={handleOverrideFetch}
                        disabled={handoverFetchingOverride || handoverDataLocked}
                        style={(handoverFetchingOverride || handoverDataLocked) ? { ...btnValidateDisabled } : { ...btnValidate }}
                      >
                        {handoverFetchingOverride ? "Checking..." : "Check Override"}
                      </button>
                    </div>
                    {handoverOverrideResult && (
                      <div style={{ marginTop: "12px", padding: "10px", background: handoverOverrideResult.allowed ? "#ecfdf5" : "#fef2f2", borderRadius: "6px", border: `1px solid ${handoverOverrideResult.allowed ? "#10b981" : "#f87171"}`, fontSize: "13px" }}>
                        <div style={{ fontWeight: "600", marginBottom: "4px", color: handoverOverrideResult.allowed ? "#065f46" : "#991b1b" }}>
                          {handoverOverrideResult.allowed ? "✓ Override Allowed" : "✗ Override Not Allowed"}
                        </div>
                        <div style={{ color: handoverOverrideResult.allowed ? "#047857" : "#dc2626" }}>{handoverOverrideResult.message}</div>
                        {handoverOverrideResult.ticketValidations && Object.keys(handoverOverrideResult.ticketValidations).length > 0 && (
                          <div style={{ marginTop: "8px", fontSize: "12px" }}>
                            {Object.entries(handoverOverrideResult.ticketValidations).map(([ticket, v]) => (
                              <div key={ticket} style={{ marginBottom: "2px" }}>
                                <a href={`${JIRA_URL}${ticket}`} target="_blank" rel="noreferrer">{ticket}</a>
                                {v.error ? <span style={{ color: "#dc2626" }}> — {v.error}</span> : v.valid ? <span style={{ color: "#16a34a" }}> ✓ Product Bug</span> : <span style={{ color: "#b45309" }}> — {v.issuetype || "Not Product Bug"}</span>}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}

              {(() => {
                // Check selected test cases
                const selectedTestCases = handoverAnalysis.test_cases?.filter((tc) => 
                  handoverSelectedTests.has(tc.test_name)
                ) || [];
                
                // If no test cases selected, hide CR section
                if (selectedTestCases.length === 0) {
                  return null;
                }
                
                const allSelectedArePassed = selectedTestCases.every((tc) => {
                  const passCount = tc.passed_count || 0;
                  const status = (tc.status || "").toLowerCase();
                  return status === "succeeded" || passCount >= 2;
                });
                
                // Check if there are failed test cases selected (not passed)
                const hasFailedTestCases = selectedTestCases.some((tc) => {
                  const passCount = tc.passed_count || 0;
                  const status = (tc.status || "").toLowerCase();
                  const isPassed = status === "succeeded" || passCount >= 2;
                  return !isPassed; // Failed test case
                });
                
                // Show CR section if:
                // 1. All tests passed (from analysis), OR
                // 2. Override saved (for failed cases), OR
                // 3. Only passed test cases selected (direct CR, no override needed)
                const shouldShowCR = handoverAnalysis.all_tests_passed || 
                                     (hasFailedTestCases && handoverOverrideSave) || 
                                     (allSelectedArePassed && !hasFailedTestCases);
                
                // Determine heading and styling based on selection
                // If only passed are selected, always show "Ready for CR"
                // If both passed and failed are selected (or override saved with failed cases), show "Override"
                // Priority: If all selected are passed, always show "Ready for CR"
                let headingText, bgColor, borderColor;
                if (allSelectedArePassed) {
                  // Only passed test cases selected - show "Ready for CR"
                  headingText = "✓ Ready for CR";
                  bgColor = "#ecfdf5";
                  borderColor = "#10b981";
                } else {
                  // Has failed test cases or override saved - show "Override"
                  headingText = "⚠ Override";
                  bgColor = "#fefce8";
                  borderColor = "#eab308";
                }
                
                return shouldShowCR ? (
                <div style={{ marginTop: "20px", padding: "16px", background: bgColor, borderRadius: "8px", border: `2px solid ${borderColor}` }}>
                  <h4 style={{ marginTop: 0, marginBottom: "12px" }}>{headingText}</h4>
                  <div ref={handoverBranchContainerRef} style={{ marginBottom: "10px", maxWidth: "360px", position: "relative" }}>
                    <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>Branch <span style={{ color: "#dc2626" }}>*</span></label>
                    <input
                      type="text"
                      value={handoverCreateLstBranch}
                      onChange={(e) => { setHandoverCreateLstBranch(e.target.value); setHandoverValidation(null); }}
                      onFocus={() => { if (handoverBranchSuggestions.length > 0) setHandoverShowBranchDropdown(true); }}
                      placeholder="master"
                      disabled={handoverDataLocked}
                      style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", backgroundColor: handoverDataLocked ? "#f3f4f6" : "white", opacity: handoverDataLocked ? 0.7 : 1 }}
                    />
                    {handoverShowBranchDropdown && !handoverDataLocked && (
                      <div style={{ position: "absolute", top: "100%", left: 0, right: 0, maxHeight: "220px", overflowY: "auto", background: "white", border: "1px solid #d1d5db", borderRadius: "4px", boxShadow: "0 4px 6px rgba(0,0,0,0.1)", zIndex: 1000, marginTop: "2px" }}>
                        {handoverBranchLoading ? (
                          <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>Searching branches...</div>
                        ) : handoverBranchSuggestions.length === 0 ? (
                          <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>No branch suggestions</div>
                        ) : (
                          handoverBranchSuggestions.map((b) => (
                            <button
                              key={b}
                              type="button"
                              onClick={() => {
                                setHandoverCreateLstBranch(b);
                                setHandoverShowBranchDropdown(false);
                                setHandoverValidation(null);
                              }}
                              style={{ width: "100%", textAlign: "left", padding: "8px 12px", fontSize: "13px", cursor: "pointer", border: "none", borderBottom: "1px solid #f1f5f9", background: b === handoverCreateLstBranch ? "#e0f2fe" : "white" }}
                            >
                              {b}
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                  <div style={{ marginBottom: "10px" }}>
                    <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>LST File Path *</label>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", width: "100%" }}>
                      <input
                      type="text"
                      value={handoverCreateLstFile}
                      onChange={(e) => { setHandoverCreateLstFile(e.target.value); setHandoverValidation(null); }}
                      placeholder="e.g. test_sets/milestones/7.3.0.98/zookeeper.lst"
                      disabled={handoverDataLocked}
                      style={{ padding: "8px 12px", fontSize: "13px", width: "100%", flex: 1, minWidth: "420px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box", backgroundColor: handoverDataLocked ? "#f3f4f6" : "white", opacity: handoverDataLocked ? 0.7 : 1 }}
                    />
                      <button
                        type="button"
                        disabled={handoverDataLocked || !(handoverCreateLstFile || "").trim()}
                        onClick={() => {
                          const f = (handoverCreateLstFile || "").trim();
                          if (!f) return;
                          setHandoverCreateLstFiles((prev) => Array.from(new Set([...(prev || []), f])));
                          setHandoverCreateLstFile("");
                          setHandoverValidation(null);
                        }}
                        style={handoverDataLocked || !(handoverCreateLstFile || "").trim() ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                      >
                        Add LST
                      </button>
                    </div>
                    {getResolvedLstFiles().length > 0 && (
                      <div style={{ marginTop: "8px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
                        {getResolvedLstFiles().map((f) => (
                          <span key={f} style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 8px", borderRadius: "999px", background: "#ecfeff", border: "1px solid #a5f3fc", color: "#155e75", fontSize: "12px" }}>
                            {f}
                            {!handoverDataLocked && (
                              <button
                                type="button"
                                onClick={() => {
                                  setHandoverCreateLstFiles((prev) => (prev || []).filter((x) => x !== f));
                                  if ((handoverCreateLstFile || "").trim() === f) setHandoverCreateLstFile("");
                                  setHandoverValidation(null);
                                }}
                                style={{ border: "none", background: "none", cursor: "pointer", color: "#0e7490" }}
                              >
                                ×
                              </button>
                            )}
                          </span>
                        ))}
                      </div>
                    )}
                    <div style={{ marginTop: "8px", display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
                      <button
                        type="button"
                        onClick={() => handleSuggestLstFile({ silent: false })}
                        disabled={handoverDataLocked || handoverSuggestingLst}
                        style={handoverDataLocked || handoverSuggestingLst ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                      >
                        {handoverSuggestingLst ? "Refreshing..." : "Refresh Suggestion"}
                      </button>
                      {handoverLstSuggestion?.message && (
                        <span style={{ fontSize: "12px", color: "#475569" }}>{handoverLstSuggestion.message}</span>
                      )}
                    </div>
                    {Array.isArray(handoverLstSuggestion?.candidates) && handoverLstSuggestion.candidates.length > 0 && (
                      <div style={{ marginTop: "8px", padding: "10px", border: "1px solid #dbeafe", borderRadius: "6px", background: "#f8fbff", width: "100%" }}>
                        <div style={{ fontSize: "12px", color: "#1e3a8a", fontWeight: 600, marginBottom: "6px" }}>
                          Click to select suggested LST files (you can select multiple)
                        </div>
                        {handoverLstSuggestion.candidates.slice(0, 4).map((c) => {
                          const file = c.lst_file || "";
                          const selected = getResolvedLstFiles().includes(file);
                          return (
                            <button
                              key={file}
                              type="button"
                              disabled={handoverDataLocked}
                              onClick={() => {
                                if (!file) return;
                                if (selected) {
                                  setHandoverCreateLstFiles((prev) => (prev || []).filter((x) => x !== file));
                                } else {
                                  setHandoverCreateLstFiles((prev) => Array.from(new Set([...(prev || []), file])));
                                }
                                setHandoverCreateLstFile(file);
                                setHandoverValidation(null);
                              }}
                              style={{
                                width: "100%",
                                textAlign: "left",
                                marginBottom: "6px",
                                padding: "8px 10px",
                                borderRadius: "6px",
                                border: selected ? "1px solid #0284c7" : "1px solid #cbd5e1",
                                background: selected ? "#e0f2fe" : "#ffffff",
                                color: "#0f172a",
                                cursor: "pointer",
                                fontSize: "12px",
                              }}
                            >
                              <span style={{ fontWeight: selected ? 700 : 500 }}>{selected ? "✓ " : ""}{file}</span>{" "}
                              <span style={{ color: "#64748b" }}>({c.count} matching testcase{c.count === 1 ? "" : "s"})</span>
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                  <div style={{ marginBottom: "10px", display: "flex", gap: "12px", flexWrap: "wrap" }}>
                    <div style={{ flex: 1, minWidth: "200px" }}>
                      <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Commit Note (optional)</label>
                      <input type="text" value={handoverCommitMessage} onChange={(e) => {
                        setHandoverCommitMessage(e.target.value);
                        // Commit message doesn't affect validation, so no need to clear
                      }} placeholder="Optional note appended after preview template" disabled={handoverDataLocked} style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box", backgroundColor: handoverDataLocked ? "#f3f4f6" : "white", opacity: handoverDataLocked ? 0.7 : 1 }} />
                    </div>
                  </div>
                  <div style={{ marginBottom: "10px" }}>
                    <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Handover ticket(s), comma-separated <span style={{ color: "#dc2626" }}>*</span></label>
                    <input type="text" value={handoverTicketsExtra} onChange={(e) => { setHandoverTicketsExtra(e.target.value); }} placeholder="ENG-123, ENG-456" disabled={handoverDataLocked} style={{ padding: "8px 12px", fontSize: "13px", width: "100%", maxWidth: "400px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box", backgroundColor: handoverDataLocked ? "#f3f4f6" : "white", opacity: handoverDataLocked ? 0.7 : 1 }} />
                  </div>
                  <div style={{ marginBottom: "10px" }}>
                    <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Reviewers (type name to search)</label>
                    <ReviewerAutocomplete value={handoverReviewers} onChange={setHandoverReviewers} placeholder="Type name (e.g. john) to search..." disabled={handoverDataLocked} />
                  </div>
                  <div style={{ display: "flex", gap: "10px", marginBottom: "12px", flexWrap: "wrap" }}>
                    {(() => {
                      // Check all mandatory fields before enabling Validate LST button
                      const hasLstFile = getResolvedLstFiles().length > 0;
                      const hasBranch = handoverCreateLstBranch.trim() !== "";
                      const hasHandoverTickets = handoverTicketsExtra.trim() !== "";
                      
                      // Button is disabled if any mandatory field is missing
                      const isValidateLstDisabled = handoverValidating || handoverDataLocked || !hasLstFile || !hasBranch || !hasHandoverTickets;
                      
                      return (
                        <button 
                          onClick={handleValidateLst} 
                          disabled={isValidateLstDisabled} 
                          style={isValidateLstDisabled ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                          title={isValidateLstDisabled ? (
                            !hasLstFile ? "Please enter LST File Path" :
                            !hasBranch ? "Please enter Branch" :
                            !hasHandoverTickets ? "Please enter Handover ticket(s)" :
                            "Validating..."
                          ) : ""}
                        >
                          {handoverValidating ? "Validating..." : "Validate LST"}
                        </button>
                      );
                    })()}
                  </div>
                  {handoverValidation && (
                    <div style={{ marginBottom: "12px", padding: "10px", background: handoverValidation.file_valid === true && handoverValidation.branch_valid === true ? "#ecfdf5" : "#f8fafc", borderRadius: "4px", border: "1px solid #e2e8f0", fontSize: "13px" }}>
                      {handoverValidation.file_valid === true && handoverValidation.branch_valid === true ? (
                        <span style={{ color: "#166534" }}>✓ Branch and file validated.</span>
                      ) : (
                        <>
                          {handoverValidation.branch_valid != null && <span>Branch: {handoverValidation.branch_valid === true ? "✓" : "✗"} </span>}
                          {handoverValidation.file_valid != null && <span>File: {handoverValidation.file_valid === true ? "✓" : "✗"}</span>}
                          {handoverValidation.error && (
                            <div style={{ marginTop: "6px", color: "#dc2626", fontSize: "12px" }}>{handoverValidation.error}</div>
                          )}
                          {handoverValidation.message && (
                            <div style={{ marginTop: "6px", color: "#475569" }}>{handoverValidation.message}</div>
                          )}
                          {!handoverValidation.message && handoverValidation.branch_error && (
                            <div style={{ marginTop: "4px", color: "#dc2626", fontSize: "12px" }}>{handoverValidation.branch_error}</div>
                          )}
                          {!handoverValidation.message && handoverValidation.file_error && handoverValidation.file_error !== handoverValidation.branch_error && (
                            <div style={{ marginTop: "4px", color: "#dc2626", fontSize: "12px" }}>{handoverValidation.file_error}</div>
                          )}
                          {Array.isArray(handoverValidation.files) && handoverValidation.files.length > 0 && (
                            <div style={{ marginTop: "8px", fontSize: "12px" }}>
                              {handoverValidation.files.map((f) => (
                                <div key={f.lst_file} style={{ marginBottom: "2px", color: f.file_valid && f.branch_valid ? "#166534" : "#b91c1c" }}>
                                  {(f.file_valid && f.branch_valid) ? "✓" : "✗"} {f.lst_file}
                                </div>
                              ))}
                            </div>
                          )}
                        </>
                      )}
                      {handoverValidation.sourcegraph_url && <div style={{ marginTop: "8px" }}><a href={handoverValidation.sourcegraph_url} target="_blank" rel="noreferrer">Verify in Sourcegraph →</a></div>}
                    </div>
                  )}
                  {/* Validation requirements check */}
                  {(() => {
                    // When ALL selected test cases are passed: Jira validation is NOT required (user can handover passed-only without Jira tickets)
                    const selectedTestCases = handoverAnalysis.test_cases?.filter((tc) => handoverSelectedTests.has(tc.test_name)) || [];
                    const allSelectedArePassed = selectedTestCases.length > 0 && selectedTestCases.every((tc) => {
                      const passCount = tc.passed_count || 0;
                      const status = (tc.status || "").toLowerCase();
                      return status === "succeeded" || passCount >= 2;
                    });
                    
                    // Step 1: Jira validation is required only when there are failed test cases (needs Product Bug tickets)
                    const hasJiraValidation = (Object.keys(handoverJiraTicketValidation).length > 0 || handoverJiraSkippedMessage) ? true : false;
                    const jiraValidationRequired = !allSelectedArePassed;
                    
                    // Step 2: LST validation must have both file_valid AND branch_valid as true
                    const hasLstValidation = handoverValidation !== null && 
                                             handoverValidation !== undefined &&
                                             handoverValidation.file_valid === true && 
                                             handoverValidation.branch_valid === true &&
                                             !handoverValidation.error;
                    
                    // Step 3: Enable "Record Handover" - Jira validation only required when selection includes failed tests
                    const isButtonDisabled = handoverCreateLstLoading || 
                                            handoverDataLocked ||
                                            getResolvedLstFiles().length === 0 || 
                                            (jiraValidationRequired && !hasJiraValidation) || 
                                            !hasLstValidation;
                    
                    return (
                      <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "12px", alignItems: "center" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                          <button
                            type="button"
                            onClick={openCrPreview}
                            disabled={handoverDataLocked || handoverCreateLstLoading}
                            style={handoverDataLocked || handoverCreateLstLoading ? { ...btnValidateDisabled } : { ...btnValidate }}
                          >
                            Preview CR
                          </button>
                          <button 
                            onClick={handleRecordHandoverAndCreateCR} 
                            disabled={isButtonDisabled} 
                            style={isButtonDisabled ? { ...btnPrimaryDisabled } : { ...btnPrimary }}
                            title={isButtonDisabled ? (jiraValidationRequired && !hasJiraValidation ? "Step 1: Please validate Jira tickets first (required for failed test cases)" : (!hasLstValidation ? "Step 2: Please validate LST file" : "")) : ""}
                          >
                            {handoverCreateLstLoading ? "Processing..." : "Record Handover | Create CR"}
                          </button>
                          {allSelectedArePassed && !hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#64748b", fontStyle: "italic" }}>
                              Passed tests only — Validate LST file to proceed
                            </span>
                          )}
                          {allSelectedArePassed && hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#16a34a", fontStyle: "italic", fontWeight: "500" }}>
                              ✓ Ready for handover
                            </span>
                          )}
                          {!allSelectedArePassed && hasJiraValidation && !hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#64748b", fontStyle: "italic" }}>
                              ✓ Jira validated. Next: Validate LST file
                            </span>
                          )}
                          {!allSelectedArePassed && !hasJiraValidation && (
                            <span style={{ fontSize: "11px", color: "#64748b", fontStyle: "italic" }}>
                              Step 1: Validate Jira tickets first (required for failed test cases)
                            </span>
                          )}
                          {!allSelectedArePassed && hasJiraValidation && hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#16a34a", fontStyle: "italic", fontWeight: "500" }}>
                              ✓ Both validations complete
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                  {handoverCrPreviewOpen && (
                    <div style={{ marginTop: "12px", padding: "12px", border: "1px solid #cbd5e1", borderRadius: "8px", background: "#f8fafc" }}>
                      <h5 style={{ margin: "0 0 10px 0", fontSize: "14px", color: "#0f172a" }}>CR Preview (editable)</h5>
                      <div style={{ marginBottom: "8px" }}>
                        <label style={{ display: "block", fontSize: "12px", marginBottom: "4px", color: "#334155" }}>Subject</label>
                        <input
                          type="text"
                          value={handoverCrSubject}
                          onChange={(e) => setHandoverCrSubject(e.target.value)}
                          disabled={handoverDataLocked}
                          style={{ width: "100%", maxWidth: "560px", padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: "4px", fontSize: "13px" }}
                        />
                      </div>
                      <div style={{ marginBottom: "8px" }}>
                        <label style={{ display: "block", fontSize: "12px", marginBottom: "4px", color: "#334155" }}>Description</label>
                        <textarea
                          value={handoverCrDescription}
                          onChange={(e) => setHandoverCrDescription(e.target.value)}
                          rows={8}
                          disabled={handoverDataLocked}
                          style={{ width: "100%", maxWidth: "760px", padding: "8px 10px", border: "1px solid #d1d5db", borderRadius: "4px", fontSize: "13px", fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" }}
                        />
                      </div>
                      <div style={{ display: "flex", gap: "8px" }}>
                        <button
                          type="button"
                          onClick={() => {
                            const selectedTests = getSelectedHandoverTests();
                            setHandoverCrDescription(buildDefaultCrDescription());
                          }}
                          disabled={handoverDataLocked}
                          style={handoverDataLocked ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                        >
                          Reset Template
                        </button>
                        <button
                          type="button"
                          onClick={() => setHandoverCrPreviewOpen(false)}
                          style={{ ...btnSecondary, padding: "9px 16px" }}
                        >
                          Save & Close
                        </button>
                      </div>
                    </div>
                  )}
                </div>
                ) : null;
              })()}

              {handoverCrResult && (
                <div style={{ marginTop: "16px", padding: "12px", background: handoverCrResult.success ? "#ecfdf5" : "#fef2f2", borderRadius: "8px", border: "1px solid " + (handoverCrResult.success ? "#10b981" : "#f87171") }}>
                  {handoverCrResult.success ? (
                    <p style={{ margin: 0 }}>✓ {handoverCrResult.message} {handoverCrResult.cr_url && <a href={handoverCrResult.cr_url} target="_blank" rel="noreferrer">View CR</a>}</p>
                  ) : (
                    <p style={{ margin: 0 }}>{handoverCrResult.error || handoverCrResult.message} {handoverCrResult.raw_error && <span style={{ fontSize: "12px", color: "#64748b" }}>{handoverCrResult.raw_error}</span>}</p>
                  )}
                </div>
              )}
              {handoverManualLstInstructions && (
                <div style={{ marginTop: "16px", padding: "12px", background: "#fffbeb", borderRadius: "8px", border: "1px solid #fbbf24", fontSize: "13px" }}>
                  <strong>Manual steps</strong>
                  {Array.isArray(handoverManualLstInstructions.manual_steps) && (
                    <div style={{ whiteSpace: "pre-wrap", margin: "8px 0 0 0" }}>{handoverManualLstInstructions.manual_steps.join("\n")}</div>
                  )}
                  {handoverManualLstInstructions.copy_paste_block && (
                    <pre style={{ marginTop: "8px", background: "#fef3c7", padding: "8px", borderRadius: "4px", overflow: "auto", fontSize: "12px" }}>{handoverManualLstInstructions.copy_paste_block}</pre>
                  )}
                  {!Array.isArray(handoverManualLstInstructions.manual_steps) && !handoverManualLstInstructions.copy_paste_block && (
                    <pre style={{ whiteSpace: "pre-wrap", margin: "8px 0 0 0" }}>{JSON.stringify(handoverManualLstInstructions, null, 2)}</pre>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
        </>
      )}

      {activeTab === "deprecation" && (
        <div>
          <p className="ho-subtitle ho-intro">
            Search by test name(s). On Search, Sourcegraph is queried in <strong>nutest-py3-tests</strong> first to find which .lst file(s) contain the test; that list is shown below. Handover data (LST file, date, ticket(s), by whom) is shown from the local DB. Use + to add more test name inputs.
          </p>
          <div className="ho-card">
            <div className="ho-card__title">Find test cases</div>
            {(deprecationSearchQueries || [""]).map((query, idx) => (
              <div key={idx} style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px", flexWrap: "wrap" }}>
                <input
                  type="text"
                  value={query}
                  onChange={(e) => {
                    const next = [...(deprecationSearchQueries || [""])];
                    next[idx] = e.target.value;
                    setDeprecationSearchQueries(next);
                  }}
                  placeholder={idx === 0 ? "Test name(s), e.g. test_a, test_b" : "Another test name(s)"}
                  style={{ flex: 1, minWidth: "280px", padding: "8px 12px", fontSize: "14px", border: "1px solid #ddd", borderRadius: "4px", boxSizing: "border-box" }}
                  onKeyPress={(e) => e.key === "Enter" && handleDeprecationSearch()}
                />
                {idx === (deprecationSearchQueries || [""]).length - 1 ? (
                  <button type="button" onClick={() => setDeprecationSearchQueries((prev) => [...(prev || [""]), ""])} style={{ padding: "8px 14px", background: "#0d9488", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>+</button>
                ) : (deprecationSearchQueries || [""]).length > 1 ? (
                  <button type="button" onClick={() => setDeprecationSearchQueries((prev) => prev.filter((_, i) => i !== idx))} style={{ padding: "6px 10px", background: "#f87171", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}>×</button>
                ) : null}
              </div>
            ))}
            <div style={{ display: "flex", gap: "12px", marginTop: "12px", flexWrap: "wrap", justifyContent: "flex-end" }}>
              <button
                onClick={handleDeprecationSearch}
                disabled={loadingDeprecationSearch}
                style={{ padding: "8px 16px", background: loadingDeprecationSearch ? "#94a3b8" : "#0d9488", color: "white", border: "none", borderRadius: "4px", cursor: loadingDeprecationSearch ? "not-allowed" : "pointer", fontWeight: "500" }}
              >
                {loadingDeprecationSearch ? "Searching..." : "Search"}
              </button>
            </div>
          </div>

          {deprecationResults && (
            <div>
              {deprecationResults.error ? (
                <div style={{ color: "#dc3545", padding: "8px", fontSize: "14px" }}>{deprecationResults.error}</div>
              ) : (
                <>
                  {/* LST file(s) containing this test — from Sourcegraph (shown first) */}
                  {(deprecationResults.sourcegraph_first_repo?.length > 0 || deprecationResults.sourcegraph_other_repos?.length > 0) ? (
                    <div style={{ marginBottom: "16px", padding: "12px", background: "#f0fdf4", borderRadius: "6px", border: "1px solid #bbf7d0" }}>
                      <div style={{ fontWeight: "600", marginBottom: "8px", color: "#166534" }}>LST file(s) containing this test (Sourcegraph)</div>
                      <p style={{ margin: "0 0 8px 0", fontSize: "13px", color: "#15803d" }}>The test name was found in these .lst files in nutest-py3-tests (and other repos) via Sourcegraph.</p>
                      {deprecationResults.sourcegraph_first_repo?.length > 0 && (
                        <div style={{ marginBottom: "8px" }}>
                          <span style={{ fontSize: "12px", color: "#15803d", fontWeight: "500" }}>
                            {deprecationResults.sourcegraph_first_repo_name || "nutest-py3-tests"} — {deprecationResults.sourcegraph_first_repo.length} LST file(s):
                          </span>
                          <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "13px" }}>
                            {deprecationResults.sourcegraph_first_repo.map((h, i) => (
                              <li key={i}><code style={{ background: "#dcfce7", padding: "2px 6px", borderRadius: "3px" }}>{h.path}</code></li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {deprecationResults.sourcegraph_other_repos?.length > 0 && (
                        <div>
                          <span style={{ fontSize: "12px", color: "#15803d", fontWeight: "500" }}>Other repos — {deprecationResults.sourcegraph_other_repos.length} LST file(s):</span>
                          <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "13px" }}>
                            {deprecationResults.sourcegraph_other_repos.map((h, i) => (
                              <li key={i}><code style={{ background: "#dcfce7", padding: "2px 6px", borderRadius: "3px" }}>{h.path}</code> <span style={{ color: "#64748b" }}>({h.repo})</span></li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div style={{ marginBottom: "16px", padding: "12px", background: "#fef3c7", borderRadius: "6px", border: "1px solid #fcd34d", fontSize: "13px", color: "#92400e" }}>
                      <strong>LST files (Sourcegraph):</strong> No .lst file containing this test name was found in nutest-py3-tests (or other configured repos). The test may not be in an LST file yet, or SOURCEGRAPH_TOKEN may not be set in backend config.
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center", gap: "12px", flexWrap: "wrap", marginBottom: "8px" }}>
                    <span style={{ fontSize: "14px", color: "#555" }}>
                      {(deprecationResults.count ?? deprecationResults.results?.length ?? 0) === 0 ? "No handover records found." : "Found " + (deprecationResults.count ?? deprecationResults.results?.length ?? 0) + " handover record(s)."}
                    </span>
                    {deprecationResults.results?.length > 0 && (
                      <button
                        type="button"
                        onClick={() => setDeprecationEditMode((prev) => !prev)}
                        style={{ padding: "6px 12px", background: deprecationEditMode ? "#64748b" : "#0d9488", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "13px" }}
                      >
                        {deprecationEditMode ? "Done" : "Edit"}
                      </button>
                    )}
                  </div>

                  {deprecationResults.results?.length > 0 && (() => {
                    const records = deprecationResults.results;
                    const recordKeys = records.map((r) => getDeprecationRecordKey(r));
                    const allSelected = recordKeys.length > 0 && recordKeys.every((k) => deprecationSelectedRecordKeys.has(k));
                    return (
                      <table className="ho-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px", marginBottom: "20px" }}>
                        <thead>
                          <tr style={{ background: "#f1f5f9" }}>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", width: "40px", textAlign: "center" }}>
                              <input
                                type="checkbox"
                                checked={allSelected}
                                onChange={(e) => {
                                  if (e.target.checked) {
                                    setDeprecationSelectedRecordKeys(new Set(recordKeys));
                                    const firstLst = (deprecationResults.results || []).map((r) => (r.lst_file || "").trim()).find(Boolean);
                                    if (firstLst) setDeprecationLstFile((prev) => (prev && prev.trim()) ? prev : firstLst);
                                  } else {
                                    setDeprecationSelectedRecordKeys(new Set());
                                  }
                                }}
                                style={{ width: "16px", height: "16px", cursor: "pointer" }}
                                title="Select for Create CR"
                              />
                            </th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left", minWidth: "130ch" }}>Test name</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left" }}>LST file</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left" }}>Branch</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left", minWidth: "120px" }}>Handover date</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left", minWidth: "150px" }}>Handover Ticket(s)</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left", minWidth: "150px" }}>Bug Ticket</th>
                            <th style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "left" }}>By whom</th>
                            {deprecationEditMode && <th style={{ padding: "8px", border: "1px solid #e2e8f0", width: "90px" }}>Actions</th>}
                          </tr>
                        </thead>
                        <tbody>
                          {records.map((r, idx) => {
                            const testName = (r.test_name || "").trim();
                            const recordKey = getDeprecationRecordKey(r);
                            const rowKey = `${recordKey}-${idx}`;
                            const isSelected = deprecationSelectedRecordKeys.has(recordKey);
                            const tickets = r.tickets || [];
                            const byWhom = formatByWhom(r.by_whom);
                            return (
                              <tr key={rowKey}>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", textAlign: "center" }}>
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => {
                                      setDeprecationSelectedRecordKeys((prev) => {
                                        const next = new Set(prev);
                                        if (next.has(recordKey)) {
                                          next.delete(recordKey);
                                        } else {
                                          next.add(recordKey);
                                          const lstFile = (r.lst_file || "").trim();
                                          if (lstFile) setDeprecationLstFile((p) => (p && p.trim()) ? p : lstFile);
                                        }
                                        return next;
                                      });
                                    }}
                                    style={{ width: "16px", height: "16px", cursor: "pointer" }}
                                    title="Select for Create CR"
                                  />
                                </td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", wordBreak: "break-word", overflowWrap: "break-word", wordWrap: "break-word", minWidth: "130ch" }}>{testName}</td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px" }}>{(r.lst_file || "").trim() || "-"}</td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px" }}>{(r.branch || "").trim() || "-"}</td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px", whiteSpace: "nowrap" }}>{formatDateIST(r.handover_date)}</td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px", verticalAlign: "top", minWidth: "150px" }}>
                                  <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", alignItems: "flex-start" }}>
                                    {/* Show handover_tickets if available, otherwise fall back to empty (old records won't have this) */}
                                    {(r.handover_tickets || []).length ? (r.handover_tickets || []).map((t) => (
                                      <a key={t} href={`${JIRA_URL}${t}`} target="_blank" rel="noreferrer" style={{ marginRight: "6px", display: "inline-block", whiteSpace: "nowrap" }}>{t}</a>
                                    )) : <span style={{ color: "#94a3b8" }}>-</span>}
                                  </div>
                                </td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px", verticalAlign: "top", minWidth: "150px" }}>
                                  <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                                    {/* Show bug_tickets if available, otherwise fall back to tickets (for backward compatibility) */}
                                    {((r.bug_tickets || []).length > 0 || (tickets.length > 0 && !r.handover_tickets)) ? (
                                      <>
                                        {(r.bug_tickets || tickets || []).map((t) => (
                                          <a key={t} href={`${JIRA_URL}${t}`} target="_blank" rel="noreferrer" style={{ display: "inline-block", whiteSpace: "nowrap" }}>{t}</a>
                                        ))}
                                        {r.bug_type && (
                                          <span style={{
                                            padding: "2px 6px",
                                            fontSize: "11px",
                                            fontWeight: "500",
                                            borderRadius: "3px",
                                            background: "#ecfdf5",
                                            color: "#065f46",
                                            border: "1px solid #d1fae5",
                                            display: "inline-block",
                                            whiteSpace: "nowrap",
                                            marginTop: "4px"
                                          }}>
                                            {r.bug_type}
                                          </span>
                                        )}
                                      </>
                                    ) : <span style={{ color: "#94a3b8" }}>-</span>}
                                  </div>
                                </td>
                                <td style={{ padding: "8px", border: "1px solid #e2e8f0", fontSize: "12px" }}>{byWhom !== "-" ? byWhom : "-"}</td>
                                {deprecationEditMode && (
                                  <td style={{ padding: "8px", border: "1px solid #e2e8f0" }}>
                                    <button type="button" onClick={() => handleDeprecationDeleteAll(testName, [r])} style={{ padding: "4px 10px", background: "#dc2626", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "12px" }}>Delete</button>
                                  </td>
                                )}
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    );
                  })()}

                  {deprecationResults?.results?.length > 0 && (() => {
                    const selectedTestNames = [...new Set((deprecationResults.results || []).filter((r) => deprecationSelectedRecordKeys.has(getDeprecationRecordKey(r))).map((r) => (r.test_name || "").trim()))];
                    const selectedCount = selectedTestNames.length;
                    return (
                      <div style={{ marginTop: "20px", padding: "16px", background: "#ecfdf5", borderRadius: "8px", border: "2px solid #10b981" }}>
                        <h4 style={{ marginTop: 0, marginBottom: "8px", color: "#065f46" }}>Deprecate — Remove {selectedCount} selected test(s) from LST file</h4>
                        <p style={{ marginBottom: "12px", fontSize: "14px", color: "#047857" }}>Enter LST file path and branch. Click &quot;Validate LST&quot; to check whether the selected testcases are present in that LST file. Then create a Gerrit CR to remove them.</p>
                        {selectedCount > 0 && (
                          <div style={{ marginBottom: "10px" }}>
                            <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>LST File Path</label>
                            <input
                              type="text"
                              value={deprecationLstFile}
                              onChange={(e) => { setDeprecationLstFile(e.target.value); setDeprecationValidation(null); setDeprecationCrResult(null); }}
                              placeholder="e.g. test_sets/milestones/7.3.0.98/zookeeper.lst"
                              style={{ padding: "8px 12px", fontSize: "13px", width: "100%", maxWidth: "500px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }}
                            />
                          </div>
                        )}
                        <div style={{ marginBottom: "10px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
                          <div>
                            <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Branch</label>
                            <input type="text" value={deprecationLstBranch} onChange={(e) => { setDeprecationLstBranch(e.target.value); setDeprecationValidation(null); }} placeholder="master" style={{ padding: "8px 12px", fontSize: "13px", width: "150px", border: "1px solid #d1d5db", borderRadius: "4px" }} />
                          </div>
                          <div style={{ flex: 1, minWidth: "200px" }}>
                            <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Commit Message</label>
                            <input type="text" value={deprecationCommitMessage} onChange={(e) => setDeprecationCommitMessage(e.target.value)} placeholder="Optional" style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }} />
                          </div>
                          <button onClick={handleDeprecationValidateLst} disabled={deprecationValidating || selectedCount === 0 || !deprecationLstFile.trim()} style={(deprecationValidating || selectedCount === 0 || !deprecationLstFile.trim()) ? { ...btnTertiaryDisabled } : { ...btnTertiary }}>
                            {deprecationValidating ? "Checking..." : "Validate LST"}
                          </button>
                        </div>
                        {deprecationValidation && (
                          <div style={{ marginBottom: "16px", marginTop: "4px", padding: "14px", background: deprecationValidation.error ? "#fef2f2" : "#ffffff", borderRadius: "8px", border: "2px solid " + (deprecationValidation.error ? "#dc2626" : "#10b981"), boxShadow: "0 1px 3px rgba(0,0,0,0.1)", fontSize: "14px", color: "#0f172a" }}>
                            <div style={{ fontWeight: "700", marginBottom: "10px", color: "#0f172a", fontSize: "15px" }}>Is selected testcase present in LST?</div>
                            {deprecationValidation.error ? (
                              <div style={{ color: "#b91c1c" }}>{deprecationValidation.error}</div>
                            ) : (
                              <table style={{ width: "100%", minWidth: "280px", borderCollapse: "collapse", fontSize: "14px" }}>
                                <thead>
                                  <tr style={{ borderBottom: "2px solid #10b981", color: "#0f172a" }}>
                                    <th style={{ textAlign: "left", padding: "8px 10px", color: "#0f172a", minWidth: "130ch" }}>Testcase</th>
                                    <th style={{ textAlign: "left", padding: "8px 10px", width: "100px", color: "#0f172a" }}>In LST</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(() => {
                                    // Get all test names from test_names, present, or not_present
                                    const allTestNames = deprecationValidation.test_names || 
                                      [...(deprecationValidation.present || []), ...(deprecationValidation.not_present || [])];
                                    const presentList = (deprecationValidation.present || []).map(t => (t || "").trim());
                                    
                                    if (allTestNames.length === 0) {
                                      return (
                                        <tr>
                                          <td colSpan="2" style={{ padding: "8px 10px", color: "#64748b", textAlign: "center" }}>
                                            No test cases to display
                                          </td>
                                        </tr>
                                      );
                                    }
                                    
                                    return allTestNames.map((name) => {
                                      // Normalize test names for comparison (trim whitespace)
                                      const normalizedName = (name || "").trim();
                                      const inLst = presentList.includes(normalizedName);
                                      return (
                                        <tr key={name || Math.random()} style={{ borderBottom: "1px solid #e2e8f0" }}>
                                          <td style={{ padding: "8px 10px", color: "#0f172a", wordBreak: "break-word", overflowWrap: "break-word", wordWrap: "break-word", minWidth: "130ch" }}>{normalizedName}</td>
                                          <td style={{ padding: "8px 10px", fontWeight: "700", color: inLst ? "#047857" : "#b45309", whiteSpace: "nowrap" }}>
                                            {inLst ? "✓ Yes" : "✗ No"}
                                          </td>
                                        </tr>
                                      );
                                    });
                                  })()}
                                </tbody>
                              </table>
                            )}
                          </div>
                        )}
                        <div style={{ marginBottom: "10px" }}>
                          <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Jira ticket no.</label>
                          <input type="text" value={deprecationTicketsExtra} onChange={(e) => setDeprecationTicketsExtra(e.target.value)} placeholder="e.g. ENG-123, ENG-456" style={{ padding: "8px 12px", fontSize: "13px", width: "100%", maxWidth: "400px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }} />
                        </div>
                        <div style={{ marginBottom: "10px" }}>
                          <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Reviewers (type name to search)</label>
                          <ReviewerAutocomplete value={deprecationReviewers} onChange={setDeprecationReviewers} placeholder="Type name (e.g. john) to search..." />
                        </div>
                        <div style={{ display: "flex", gap: "10px", flexWrap: "wrap", marginTop: "10px", alignItems: "center" }}>
                          <button onClick={() => handleDeprecationCreateLstCr(false)} disabled={deprecationCreateLstLoading || !deprecationLstFile.trim()} style={(deprecationCreateLstLoading || !deprecationLstFile.trim()) ? { ...btnPrimaryDisabled } : { ...btnPrimary }}>
                            {deprecationCreateLstLoading ? "Creating..." : "Create Gerrit CR"}
                          </button>
                        </div>
                        {deprecationCrResult && (
                          <div style={{ marginTop: "12px", padding: "10px", background: deprecationCrResult.success ? "#ecfdf5" : "#fef2f2", borderRadius: "4px", border: "1px solid " + (deprecationCrResult.success ? "#10b981" : "#f87171"), fontSize: "13px" }}>
                            {deprecationCrResult.success && deprecationCrResult.cr_url && <p style={{ margin: "0 0 8px 0" }}><a href={deprecationCrResult.cr_url} target="_blank" rel="noreferrer">Open CR →</a></p>}
                            {(deprecationCrResult.message || deprecationCrResult.error) && <p style={{ margin: 0 }}>{deprecationCrResult.message || deprecationCrResult.error}</p>}
                          </div>
                        )}
                        {deprecationManualLstInstructions && (
                          <div style={{ marginTop: "12px", padding: "12px", background: "#f8fafc", borderRadius: "4px", border: "1px solid #e2e8f0", fontSize: "13px" }}>
                            {Array.isArray(deprecationManualLstInstructions.manual_steps) && <div style={{ whiteSpace: "pre-wrap", marginBottom: "8px" }}>{deprecationManualLstInstructions.manual_steps.join("\n")}</div>}
                            {deprecationManualLstInstructions.copy_paste_block && <pre style={{ marginTop: "8px", background: "#f1f5f9", padding: "8px", borderRadius: "4px", overflow: "auto", fontSize: "12px" }}>{deprecationManualLstInstructions.copy_paste_block}</pre>}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
