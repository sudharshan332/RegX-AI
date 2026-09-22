import React, { useState, useEffect, useRef, useMemo } from "react";
import api from "../api";
import { useAuth } from "../context/AuthContext";
import "./Handover.css";

// Relative paths: the shared `api` axios instance (src/api.js) already prepends
// API_BASE_URL and attaches the JWT, matching the rest of the dashboard.
const JITA_ANALYSIS_API = "/mcp/regression/jita-analysis";
const CREATE_LST_CR_API = "/mcp/regression/create-lst-cr";
const VALIDATE_LST_API = "/mcp/regression/validate-lst";
const CHECK_LST_TESTCASES_API = "/mcp/regression/check-lst-testcases";
const DEPRECATE_LST_CR_API = "/mcp/regression/deprecate-lst-cr";
const DEPRECATION_RECORD_API = "/mcp/regression/deprecation-record";
const DEPRECATION_RECORD_DELETE_API = "/mcp/regression/deprecation-record-delete";
const HANDOVER_RECORD_API = "/mcp/regression/handover-record";
const HANDOVER_RECORD_DELETE_API = "/mcp/regression/handover-record-delete";
const HANDOVER_RECORDS_API = "/mcp/regression/handover-records";
const DEPRECATION_RECORDS_API = "/mcp/regression/deprecation-records";
const DEPRECATION_SEARCH_API = "/mcp/regression/deprecation-search";
const JIRA_VALIDATE_API = "/mcp/regression/validate-jira-ticket";
const SEARCH_LST_FILE_API = "/mcp/regression/search-lst-file";
const SUGGEST_LST_FILE_API = "/mcp/regression/suggest-lst-file";
const SEARCH_REVIEWERS_API = "/mcp/regression/search-reviewers";
const SEARCH_BRANCHES_API = "/mcp/regression/search-branches";
const JIRA_URL = "https://jira.nutanix.com/browse/";

function isPassedTest(tc) {
  if (!tc) return false;
  const passCount = tc.passed_count || 0;
  const status = (tc.status || "").toLowerCase();
  return status === "succeeded" || passCount >= 2;
}

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

const HEX_TASK_ID_RE = /^[a-f0-9]{20,}$/i;
const HANDOVER_URL_RE = /https?:\/\/[^\s,]+/gi;
const JIRA_KEY_RE = /^[A-Za-z][A-Za-z0-9_]+-\d+$/;

function parseHandoverInput(text) {
  const blob = String(text || "");
  const taskIds = [];
  const seenIds = new Set();
  const testNames = [];
  const seenNames = new Set();

  const addId = (tid) => {
    const t = String(tid || "").trim();
    if (!t || seenIds.has(t)) return;
    seenIds.add(t);
    taskIds.push(t);
  };
  const addName = (name) => {
    const n = String(name || "").trim();
    if (!n || seenNames.has(n) || HEX_TASK_ID_RE.test(n) || JIRA_KEY_RE.test(n)) return;
    seenNames.add(n);
    testNames.push(n);
  };

  let remainder = blob;
  const urlMatches = blob.match(HANDOVER_URL_RE) || [];
  urlMatches.forEach((raw) => {
    const url = raw.replace(/[).,\]]+$/, "");
    try {
      const parsed = new URL(url);
      if ((parsed.pathname || "").includes("/agave_tasks/")) {
        const tid = parsed.pathname.replace(/\/+$/, "").split("/").pop();
        if (tid && tid.length >= 20) addId(tid);
      }
      const param = parsed.searchParams.get("task_ids") || "";
      param.split(",").forEach((tid) => addId(tid));
    } catch {
      // ignore malformed URLs; leftover text is parsed as names below
    }
    remainder = remainder.split(raw).join("\n");
  });

  remainder.split(/[,\n]+/).forEach((segment) => {
    const leftover = [];
    String(segment || "").split(/\s+/).forEach((part) => {
      const token = part.trim().replace(/[).,\]]+$/, "");
      if (!token) return;
      if (HEX_TASK_ID_RE.test(token)) {
        addId(token);
        return;
      }
      if (JIRA_KEY_RE.test(token)) return;
      leftover.push(token);
    });
    if (leftover.length) addName(leftover.join(" "));
  });

  return { taskIds, testNames };
}

function getSavedRecordKey(kind, r) {
  const date = kind === "deprecation" ? (r.deprecation_date || "") : (r.handover_date || "");
  return `${kind}\0${(r.test_name || "").trim()}\0${date}\0${(r.lst_file || "").trim()}`;
}

function recordLstFiles(r) {
  const files = [];
  const seen = new Set();
  const add = (raw) => {
    const v = (raw || "").trim();
    if (!v || seen.has(v)) return;
    seen.add(v);
    files.push(v);
  };
  if (Array.isArray(r?.lst_files)) r.lst_files.forEach(add);
  add(r?.lst_file);
  return files;
}

function lstFileBasename(path) {
  const s = String(path || "").trim();
  if (!s) return "";
  const parts = s.split(/[/\\]/).filter(Boolean);
  return parts[parts.length - 1] || s;
}

function uniqueTickets(...lists) {
  const out = [];
  const seen = new Set();
  lists.forEach((list) => {
    (list || []).forEach((raw) => {
      const t = String(raw || "").trim();
      if (!t || seen.has(t)) return;
      seen.add(t);
      out.push(t);
    });
  });
  return out;
}

function TicketLinks({ tickets }) {
  const list = uniqueTickets(tickets);
  if (!list.length) return <span className="ho-records-empty">-</span>;
  return (
    <div className="ho-ticket-pills">
      {list.map((t) => (
        <a key={t} href={`${JIRA_URL}${t}`} target="_blank" rel="noreferrer" className="ho-ticket-pill">{t}</a>
      ))}
    </div>
  );
}

function SavedRecordTickets({ record }) {
  const tickets = uniqueTickets(record.handover_tickets, record.jira_tickets, record.tickets);
  return <TicketLinks tickets={tickets} />;
}

function recordExtraSections(r) {
  return [
    ["Notes", r?.notes],
    ["Commit message", r?.commit_message],
    ["CR subject", r?.cr_subject],
    ["CR description", r?.cr_description],
  ].filter(([, value]) => String(value || "").trim());
}

function formatLstAddSummary(toAdd, alreadyPresent) {
  const added = Array.isArray(toAdd) ? toAdd : [];
  const already = Array.isArray(alreadyPresent) ? alreadyPresent : [];
  const total = added.length + already.length;
  if (!total) return "";
  let msg = ` Added ${added.length} of ${total} selected.`;
  if (already.length) {
    msg += ` Skipped ${already.length} already in LST (exact line match).`;
  }
  return msg;
}

function formatLstRemoveSummary(removed, notPresent) {
  const rem = Array.isArray(removed) ? removed : [];
  const missing = Array.isArray(notPresent) ? notPresent : [];
  let msg = ` Removed ${rem.length}.`;
  if (missing.length) {
    const preview = missing.slice(0, 5).join(", ");
    msg += ` Not in LST (${missing.length}): ${preview}${missing.length > 5 ? " ..." : ""}.`;
  }
  return msg;
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

export default function Handover() {
  const { user } = useAuth();
  const [handoverJitaInput, setHandoverJitaInput] = useState("");
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
  const handoverLstSuggestCacheRef = useRef(new Map());
  const handoverAutoJiraRef = useRef(null);
  const handoverBranchSuggestTimerRef = useRef(null);
  const handoverBranchContainerRef = useRef(null);
  const handoverFetchBranchContainerRef = useRef(null);
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
  const [deprecationLstFile, setDeprecationLstFile] = useState("");
  const [deprecationLstFiles, setDeprecationLstFiles] = useState([]);
  const [deprecationLstSuggestion, setDeprecationLstSuggestion] = useState(null);
  const [deprecationSuggestingLst, setDeprecationSuggestingLst] = useState(false);
  const deprecationLstSuggestCacheRef = useRef(new Map());
  const [deprecationLstBranch, setDeprecationLstBranch] = useState("");
  const [deprecationBranchSuggestions, setDeprecationBranchSuggestions] = useState([]);
  const [deprecationBranchLoading, setDeprecationBranchLoading] = useState(false);
  const [deprecationShowBranchDropdown, setDeprecationShowBranchDropdown] = useState(false);
  const deprecationBranchSuggestTimerRef = useRef(null);
  const deprecationBranchContainerRef = useRef(null);
  const [deprecationCommitMessage, setDeprecationCommitMessage] = useState("");
  const [deprecationTicketsExtra, setDeprecationTicketsExtra] = useState("");
  const [deprecationReviewers, setDeprecationReviewers] = useState("");
  const [deprecationValidation, setDeprecationValidation] = useState(null);
  const [deprecationCrResult, setDeprecationCrResult] = useState(null);
  const [deprecationCreateLstLoading, setDeprecationCreateLstLoading] = useState(false);
  const [deprecationValidating, setDeprecationValidating] = useState(false);
  const [deprecationManualLstInstructions, setDeprecationManualLstInstructions] = useState(null);

  const [recordsQuery, setRecordsQuery] = useState("");
  const [recordsHandover, setRecordsHandover] = useState([]);
  const [recordsDeprecation, setRecordsDeprecation] = useState([]);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [recordsError, setRecordsError] = useState(null);
  const [recordsExpanded, setRecordsExpanded] = useState(new Set());
  const [recordsEditMode, setRecordsEditMode] = useState(false);

  const getAuthHeaders = () => {
    if (user?.email) return { "X-User-Email": user.email };
    return {};
  };

  const getSelectedHandoverTests = () => {
    if (!handoverAnalysis?.test_cases?.length) return [];
    return handoverSelectedTests.size > 0
      ? Array.from(handoverSelectedTests).filter((name) => handoverAnalysis.test_cases.some((tc) => tc.test_name === name))
      : handoverAnalysis.test_cases.map((tc) => tc.test_name).filter(Boolean);
  };

  const getSelectedTestCases = () =>
    (handoverAnalysis?.test_cases || []).filter((tc) => handoverSelectedTests.has(tc.test_name));

  const selectedFailedAreProductBug = () => {
    const selected = getSelectedTestCases();
    if (!selected.length) return false;
    const failed = selected.filter((tc) => !isPassedTest(tc));
    if (!failed.length) return false;
    return failed.every((tc) => handoverValidatedProductBugTests.has(tc.test_name));
  };

  const selectedAreHandoverReady = () => {
    const selected = getSelectedTestCases();
    if (!selected.length) return false;
    return selected.every((tc) => isPassedTest(tc) || handoverValidatedProductBugTests.has(tc.test_name));
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
    const test_names = handoverSelectedTests.size > 0 ? getSelectedHandoverTests().slice(0, 20) : [];
    if (!branch) {
      if (!silent) alert("Please enter Branch before suggesting LST.");
      return;
    }
    if (!test_names.length) {
      if (!silent) alert("Please select at least one testcase before suggesting an LST file.");
      return;
    }
    const cacheKey = `${branch}::${[...test_names].sort().join("|")}`;
    const cached = handoverLstSuggestCacheRef.current.get(cacheKey);
    if (cached) {
      setHandoverLstSuggestion(cached);
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
    const selected = handoverSelectedTests.size > 0 ? getSelectedHandoverTests() : [];
    if (!branch || !selected.length || handoverDataLocked) return undefined;
    const t = setTimeout(() => {
      handleSuggestLstFile({ silent: true });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoverCreateLstBranch, handoverSelectedTests, handoverAnalysis, handoverDataLocked]);

  useEffect(() => {
    const q = (handoverCreateLstBranch || "").trim();
    if (handoverBranchSuggestTimerRef.current) clearTimeout(handoverBranchSuggestTimerRef.current);
    if (!q) {
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
  }, [handoverCreateLstBranch]);

  useEffect(() => {
    const onDocClick = (e) => {
      const inHandoverBranch = handoverBranchContainerRef.current?.contains(e.target);
      const inFetchBranch = handoverFetchBranchContainerRef.current?.contains(e.target);
      if (!inHandoverBranch && !inFetchBranch) {
        setHandoverShowBranchDropdown(false);
      }
      if (deprecationBranchContainerRef.current && !deprecationBranchContainerRef.current.contains(e.target)) {
        setDeprecationShowBranchDropdown(false);
      }
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  useEffect(() => {
    const q = (deprecationLstBranch || "").trim();
    if (deprecationBranchSuggestTimerRef.current) clearTimeout(deprecationBranchSuggestTimerRef.current);
    if (!q) {
      setDeprecationBranchSuggestions([]);
      setDeprecationShowBranchDropdown(false);
      return undefined;
    }
    deprecationBranchSuggestTimerRef.current = setTimeout(async () => {
      setDeprecationBranchLoading(true);
      try {
        const res = await api.get(SEARCH_BRANCHES_API, { params: { q }, headers: getAuthHeaders(), timeout: 20000 });
        const results = (res.data?.results || []).filter(Boolean);
        setDeprecationBranchSuggestions(results);
        setDeprecationShowBranchDropdown(results.length > 0);
      } catch {
        setDeprecationBranchSuggestions([]);
        setDeprecationShowBranchDropdown(false);
      } finally {
        setDeprecationBranchLoading(false);
      }
    }, 220);
    return () => {
      if (deprecationBranchSuggestTimerRef.current) clearTimeout(deprecationBranchSuggestTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deprecationLstBranch]);

  const getDeprecationSearchTestNames = () => {
    const names = [];
    (deprecationSearchQueries || []).forEach((q) => {
      String(q || "")
        .split(/[,\n]+/)
        .map((s) => s.trim())
        .filter(Boolean)
        .forEach((n) => {
          if (!names.includes(n)) names.push(n);
        });
    });
    return names;
  };

  /** Searched test name(s) are the deprecation CR targets. */
  const getDeprecationTargetTests = () => getDeprecationSearchTestNames();

  const getResolvedDeprecationLstFiles = () => {
    const out = [];
    const seen = new Set();
    (deprecationLstFiles || []).forEach((f) => {
      const v = (f || "").trim();
      if (!v || seen.has(v)) return;
      seen.add(v);
      out.push(v);
    });
    return out;
  };

  const handleSuggestDeprecationLstFile = async ({ silent = false } = {}) => {
    const branch = (deprecationLstBranch || "").trim();
    const test_names = getDeprecationTargetTests().slice(0, 20);
    if (!branch) {
      if (!silent) alert("Please enter Branch so Sourcegraph can list LST files on that revision.");
      return;
    }
    if (!test_names.length) {
      if (!silent) alert("Search by test name first.");
      return;
    }
    const cacheKey = `${branch}::${[...test_names].sort().join("|")}`;
    const cached = deprecationLstSuggestCacheRef.current.get(cacheKey);
    if (cached) {
      setDeprecationLstSuggestion(cached);
      return;
    }
    setDeprecationSuggestingLst(true);
    try {
      const res = await api.post(
        SUGGEST_LST_FILE_API,
        { branch, test_names },
        { headers: getAuthHeaders(), timeout: 60000 }
      );
      const data = res.data || {};
      deprecationLstSuggestCacheRef.current.set(cacheKey, data);
      setDeprecationLstSuggestion(data);
    } catch (err) {
      const msg = err.response?.data?.error || err.message || "Failed to list LST files.";
      setDeprecationLstSuggestion({ error: msg, suggested_lst_file: "", candidates: [] });
    } finally {
      setDeprecationSuggestingLst(false);
    }
  };

  useEffect(() => {
    const branch = (deprecationLstBranch || "").trim();
    const names = getDeprecationTargetTests();
    if (!deprecationResults || deprecationResults.error || !branch || !names.length) return undefined;
    const t = setTimeout(() => {
      handleSuggestDeprecationLstFile({ silent: true });
    }, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deprecationLstBranch, deprecationSearchQueries, deprecationResults]);

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
    const input = (handoverJitaInput || "").trim();
    if (!input) {
      alert("Enter JITA results URL(s), task ID(s), and/or testcase name(s), separated by comma, space, or new line.");
      return;
    }
    const parsed = parseHandoverInput(input);
    const branch = (handoverCreateLstBranch || "").trim();
    if (!parsed.taskIds.length && !parsed.testNames.length) {
      alert("Enter JITA results URL(s), task ID(s), and/or testcase name(s), separated by comma, space, or new line.");
      return;
    }
    if (parsed.testNames.length && !branch) {
      alert("Enter Branch so the last 5 runs on that branch can be used for testcase-name lookup.");
      return;
    }
    setLoadingHandover(true);
    setHandoverAnalysis(null);
    handoverAutoJiraRef.current = null;
    setHandoverDataLocked(false);
    setHandoverTestTickets({});
    setHandoverBugTypeMap({});
    setHandoverJiraTicketValidation({});
    setHandoverJiraOverride(false);
    setHandoverManualLstInstructions(null);
    setHandoverCrResult(null);
    setHandoverSelectedTests(new Set());
    setHandoverLstFileResults({});
    setHandoverTicketsExtra(""); // Clear handover tickets from previous search
    setHandoverCreateLstFile(""); // Clear LST file from previous search
    setHandoverCreateLstFiles([]);
    handoverLstSuggestCacheRef.current.clear();
    setHandoverLstSuggestion(null); // Clear LST suggestion
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
      const res = await api.post(
        JITA_ANALYSIS_API,
        { input, branch, min_passes_for_success: 2, use_sliding_eligibility: true },
        { timeout: 120000, headers: { "Content-Type": "application/json" } }
      );
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
        
        // Auto-select eligible tests (2 consecutive passes, or Product Bug gaps between passes)
        const autoSelected = new Set();
        res.data.test_cases.forEach((tc) => {
          const status = (tc.status || "").toLowerCase();
          const isEligible = status === "succeeded" || !!tc.eligibility_reason;
          if (isEligible) {
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
        errorMsg = "Invalid request: " + (err.response?.data?.error || err.message || "Please check the JITA URL or testcase name(s).");
      } else if (err.message) {
        errorMsg = err.message;
      }
      
      setHandoverAnalysis({ error: errorMsg });
    } finally {
      setLoadingHandover(false);
    }
  };

  const handleValidateJiraTickets = async ({ silent = false, ticketsMap, testCases } = {}) => {
    // Priority: Table input (user's latest changes) > Backend analysis
    // Extra tickets (handoverTicketsExtra) are validated separately and NOT used for Product Bug validation
    const ticketSource = ticketsMap || handoverTestTickets || {};
    const cases = testCases || handoverAnalysis?.test_cases || [];
    const fromTable = [];
    const ticketsByTest = {}; // Track which tickets belong to which test case (excludes extra tickets)
    Object.entries(ticketSource).forEach(([testName, val]) => {
      const testTickets = (val || "").split(",").map((t) => t.trim().toUpperCase()).filter((t) => /^[A-Z]+-\d+$/.test(t));
      testTickets.forEach((t) => {
        fromTable.push(t);
        if (!ticketsByTest[testName]) ticketsByTest[testName] = [];
        ticketsByTest[testName].push(t);
      });
    });
    
    // Only include backend tickets if user hasn't entered tickets in table for that test case
    const fromAnalysis = [];
    cases.forEach((tc) => {
      const testName = tc.test_name;
      // Only use backend tickets if user hasn't entered tickets in table for this test
      const hasUserInput = ticketSource[testName] && String(ticketSource[testName]).trim();
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
    
    // Combine tickets for validation: Only Table input + Backend (skip handover tickets)
    // Note: Handover tickets (handoverTicketsExtra) are NOT validated - they are not bug tickets
    const tickets = [...new Set([...fromTable, ...fromAnalysis])].filter((t) => /^[A-Z]+-\d+$/.test(t));
    if (tickets.length === 0) {
      if (!silent) alert("Enter at least one Jira ticket (e.g. ENG-123) in the Ticket(s) column or handover tickets field.");
      return;
    }
    setHandoverJiraValidating(true);
    setHandoverJiraTicketValidation({});
    setHandoverJiraSkippedMessage(null);
    const results = {};
    try {
      for (const ticket of tickets) {
        try {
          const res = await api.post(JIRA_VALIDATE_API, { ticket }, { timeout: 10000, headers: { "Content-Type": "application/json" } });
          if (res.data?.skipped) {
            setHandoverJiraSkippedMessage(res.data.message || "Jira validation is not configured.");
            setHandoverJiraTicketValidation({});
            setHandoverValidatedProductBugTests(new Set());
            return;
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
        const allValid = testTickets.length > 0 && testTickets.every((ticket) => {
          const validation = results[ticket.toUpperCase()];
          return validation && validation.valid === true;
        });
        if (allValid) {
          validatedProductBugTests.add(testName);
        }
      });
      setHandoverValidatedProductBugTests(validatedProductBugTests);
    } finally {
      setHandoverJiraValidating(false);
    }
  };

  useEffect(() => {
    if (!handoverAnalysis?.test_cases?.length || handoverAnalysis.error || handoverDataLocked) {
      if (!handoverAnalysis) handoverAutoJiraRef.current = null;
      return undefined;
    }
    if (handoverAutoJiraRef.current === handoverAnalysis) return undefined;
    handoverAutoJiraRef.current = handoverAnalysis;
    if (!handoverSelectedTests.size) return undefined;
    handleValidateJiraTickets({ silent: true });
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoverAnalysis]);

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
      const authRequired = responses.some((r) => r.auth_required);
      const branchOk = responses.length > 0 && responses.every((r) => r.branch_valid === true);
      const fileOk = responses.length > 0 && responses.every((r) => r.file_valid === true);
      const allValid = branchOk && fileOk && !authRequired && responses.every((r) => !r.error);
      const authMessage = authRequired
        ? (responses.find((r) => r.message || r.branch_error || r.file_error)?.message
          || responses.find((r) => r.branch_error)?.branch_error
          || "Sourcegraph token missing/invalid — save it in Settings → API Key Configuration.")
        : null;
      setHandoverValidation({
        all_valid: allValid,
        files: responses,
        branch_valid: authRequired ? null : (branchOk ? true : (responses.some((r) => r.branch_valid === false) ? false : null)),
        file_valid: authRequired ? null : (fileOk ? true : (responses.some((r) => r.file_valid === false) ? false : null)),
        auth_required: authRequired,
        branch_error: authRequired ? authMessage : (responses.find((r) => r.branch_error)?.branch_error || null),
        file_error: authRequired ? authMessage : (responses.find((r) => r.file_error)?.file_error || null),
        message: authMessage || responses.find((r) => r.message)?.message || null,
        sourcegraph_url: responses.find((r) => r.sourcegraph_url)?.sourcegraph_url || null,
        error: responses.find((r) => r.error)?.error || null,
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
      const canProceed = handoverAnalysis?.all_tests_passed || selectedAreHandoverReady();
      if (!canProceed) {
        alert("Selected test cases must be passed or Jira-validated as Product Bug before creating LST CR.");
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
          user_email: user?.email,
          user_name: user?.name || user?.username,
          handover_tickets: handoverTicketsList,
          reviewers: reviewersList.length ? reviewersList : undefined,
          cr_subject: finalCrSubject,
          cr_description: finalCrDescription,
        },
        { headers: getAuthHeaders(), timeout: 600000 }
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
          error: "Gerrit HTTP password is missing or invalid. Save it in Settings → API Keys → Gerrit HTTP Password.",
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
    setDeprecationLstFiles([]);
    setDeprecationLstFile("");
    setDeprecationLstSuggestion(null);
    deprecationLstSuggestCacheRef.current.clear();
    setDeprecationValidation(null);
    setDeprecationCrResult(null);
    setDeprecationManualLstInstructions(null);
    try {
      const branch = (deprecationLstBranch || "").trim();
      const res = await api.post(DEPRECATION_SEARCH_API, { q: parts, branch: branch || undefined });
      setDeprecationResults(res.data);
    } catch (err) {
      setDeprecationResults({ error: err.response?.data?.error || "Search failed.", results: [], count: 0 });
    } finally {
      setLoadingDeprecationSearch(false);
    }
  };

  const loadSavedRecords = async (queryText) => {
    const q = (queryText ?? recordsQuery).trim();
    setRecordsLoading(true);
    setRecordsError(null);
    try {
      const payload = q ? { q } : {};
      const [ho, dep] = await Promise.all([
        api.post(HANDOVER_RECORDS_API, payload, { headers: getAuthHeaders(), timeout: 30000 }),
        api.post(DEPRECATION_RECORDS_API, payload, { headers: getAuthHeaders(), timeout: 30000 }),
      ]);
      setRecordsHandover(ho.data?.results || []);
      setRecordsDeprecation(dep.data?.results || []);
    } catch (err) {
      setRecordsError(err.response?.data?.error || err.message || "Failed to load records.");
    } finally {
      setRecordsLoading(false);
    }
  };

  const handleRecordsDelete = async (kind, r) => {
    const testName = (r.test_name || "").trim();
    const date = kind === "deprecation" ? (r.deprecation_date || "") : (r.handover_date || "");
    if (!testName || !date) return;
    if (!window.confirm(`Delete this ${kind} record for "${testName}"?`)) return;
    try {
      const res = await api.post(
        kind === "deprecation" ? DEPRECATION_RECORD_DELETE_API : HANDOVER_RECORD_DELETE_API,
        kind === "deprecation"
          ? { test_name: testName, deprecation_date: date, lst_file: r.lst_file || "" }
          : { test_name: testName, handover_date: date, lst_file: r.lst_file || "" },
        { headers: getAuthHeaders() }
      );
      if (!res.data?.success) {
        alert(res.data?.message || "No matching record found.");
        return;
      }
      const key = getSavedRecordKey(kind, r);
      if (kind === "deprecation") {
        setRecordsDeprecation((prev) => prev.filter((x) => getSavedRecordKey("deprecation", x) !== key));
      } else {
        setRecordsHandover((prev) => prev.filter((x) => getSavedRecordKey("handover", x) !== key));
      }
      setRecordsExpanded((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    } catch (err) {
      if (err.response?.status === 403) {
        alert(err.response?.data?.error || "You can only delete records you created.");
        return;
      }
      alert(err.response?.data?.error || "Failed to delete record.");
    }
  };

  const toggleRecordsExpanded = (key) => {
    setRecordsExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  useEffect(() => {
    if (activeTab === "records") {
      loadSavedRecords();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const visibleSavedRecords = useMemo(() => {
    const ho = (recordsHandover || []).map((r) => ({
      ...r,
      _kind: "handover",
      _date: r.handover_date || "",
      _key: getSavedRecordKey("handover", r),
    }));
    const dep = (recordsDeprecation || []).map((r) => ({
      ...r,
      _kind: "deprecation",
      _date: r.deprecation_date || "",
      _key: getSavedRecordKey("deprecation", r),
    }));
    const rows = ho.concat(dep);
    rows.sort((a, b) => String(b._date).localeCompare(String(a._date)));
    return rows;
  }, [recordsHandover, recordsDeprecation]);

  const canEditAnyVisible = visibleSavedRecords.some((r) => r.can_delete);

  const handleDeprecationValidateLst = async () => {
    const branch = (deprecationLstBranch || "").trim();
    const lst_files = getResolvedDeprecationLstFiles();
    if (!branch) {
      alert("Please enter Branch.");
      return;
    }
    if (!lst_files.length) {
      alert("Select at least one LST file.");
      return;
    }
    const test_names = getDeprecationTargetTests();
    if (!test_names.length) {
      alert("Search by test name first.");
      return;
    }
    setDeprecationValidating(true);
    setDeprecationValidation(null);
    setDeprecationCrResult(null);
    try {
      const files = await Promise.all(
        lst_files.map((lst_file) =>
          api.post(CHECK_LST_TESTCASES_API, { branch, lst_file, test_names }, { timeout: 30000 })
            .then((r) => ({ lst_file, ...(r.data || {}) }))
            .catch((err) => ({
              lst_file,
              error: err.response?.data?.error || err.message || "Check failed",
              present: [],
              not_present: test_names,
              test_names,
            }))
        )
      );
      const firstError = files.find((f) => f.error);
      setDeprecationValidation({
        files,
        test_names,
        error: firstError && files.length === 1 ? firstError.error : null,
      });
    } catch (err) {
      let errorMsg = "Check failed";
      if (err.code === "ECONNABORTED" || err.message?.includes("timeout")) {
        errorMsg = "Request timed out. Please check your network connection and try again, or paste the LST file content below.";
      } else if (err.message?.includes("Network Error") || err.code === "ERR_NETWORK") {
        errorMsg = "Network error: Unable to connect to the backend. Please check your VPN connection and ensure the backend is running.";
      } else {
        errorMsg = err.response?.data?.error || err.message || "Check failed";
      }
      setDeprecationValidation({ error: errorMsg, present: [], not_present: test_names, files: [] });
    } finally {
      setDeprecationValidating(false);
    }
  };

  const handleDeprecationSave = async () => {
    const test_names = getDeprecationTargetTests();
    if (!test_names.length) {
      alert("Search by test name first.");
      return;
    }
    const branch = (deprecationLstBranch || "").trim();
    const lst_files = getResolvedDeprecationLstFiles();
    const lst_file = lst_files[0] || "";
    if (!branch) {
      alert("Please enter Branch.");
      return;
    }
    if (!lst_files.length) {
      alert("Select at least one LST file.");
      return;
    }
    setDeprecationCreateLstLoading(true);
    setDeprecationManualLstInstructions(null);
    setDeprecationCrResult(null);
    const ticketsList = (deprecationTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    const reviewersList = (deprecationReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const commitMsg = "Deprecated " + test_names.length + " test(s) from " + lst_files.join(", ") + (ticketsList.length ? "\n\nJira: " + ticketsList.join(", ") : "") + (deprecationCommitMessage.trim() ? "\n\n" + deprecationCommitMessage.trim() : "");
    const notes =
      "Deprecation saved (no Gerrit push). " +
      "Branch: " + branch + "; LST: " + lst_files.join(", ") +
      (reviewersList.length ? "; Reviewers: " + reviewersList.join(", ") : "") +
      (ticketsList.length ? "; Jira: " + ticketsList.join(", ") : "");
    try {
      const res = await api.post(
        DEPRECATION_RECORD_API,
        {
          branch,
          lst_file,
          lst_files,
          test_names,
          commit_message: commitMsg,
          jira_tickets: ticketsList.length ? ticketsList : undefined,
          reviewers: reviewersList.length ? reviewersList : undefined,
          notes,
          by_whom: user?.email || user?.username || user?.name || "unknown",
          user_email: user?.email,
          user_name: user?.name || user?.username,
        },
        { headers: getAuthHeaders() }
      );
      setDeprecationCrResult({
        success: true,
        message: res.data?.message || "Deprecation saved.",
        notes: res.data?.notes || notes,
        cr_status: res.data?.cr_status || "pending_manual",
      });
      alert(res.data?.message || "Deprecation saved.");
    } catch (err) {
      const errData = err.response?.data;
      setDeprecationCrResult({ success: false, error: errData?.error || "Failed to save deprecation", message: errData?.message });
    } finally {
      setDeprecationCreateLstLoading(false);
    }
  };

  const handleDeprecationCreateLstCr = async () => {
    const test_names = getDeprecationTargetTests();
    if (!test_names.length) {
      alert("Search by test name first.");
      return;
    }
    const branch = (deprecationLstBranch || "").trim();
    const lst_files = getResolvedDeprecationLstFiles();
    const lst_file = lst_files[0] || "";
    if (!branch) {
      alert("Please enter Branch.");
      return;
    }
    if (!lst_files.length) {
      alert("Select at least one LST file.");
      return;
    }
    setDeprecationCreateLstLoading(true);
    setDeprecationManualLstInstructions(null);
    setDeprecationCrResult(null);
    const ticketsList = (deprecationTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    const reviewersList = (deprecationReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const commitMsg = "Deprecated " + test_names.length + " test(s) from " + lst_files.join(", ") + (ticketsList.length ? "\n\nJira: " + ticketsList.join(", ") : "") + (deprecationCommitMessage.trim() ? "\n\n" + deprecationCommitMessage.trim() : "");
    try {
      // Persist a record first, then create CR
      try {
        await api.post(
          DEPRECATION_RECORD_API,
          {
            branch,
            lst_file,
            lst_files,
            test_names,
            commit_message: commitMsg,
            jira_tickets: ticketsList.length ? ticketsList : undefined,
            reviewers: reviewersList.length ? reviewersList : undefined,
            notes: "Deprecation CR requested via RegX.",
            cr_status: "creating",
            by_whom: user?.email || user?.username || user?.name || "unknown",
          },
          { headers: getAuthHeaders() }
        );
      } catch (_) {
        /* record save is best-effort before CR */
      }
      const res = await api.post(
        DEPRECATE_LST_CR_API,
        {
          branch,
          lst_file,
          lst_files,
          test_names,
          commit_message: commitMsg,
          jira_tickets: ticketsList.length ? ticketsList : undefined,
          reviewers: reviewersList.length ? reviewersList : undefined,
          manual_only: false,
        },
        { headers: getAuthHeaders(), timeout: 600000 }
      );
      if (res.data.manual && res.data.instructions) {
        setDeprecationManualLstInstructions(res.data.instructions);
        setDeprecationCrResult({ success: true, manual: true, message: res.data.message || "Manual CR steps generated below." });
      } else if (res.data.success) {
        setDeprecationCrResult({
          success: true,
          cr_url: res.data.cr_url || res.data.gerrit_url,
          gerrit_change_id: res.data.gerrit_change_id,
          message: res.data.message,
          removed: res.data.removed || [],
          not_present: res.data.not_present || [],
        });
        let depMsg = "✓ Deprecation CR created successfully!";
        if (res.data.gerrit_change_id) depMsg += ` Change ${res.data.gerrit_change_id}`;
        if (res.data.cr_url || res.data.gerrit_url) depMsg += ` — ${res.data.cr_url || res.data.gerrit_url}`;
        depMsg += formatLstRemoveSummary(res.data.removed, res.data.not_present);
        alert(depMsg);
      } else {
        setDeprecationCrResult({
          success: false,
          message: res.data.message,
          error: res.data.error,
          removed: res.data.removed || [],
          not_present: res.data.not_present || [],
        });
        alert(res.data.message || res.data.error || "Deprecation CR failed.");
      }
    } catch (err) {
      const errData = err.response?.data;
      if (errData?.require_key_setup) {
        alert(errData.message || errData.error || "Gerrit HTTP password required in Settings.");
      }
      setDeprecationCrResult({
        success: false,
        error: errData?.error || "Failed to create CR",
        message: errData?.message,
        git_error: errData?.git_error,
      });
      if (errData?.instructions) setDeprecationManualLstInstructions(errData.instructions);
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
        by_whom: user?.email || user?.username || user?.name || "unknown",
        branch: (handoverCreateLstBranch || "master").trim(),
        lst_file: (handoverCreateLstFile || "").trim(),
      });
      return { success: true, message: "Handover saved. You can search by test name on the Deprecation page." };
    } catch (err) {
      return { success: false, error: err.response?.data?.error || "Failed to save handover." };
    }
  };

  const handleHandoverSaveOnly = async () => {
    if (!handoverAnalysis?.test_cases?.length) {
      alert("No test cases available.");
      return;
    }

    const test_names = handoverSelectedTests.size > 0
      ? Array.from(handoverSelectedTests).filter((name) => handoverAnalysis.test_cases.some((tc) => tc.test_name === name))
      : handoverAnalysis.test_cases.map((tc) => tc.test_name).filter(Boolean);

    if (test_names.length === 0) {
      alert("Please select at least one test case.");
      return;
    }

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
      alert(`Cannot save handover: The following SELECTED test case(s) contain Test Bug or Environment bug types:\n${problematicTests.join("\n")}`);
      return;
    }

    const canProceedSave = handoverAnalysis?.all_tests_passed || selectedAreHandoverReady();
    if (!canProceedSave) {
      alert("Selected test cases must be passed or Jira-validated as Product Bug before saving handover.");
      return;
    }

    const branch = (handoverCreateLstBranch || "master").trim() || "master";
    const lst_files = getResolvedLstFiles();
    const lst_file = lst_files[0] || "";
    const reviewersList = (handoverReviewers || "").split(",").map((r) => r.trim()).filter(Boolean);
    const handoverTicketsList = (handoverTicketsExtra || "").split(",").map((t) => t.trim()).filter(Boolean);
    if (!handoverTicketsList.length) {
      alert("Please enter handover ticket(s) before saving.");
      return;
    }
    if (!lst_files.length) {
      alert("Please add at least one LST file path.");
      return;
    }

    setHandoverCreateLstLoading(true);
    setHandoverCrResult(null);

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
    const finalCrSubject = (handoverCrSubject || "Testcase Handover").trim() || "Testcase Handover";
    const finalCrDescription = (handoverCrDescription || "").trim() || buildDefaultCrDescription();
    const notes =
      "Handover saved without Gerrit push. Branch: " + branch +
      "; LST: " + lst_files.join(", ") +
      (reviewersList.length ? "; Reviewers: " + reviewersList.join(", ") : "") +
      "; Tickets: " + handoverTicketsList.join(", ");

    try {
      const res = await api.post(HANDOVER_RECORD_API, {
        test_names,
        test_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        tickets: ticketsList?.length ? ticketsList : undefined,
        test_bug_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        handover_tickets: handoverTicketsList,
        by_whom: user?.email || user?.username || user?.name || "unknown",
        branch,
        lst_file: lst_file || "",
        lst_files,
        reviewers: reviewersList.length ? reviewersList : undefined,
        notes,
        cr_status: "pending_manual",
        cr_subject: finalCrSubject,
        cr_description: finalCrDescription,
      });
      const saveResult = {
        success: true,
        message: res.data?.message || "Handover saved.",
        notes: res.data?.notes || notes,
        cr_status: res.data?.cr_status || "pending_manual",
      };
      setHandoverCrResult(saveResult);
      setHandoverDataLocked(true);
      alert(saveResult.message);
    } catch (err) {
      const errData = err.response?.data;
      setHandoverCrResult({
        success: false,
        error: errData?.error || "Failed to save handover.",
        message: errData?.message || err.message,
      });
      alert(errData?.error || "Failed to save handover.");
    } finally {
      setHandoverCreateLstLoading(false);
    }
  };

  const handleRecordHandoverAndCreateCR = async () => {
    if (!handoverAnalysis?.test_cases?.length) {
      alert("No test cases available.");
      return;
    }

    const test_names = handoverSelectedTests.size > 0
      ? Array.from(handoverSelectedTests).filter((name) => handoverAnalysis.test_cases.some((tc) => tc.test_name === name))
      : handoverAnalysis.test_cases.map((tc) => tc.test_name).filter(Boolean);

    if (test_names.length === 0) {
      alert("Please select at least one test case.");
      return;
    }

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
      alert(`Cannot record handover: The following SELECTED test case(s) contain Test Bug or Environment bug types:\n${problematicTests.join("\n")}`);
      return;
    }

    const canProceedCR = handoverAnalysis?.all_tests_passed || selectedAreHandoverReady();
    if (!canProceedCR) {
      alert("Selected test cases must be passed or Jira-validated as Product Bug before creating LST CR.");
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

    setHandoverCreateLstLoading(true);
    setHandoverManualLstInstructions(null);
    setHandoverCrResult(null);

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

    const finalCrSubject = (handoverCrSubject || "Testcase Handover").trim() || "Testcase Handover";
    const finalCrDescription = (handoverCrDescription || "").trim() || buildDefaultCrDescription();

    let handoverResult = null;
    let crResult = null;

    try {
      await api.post(HANDOVER_RECORD_API, {
        test_names,
        test_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        tickets: ticketsList?.length ? ticketsList : undefined,
        test_bug_tickets: hasPerTestBugTickets ? test_bug_tickets : undefined,
        handover_tickets: handoverTicketsList,
        by_whom: user?.email || user?.username || user?.name || "unknown",
        branch,
        lst_file: lst_file || "",
        lst_files,
        reviewers: reviewersList,
        notes: "Handover CR requested via RegX.",
        cr_status: "creating",
        cr_subject: finalCrSubject,
        cr_description: finalCrDescription,
      });
      handoverResult = { success: true, message: "Handover saved successfully." };
    } catch (err) {
      handoverResult = { success: false, error: err.response?.data?.error || "Failed to save handover." };
    }

    try {
      const res = await api.post(
        CREATE_LST_CR_API,
        {
          branch,
          test_names,
          lst_file: lst_file || "",
          lst_files,
          manual_only: false,
          user_email: user?.email,
          user_name: user?.name || user?.username,
          handover_tickets: handoverTicketsList,
          reviewers: reviewersList,
          cr_subject: finalCrSubject,
          cr_description: finalCrDescription,
        },
        { headers: getAuthHeaders(), timeout: 600000 }
      );
      if (res.data.manual && res.data.instructions) {
        setHandoverManualLstInstructions(res.data.instructions);
        crResult = { success: true, manual: true, message: res.data.message || "Manual CR steps generated below." };
      } else if (res.data.success) {
        crResult = {
          success: true,
          cr_url: res.data.cr_url || res.data.gerrit_url,
          gerrit_change_id: res.data.gerrit_change_id,
          message: res.data.message,
          already_present: res.data.already_present || [],
          to_add: res.data.to_add || [],
        };
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
          error: "Gerrit HTTP password is missing or invalid. Save it in Settings → API Keys → Gerrit HTTP Password.",
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
          errMsg = "Request was interrupted (connection reset or timeout). The backend may have restarted during git clone. Try again.";
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
        git_error: errData?.git_error,
      };
      if (errData?.instructions) setHandoverManualLstInstructions(errData.instructions);
    }

    setHandoverCrResult(crResult);

    let message = "";
    if (handoverResult.success && crResult.manual) {
      message = "✓ Handover recorded. Follow the manual git steps shown below to push the CR for review.";
    } else if (handoverResult.success && crResult.success) {
      message = "✓ Handover recorded and CR created successfully!";
      if (crResult.gerrit_change_id) message += ` Change ${crResult.gerrit_change_id}`;
      if (crResult.cr_url) message += ` — ${crResult.cr_url}`;
      message += formatLstAddSummary(crResult.to_add, crResult.already_present);
    } else if (handoverResult.success && !crResult.success) {
      message = `✓ Handover recorded successfully, but CR failed: ${crResult.error || crResult.message || "Unknown error"}`;
      if (crResult.already_present?.length && !crResult.to_add?.length) {
        message += formatLstAddSummary(crResult.to_add, crResult.already_present);
      }
    } else if (!handoverResult.success && crResult.success) {
      message = `✓ CR created successfully, but handover failed: ${handoverResult.error || "Unknown error"}`;
      message += formatLstAddSummary(crResult.to_add, crResult.already_present);
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
            backed by JITA results, Jira validation, and Gerrit CR creation.
          </p>
        </div>
        <div className="ho-tabs" role="tablist" aria-label="Handover, Deprecation, or Records">
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
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === "records"}
            className={`ho-tab${activeTab === "records" ? " is-active" : ""}`}
            onClick={() => setActiveTab("records")}
          >
            Records
          </button>
        </div>
      </div>

      {activeTab === "handover" && (
        <>
      <p className="ho-subtitle ho-intro">
        Paste JITA results URL(s), task ID(s), and/or testcase name(s) (comma or newline separated). For test names, enter Branch so the last 5 runs on that branch are used.
      </p>

      <div className="ho-card">
        <div className="ho-card__title">JITA results</div>
        <textarea
          value={handoverJitaInput}
          onChange={(e) => setHandoverJitaInput(e.target.value)}
          rows={4}
          placeholder="JITA URL(s), task ID(s), or testcase name(s)"
          style={{ width: "100%", padding: "10px 12px", fontSize: "14px", border: "1px solid #ddd", borderRadius: "4px", boxSizing: "border-box", fontFamily: "inherit", resize: "vertical" }}
        />
        <div style={{ display: "flex", gap: "12px", marginTop: "12px", flexWrap: "wrap", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div ref={handoverFetchBranchContainerRef} style={{ flex: "1 1 260px", maxWidth: "360px", position: "relative" }}>
            <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>
              Branch <span style={{ color: "#dc2626" }}>*</span>
              <span style={{ fontWeight: "400", color: "#64748b" }}> (required for test names)</span>
            </label>
            <input
              type="text"
              value={handoverCreateLstBranch}
              onChange={(e) => { setHandoverCreateLstBranch(e.target.value); setHandoverValidation(null); }}
              onFocus={() => { if (handoverBranchSuggestions.length > 0) setHandoverShowBranchDropdown(true); }}
              placeholder="master"
              disabled={loadingHandover}
              style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box", backgroundColor: loadingHandover ? "#f3f4f6" : "white" }}
            />
            {handoverShowBranchDropdown && !loadingHandover && (
              <div style={{ position: "absolute", top: "100%", left: 0, right: 0, maxHeight: "220px", overflowY: "auto", background: "white", border: "1px solid #d1d5db", borderRadius: "4px", boxShadow: "0 4px 6px rgba(0,0,0,0.1)", zIndex: 1000, marginTop: "2px" }}>
                {handoverBranchLoading ? (
                  <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>Searching branches...</div>
                ) : handoverBranchSuggestions.length === 0 ? (
                  <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>No branch suggestions</div>
                ) : (
                  handoverBranchSuggestions.map((b) => (
                    <button
                      key={`fetch-${b}`}
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
          <button onClick={() => handleHandoverAnalyze()} disabled={loadingHandover} style={loadingHandover ? { ...btnValidateDisabled } : { ...btnSecondary }}>
            {loadingHandover ? "Loading..." : "Fetch"}
          </button>
        </div>
      </div>

      {handoverAnalysis && (
        <div style={{ marginTop: "20px" }}>
          {handoverDataLocked && !handoverAnalysis.error && (
            <div style={{ marginBottom: "12px", padding: "12px 16px", background: "#f1f5f9", borderRadius: "8px", border: "1px solid #cbd5e1", color: "#475569", fontSize: "14px" }}>
              ✓ Data saved. Change the search box and click <strong>Fetch</strong> to make new changes.
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
                {(handoverAnalysis.lookup_mode === "test_names" || handoverAnalysis.lookup_mode === "mixed") && handoverAnalysis.history_window ? (
                  <span style={{ color: "#0f766e", background: "#ccfbf1", padding: "4px 10px", borderRadius: "6px" }}>
                    Last {handoverAnalysis.history_window} runs on {handoverAnalysis.branch || handoverCreateLstBranch || "branch"}
                  </span>
                ) : null}
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
                          const passedTestCases = (handoverAnalysis.test_cases || []).filter((tc) => isPassedTest(tc));
                          
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
                            
                            const passedTestCases = (handoverAnalysis.test_cases || []).filter((tc) => isPassedTest(tc));
                            
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
                    const isPassed = isPassedTest(tc);
                    
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
                              setHandoverJiraTicketValidation({});
                              setHandoverJiraSkippedMessage(null);
                              setHandoverValidatedProductBugTests((prev) => {
                                if (!prev.has(tc.test_name)) return prev;
                                const next = new Set(prev);
                                next.delete(tc.test_name);
                                return next;
                              });
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
                <button type="button" onClick={() => handleValidateJiraTickets()} disabled={handoverJiraValidating || handoverDataLocked} style={(handoverJiraValidating || handoverDataLocked) ? { ...btnValidateDisabled } : { ...btnValidate }}>
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
                const selectedTestCases = getSelectedTestCases();
                if (selectedTestCases.length === 0) {
                  return null;
                }

                const shouldShowCR = handoverAnalysis.all_tests_passed || selectedTestCases.every(isPassedTest) || selectedFailedAreProductBug();
                if (!shouldShowCR) {
                  return null;
                }

                const headingText = "✓ Ready for CR";
                const bgColor = "#ecfdf5";
                const borderColor = "#10b981";
                
                return (
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
                      {handoverValidation.auth_required ? (
                        <div style={{ color: "#b45309" }}>
                          Sourcegraph token missing/invalid — save it in Settings → API Key Configuration, then click Test Keys and retry Validate LST.
                          {(handoverValidation.message || handoverValidation.branch_error) && (
                            <div style={{ marginTop: "6px", fontSize: "12px" }}>{handoverValidation.message || handoverValidation.branch_error}</div>
                          )}
                        </div>
                      ) : handoverValidation.file_valid === true && handoverValidation.branch_valid === true ? (
                        <span style={{ color: "#166534" }}>✓ Branch and file validated.</span>
                      ) : (
                        <>
                          {handoverValidation.branch_valid != null && <span>Branch: {handoverValidation.branch_valid === true ? "✓" : "✗"} </span>}
                          {handoverValidation.file_valid != null && <span>File: {handoverValidation.file_valid === true ? "✓" : "✗"}</span>}
                          {handoverValidation.branch_valid == null && handoverValidation.file_valid == null && !handoverValidation.error && (
                            <span style={{ color: "#64748b" }}>Could not complete Sourcegraph validation.</span>
                          )}
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
                                <div key={f.lst_file} style={{ marginBottom: "4px", color: f.file_valid && f.branch_valid ? "#166534" : "#b91c1c" }}>
                                  {(f.file_valid && f.branch_valid) ? "✓" : "✗"} {f.lst_file}
                                  {(f.branch_error || f.file_error) && (
                                    <div style={{ color: "#64748b", fontWeight: 400 }}>
                                      {[f.branch_valid === true ? null : f.branch_error, f.file_valid === true ? null : f.file_error].filter(Boolean).join(" · ")}
                                    </div>
                                  )}
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
                    const hasLstValidation = handoverValidation !== null && 
                                             handoverValidation !== undefined &&
                                             handoverValidation.file_valid === true && 
                                             handoverValidation.branch_valid === true &&
                                             !handoverValidation.error;
                    const isButtonDisabled = handoverCreateLstLoading || 
                                            handoverDataLocked ||
                                            getResolvedLstFiles().length === 0 || 
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
                            type="button"
                            onClick={handleHandoverSaveOnly}
                            disabled={isButtonDisabled}
                            style={isButtonDisabled ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                            title="Save handover data without creating a Gerrit CR"
                          >
                            {handoverCreateLstLoading ? "Saving..." : "Save"}
                          </button>
                          <button
                            onClick={handleRecordHandoverAndCreateCR}
                            disabled={isButtonDisabled}
                            style={isButtonDisabled ? { ...btnPrimaryDisabled } : { ...btnPrimary }}
                            title={isButtonDisabled ? (!hasLstValidation ? "Please validate LST file" : "") : "Save handover and create Gerrit CR"}
                          >
                            {handoverCreateLstLoading ? "Processing..." : "Take handover"}
                          </button>
                          {!hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#64748b", fontStyle: "italic" }}>
                              Validate LST file to proceed
                            </span>
                          )}
                          {hasLstValidation && (
                            <span style={{ fontSize: "11px", color: "#16a34a", fontStyle: "italic", fontWeight: "500" }}>
                              ✓ Ready for handover
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
                );
              })()}

              {handoverCrResult && (
                <div style={{ marginTop: "16px", padding: "12px", background: handoverCrResult.success ? "#ecfdf5" : "#fef2f2", borderRadius: "8px", border: "1px solid " + (handoverCrResult.success ? "#10b981" : "#f87171") }}>
                  {handoverCrResult.success ? (
                    <div>
                      <p style={{ margin: 0 }}>
                        ✓ {handoverCrResult.message}{" "}
                        {(handoverCrResult.cr_url || handoverCrResult.gerrit_url) && (
                          <a href={handoverCrResult.cr_url || handoverCrResult.gerrit_url} target="_blank" rel="noreferrer">
                            {handoverCrResult.gerrit_change_id ? `CR ${handoverCrResult.gerrit_change_id}` : "View CR"}
                          </a>
                        )}
                      </p>
                      {(handoverCrResult.to_add?.length > 0 || handoverCrResult.already_present?.length > 0) && (
                        <div style={{ marginTop: "10px", fontSize: "12px", color: "#065f46" }}>
                          {handoverCrResult.to_add?.length > 0 && (
                            <details open style={{ marginBottom: "6px" }}>
                              <summary style={{ cursor: "pointer", fontWeight: 600 }}>
                                Added to LST ({handoverCrResult.to_add.length})
                              </summary>
                              <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                                {handoverCrResult.to_add.map((n) => (
                                  <li key={n} style={{ wordBreak: "break-word" }}>{n}</li>
                                ))}
                              </ul>
                            </details>
                          )}
                          {handoverCrResult.already_present?.length > 0 && (
                            <details style={{ marginBottom: "6px" }}>
                              <summary style={{ cursor: "pointer", fontWeight: 600, color: "#b45309" }}>
                                Already in LST — skipped ({handoverCrResult.already_present.length})
                              </summary>
                              <ul style={{ margin: "6px 0 0 18px", padding: 0, color: "#92400e" }}>
                                {handoverCrResult.already_present.map((n) => (
                                  <li key={n} style={{ wordBreak: "break-word" }}>{n}</li>
                                ))}
                              </ul>
                            </details>
                          )}
                        </div>
                      )}
                      {(handoverCrResult.notes || handoverCrResult.cr_status) && (
                        <p style={{ margin: "8px 0 0 0", fontSize: "12px", color: "#047857" }}>
                          {handoverCrResult.cr_status ? `Status: ${handoverCrResult.cr_status}. ` : ""}
                          {handoverCrResult.notes || ""}
                        </p>
                      )}
                    </div>
                  ) : (
                    <div>
                      <p style={{ margin: 0 }}>{handoverCrResult.error || handoverCrResult.message} {handoverCrResult.raw_error && <span style={{ fontSize: "12px", color: "#64748b" }}>{handoverCrResult.raw_error}</span>}</p>
                      {handoverCrResult.already_present?.length > 0 && (
                        <details style={{ marginTop: "8px", fontSize: "12px" }}>
                          <summary style={{ cursor: "pointer" }}>Already in LST ({handoverCrResult.already_present.length})</summary>
                          <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                            {handoverCrResult.already_present.map((n) => (
                              <li key={n} style={{ wordBreak: "break-word" }}>{n}</li>
                            ))}
                          </ul>
                        </details>
                      )}
                    </div>
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
            Search by test name(s), then enter Branch so Sourcegraph can list LST files on that revision. Select one or more files to remove the test from. Saved rows live under the Records tab.
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
                  {deprecationResults && !deprecationResults.error && (() => {
                    const selectedTestNames = getDeprecationTargetTests();
                    const selectedCount = selectedTestNames.length;
                    const resolvedDeprecationLstFiles = getResolvedDeprecationLstFiles();
                    const hasDeprecationLst = resolvedDeprecationLstFiles.length > 0;
                    const hasDeprecationBranch = (deprecationLstBranch || "").trim() !== "";
                    const depActionsDisabled = deprecationCreateLstLoading || selectedCount === 0 || !hasDeprecationLst || !hasDeprecationBranch;
                    const depValidateDisabled = deprecationValidating || selectedCount === 0 || !hasDeprecationLst || !hasDeprecationBranch;
                    return (
                      <div style={{ marginTop: "20px", padding: "16px", background: "#ecfdf5", borderRadius: "8px", border: "2px solid #10b981" }}>
                        <h4 style={{ marginTop: 0, marginBottom: "8px", color: "#065f46" }}>
                          Deprecate — Remove {selectedCount} test(s) from LST file(s)
                        </h4>
                        <p style={{ marginBottom: "12px", fontSize: "14px", color: "#047857" }}>
                          Enter Branch so Sourcegraph can list LST files on that revision. Select one or more files to remove the test from.
                        </p>
                        {selectedCount > 0 && (
                          <div style={{ marginBottom: "12px", padding: "10px", background: "#fff", borderRadius: "6px", border: "1px solid #a7f3d0", fontSize: "13px", color: "#065f46" }}>
                            <strong>Tests to remove:</strong>
                            <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                              {selectedTestNames.map((n) => (
                                <li key={n} style={{ wordBreak: "break-word" }}>{n}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <div ref={deprecationBranchContainerRef} style={{ marginBottom: "10px", maxWidth: "360px", position: "relative" }}>
                          <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>Branch <span style={{ color: "#dc2626" }}>*</span></label>
                          <input
                            type="text"
                            value={deprecationLstBranch}
                            onChange={(e) => {
                              setDeprecationLstBranch(e.target.value);
                              setDeprecationLstFiles([]);
                              setDeprecationValidation(null);
                              setDeprecationCrResult(null);
                            }}
                            onFocus={() => { if (deprecationBranchSuggestions.length > 0) setDeprecationShowBranchDropdown(true); }}
                            placeholder="master"
                            style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }}
                          />
                          {deprecationShowBranchDropdown && (
                            <div style={{ position: "absolute", top: "100%", left: 0, right: 0, maxHeight: "220px", overflowY: "auto", background: "white", border: "1px solid #d1d5db", borderRadius: "4px", boxShadow: "0 4px 6px rgba(0,0,0,0.1)", zIndex: 1000, marginTop: "2px" }}>
                              {deprecationBranchLoading ? (
                                <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>Searching branches...</div>
                              ) : deprecationBranchSuggestions.length === 0 ? (
                                <div style={{ padding: "8px 12px", fontSize: "13px", color: "#64748b" }}>No branch suggestions</div>
                              ) : (
                                deprecationBranchSuggestions.map((b) => (
                                  <button
                                    key={b}
                                    type="button"
                                    onClick={() => {
                                      setDeprecationLstBranch(b);
                                      setDeprecationShowBranchDropdown(false);
                                      setDeprecationLstFiles([]);
                                      setDeprecationValidation(null);
                                      setDeprecationCrResult(null);
                                    }}
                                    style={{ width: "100%", textAlign: "left", padding: "8px 12px", fontSize: "13px", cursor: "pointer", border: "none", borderBottom: "1px solid #f1f5f9", background: b === deprecationLstBranch ? "#e0f2fe" : "white" }}
                                  >
                                    {b}
                                  </button>
                                ))
                              )}
                            </div>
                          )}
                        </div>
                        <div style={{ marginBottom: "10px" }}>
                          <label style={{ display: "block", marginBottom: "4px", fontSize: "13px", fontWeight: "500" }}>LST File Path <span style={{ color: "#dc2626" }}>*</span></label>
                          <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap", width: "100%" }}>
                            <input
                              type="text"
                              value={deprecationLstFile}
                              onChange={(e) => { setDeprecationLstFile(e.target.value); setDeprecationValidation(null); setDeprecationCrResult(null); }}
                              placeholder="Optional typed path, e.g. test_sets/milestones/.../foo.lst"
                              style={{ padding: "8px 12px", fontSize: "13px", width: "100%", flex: 1, minWidth: "280px", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }}
                            />
                            <button
                              type="button"
                              disabled={!(deprecationLstFile || "").trim()}
                              onClick={() => {
                                const f = (deprecationLstFile || "").trim();
                                if (!f) return;
                                setDeprecationLstFiles((prev) => Array.from(new Set([...(prev || []), f])));
                                setDeprecationLstFile("");
                                setDeprecationValidation(null);
                                setDeprecationCrResult(null);
                              }}
                              style={!(deprecationLstFile || "").trim() ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                            >
                              Add LST
                            </button>
                          </div>
                          {resolvedDeprecationLstFiles.length > 0 && (
                            <div style={{ marginTop: "8px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
                              {resolvedDeprecationLstFiles.map((f) => (
                                <span key={f} style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 8px", borderRadius: "999px", background: "#ecfeff", border: "1px solid #a5f3fc", color: "#155e75", fontSize: "12px" }}>
                                  {f}
                                  <button
                                    type="button"
                                    onClick={() => {
                                      setDeprecationLstFiles((prev) => (prev || []).filter((x) => x !== f));
                                      if ((deprecationLstFile || "").trim() === f) setDeprecationLstFile("");
                                      setDeprecationValidation(null);
                                      setDeprecationCrResult(null);
                                    }}
                                    style={{ border: "none", background: "none", cursor: "pointer", color: "#0e7490" }}
                                  >
                                    ×
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                          <div style={{ marginTop: "8px", display: "flex", gap: "10px", alignItems: "center", flexWrap: "wrap" }}>
                            <button
                              type="button"
                              onClick={() => handleSuggestDeprecationLstFile({ silent: false })}
                              disabled={deprecationSuggestingLst}
                              style={deprecationSuggestingLst ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                            >
                              {deprecationSuggestingLst ? "Refreshing..." : "Refresh Suggestion"}
                            </button>
                            {deprecationLstSuggestion?.message && (
                              <span style={{ fontSize: "12px", color: "#475569" }}>{deprecationLstSuggestion.message}</span>
                            )}
                            {deprecationLstSuggestion?.error && (
                              <span style={{ fontSize: "12px", color: "#b91c1c" }}>{deprecationLstSuggestion.error}</span>
                            )}
                          </div>
                          {!hasDeprecationBranch && (
                            <p style={{ margin: "8px 0 0 0", fontSize: "12px", color: "#92400e" }}>
                              Enter Branch so Sourcegraph can list LST files on that revision.
                            </p>
                          )}
                          {Array.isArray(deprecationLstSuggestion?.candidates) && deprecationLstSuggestion.candidates.length > 0 && (
                            <div style={{ marginTop: "8px", padding: "10px", border: "1px solid #dbeafe", borderRadius: "6px", background: "#f8fbff", width: "100%" }}>
                              <div style={{ fontSize: "12px", color: "#1e3a8a", fontWeight: 600, marginBottom: "6px" }}>
                                Click to select suggested LST files (you can select multiple)
                              </div>
                              {deprecationLstSuggestion.candidates.map((c) => {
                                const file = c.lst_file || "";
                                const selected = resolvedDeprecationLstFiles.includes(file);
                                return (
                                  <button
                                    key={file}
                                    type="button"
                                    onClick={() => {
                                      if (!file) return;
                                      if (selected) {
                                        setDeprecationLstFiles((prev) => (prev || []).filter((x) => x !== file));
                                      } else {
                                        setDeprecationLstFiles((prev) => Array.from(new Set([...(prev || []), file])));
                                      }
                                      setDeprecationValidation(null);
                                      setDeprecationCrResult(null);
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
                        <div style={{ marginBottom: "10px", display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
                          <div style={{ flex: 1, minWidth: "200px" }}>
                            <label style={{ display: "block", marginBottom: "4px", fontSize: "13px" }}>Commit Message</label>
                            <input type="text" value={deprecationCommitMessage} onChange={(e) => setDeprecationCommitMessage(e.target.value)} placeholder="Optional" style={{ padding: "8px 12px", fontSize: "13px", width: "100%", border: "1px solid #d1d5db", borderRadius: "4px", boxSizing: "border-box" }} />
                          </div>
                          <button
                            onClick={handleDeprecationValidateLst}
                            disabled={depValidateDisabled}
                            style={depValidateDisabled ? { ...btnTertiaryDisabled } : { ...btnTertiary }}
                            title={!hasDeprecationBranch ? "Please enter Branch" : (!hasDeprecationLst ? "Select at least one LST file" : (selectedCount === 0 ? "Search or select testcases first" : ""))}
                          >
                            {deprecationValidating ? "Checking..." : "Validate LST"}
                          </button>
                        </div>
                        {deprecationValidation && (
                          <div style={{ marginBottom: "16px", marginTop: "4px", padding: "14px", background: deprecationValidation.error && !(deprecationValidation.files || []).length ? "#fef2f2" : "#ffffff", borderRadius: "8px", border: "2px solid " + (deprecationValidation.error && !(deprecationValidation.files || []).length ? "#dc2626" : "#10b981"), boxShadow: "0 1px 3px rgba(0,0,0,0.1)", fontSize: "14px", color: "#0f172a" }}>
                            <div style={{ fontWeight: "700", marginBottom: "10px", color: "#0f172a", fontSize: "15px" }}>Is selected testcase present in LST?</div>
                            {deprecationValidation.error && !(deprecationValidation.files || []).length ? (
                              <div style={{ color: "#b91c1c" }}>{deprecationValidation.error}</div>
                            ) : Array.isArray(deprecationValidation.files) && deprecationValidation.files.length > 0 ? (
                              deprecationValidation.files.map((fileResult) => {
                                const allTestNames = fileResult.test_names || deprecationValidation.test_names ||
                                  [...(fileResult.present || []), ...(fileResult.not_present || [])];
                                const presentList = (fileResult.present || []).map((t) => (t || "").trim());
                                const resolvedFrom = fileResult.resolved_from || {};
                                const ambiguous = fileResult.ambiguous || {};
                                const isPresent = (normalizedName) => {
                                  if (presentList.includes(normalizedName)) return true;
                                  if (presentList.some((p) => resolvedFrom[p] === normalizedName)) return true;
                                  if (presentList.some((p) => p.includes(normalizedName))) return true;
                                  return false;
                                };
                                const displayName = (normalizedName) => {
                                  const resolved = presentList.find((p) => resolvedFrom[p] === normalizedName)
                                    || presentList.find((p) => p !== normalizedName && p.includes(normalizedName));
                                  return resolved && resolved !== normalizedName
                                    ? `${normalizedName}  →  ${resolved}`
                                    : normalizedName;
                                };
                                return (
                                  <div key={fileResult.lst_file} style={{ marginBottom: "12px" }}>
                                    <div style={{ fontWeight: 600, fontSize: "13px", color: fileResult.error ? "#b91c1c" : "#065f46", marginBottom: "6px" }}>
                                      {fileResult.lst_file}
                                    </div>
                                    {fileResult.error ? (
                                      <div style={{ color: "#b91c1c", fontSize: "13px" }}>{fileResult.error}</div>
                                    ) : (
                                      <table style={{ width: "100%", minWidth: "280px", borderCollapse: "collapse", fontSize: "14px" }}>
                                        <thead>
                                          <tr style={{ borderBottom: "2px solid #10b981", color: "#0f172a" }}>
                                            <th style={{ textAlign: "left", padding: "8px 10px", color: "#0f172a" }}>Testcase</th>
                                            <th style={{ textAlign: "left", padding: "8px 10px", width: "100px", color: "#0f172a" }}>In LST</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {allTestNames.length === 0 ? (
                                            <tr>
                                              <td colSpan="2" style={{ padding: "8px 10px", color: "#64748b", textAlign: "center" }}>
                                                No test cases to display
                                              </td>
                                            </tr>
                                          ) : allTestNames.map((name) => {
                                            const normalizedName = (name || "").trim();
                                            const inLst = isPresent(normalizedName);
                                            const amb = ambiguous[normalizedName];
                                            return (
                                              <tr key={`${fileResult.lst_file}:${normalizedName}`} style={{ borderBottom: "1px solid #e2e8f0" }}>
                                                <td style={{ padding: "8px 10px", color: "#0f172a", wordBreak: "break-word" }}>
                                                  {displayName(normalizedName)}
                                                  {Array.isArray(amb) && amb.length > 0 && (
                                                    <div style={{ marginTop: "4px", fontSize: "12px", color: "#b45309" }}>
                                                      Ambiguous — matches {amb.length} lines; use the full test name.
                                                    </div>
                                                  )}
                                                </td>
                                                <td style={{ padding: "8px 10px", fontWeight: "700", color: inLst ? "#047857" : "#b45309", whiteSpace: "nowrap" }}>
                                                  {inLst ? "✓ Yes" : "✗ No"}
                                                </td>
                                              </tr>
                                            );
                                          })}
                                        </tbody>
                                      </table>
                                    )}
                                  </div>
                                );
                              })
                            ) : (
                              <div style={{ color: "#64748b" }}>No LST files to display</div>
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
                          <button onClick={handleDeprecationSave} disabled={depActionsDisabled} style={depActionsDisabled ? { ...btnTertiaryDisabled } : { ...btnTertiary }}>
                            {deprecationCreateLstLoading ? "Saving..." : "Save"}
                          </button>
                          <button onClick={handleDeprecationCreateLstCr} disabled={depActionsDisabled} style={depActionsDisabled ? { ...btnPrimaryDisabled } : { ...btnPrimary }}>
                            {deprecationCreateLstLoading ? "Creating..." : "Create Gerrit CR"}
                          </button>
                        </div>
                        {deprecationCrResult && (
                          <div style={{ marginTop: "12px", padding: "10px", background: deprecationCrResult.success ? "#ecfdf5" : "#fef2f2", borderRadius: "4px", border: "1px solid " + (deprecationCrResult.success ? "#10b981" : "#f87171"), fontSize: "13px" }}>
                            {deprecationCrResult.success && (deprecationCrResult.cr_url || deprecationCrResult.gerrit_url) && (
                              <p style={{ margin: "0 0 8px 0" }}>
                                <a href={deprecationCrResult.cr_url || deprecationCrResult.gerrit_url} target="_blank" rel="noreferrer">
                                  {deprecationCrResult.gerrit_change_id ? `Open CR ${deprecationCrResult.gerrit_change_id} →` : "Open CR →"}
                                </a>
                              </p>
                            )}
                            {(deprecationCrResult.message || deprecationCrResult.error) && <p style={{ margin: 0 }}>{deprecationCrResult.message || deprecationCrResult.error}</p>}
                            {deprecationCrResult.notes && <p style={{ margin: "8px 0 0 0", fontSize: "12px", color: "#047857" }}>{deprecationCrResult.notes}</p>}
                            {deprecationCrResult.git_error && <pre style={{ marginTop: "8px", fontSize: "11px", whiteSpace: "pre-wrap" }}>{deprecationCrResult.git_error}</pre>}
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

      {activeTab === "records" && (
        <div>
          <p className="ho-subtitle ho-intro">
            Browse saved handover and deprecation rows with all stored fields. Search by test name, filter by type, and delete records that no longer apply.
          </p>
          <div className="ho-card">
            <div className="ho-card__title">Saved records</div>
            <div style={{ display: "flex", gap: "12px", alignItems: "center", flexWrap: "wrap", marginBottom: "12px" }}>
              <input
                type="text"
                value={recordsQuery}
                onChange={(e) => setRecordsQuery(e.target.value)}
                onKeyPress={(e) => e.key === "Enter" && loadSavedRecords(e.target.value)}
                placeholder="Search by test name, LST, ticket, reviewer..."
                style={{ flex: 1, minWidth: "260px", padding: "8px 12px", fontSize: "14px", border: "1px solid #ddd", borderRadius: "4px", boxSizing: "border-box" }}
              />
              <button
                type="button"
                onClick={() => loadSavedRecords()}
                disabled={recordsLoading}
                style={{ padding: "8px 16px", background: recordsLoading ? "#94a3b8" : "#0d9488", color: "white", border: "none", borderRadius: "4px", cursor: recordsLoading ? "not-allowed" : "pointer", fontWeight: "500" }}
              >
                {recordsLoading ? "Loading..." : "Search"}
              </button>
              {canEditAnyVisible && (
                <button
                  type="button"
                  onClick={() => setRecordsEditMode((v) => !v)}
                  style={{ padding: "8px 14px", background: recordsEditMode ? "#dc2626" : "#64748b", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", fontWeight: "500" }}
                >
                  {recordsEditMode ? "Done" : "Edit"}
                </button>
              )}
            </div>
            {recordsError && (
              <div style={{ marginTop: "8px", padding: "10px 12px", background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: "6px", color: "#991b1b", fontSize: "13px" }}>
                {recordsError}
              </div>
            )}
            {!recordsLoading && !recordsError && (
              <p style={{ margin: "8px 0 0", fontSize: "13px", color: "#64748b" }}>
                {visibleSavedRecords.length} record{visibleSavedRecords.length === 1 ? "" : "s"}
              </p>
            )}
          </div>

          {recordsLoading && (
            <div className="ho-card" style={{ marginTop: "12px", fontSize: "14px", color: "#64748b" }}>Loading records...</div>
          )}

          {!recordsLoading && visibleSavedRecords.length === 0 && !recordsError && (
            <div className="ho-card" style={{ marginTop: "12px", fontSize: "14px", color: "#64748b" }}>
              No saved records match this search.
            </div>
          )}

          {!recordsLoading && visibleSavedRecords.length > 0 && (
            <div className="ho-card ho-records-wrap">
              <div className="ho-records-scroll">
                <table className="ho-table ho-records-table">
                  <thead>
                    <tr>
                      <th className="col-type">Type</th>
                      <th className="col-name">Test name</th>
                      <th className="col-date">Date</th>
                      <th className="col-lst">LST file(s)</th>
                      <th className="col-branch">Branch</th>
                      <th className="col-tickets">Tickets</th>
                      <th className="col-tickets">Bug tickets</th>
                      <th className="col-reviewers">Reviewers</th>
                      <th className="col-whom">By whom</th>
                      <th className="col-status">CR status</th>
                      <th className="col-actions">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleSavedRecords.map((r) => {
                      const extra = recordExtraSections(r);
                      const lstFiles = recordLstFiles(r);
                      const expanded = recordsExpanded.has(r._key);
                      const reviewers = Array.isArray(r.reviewers) ? r.reviewers.filter(Boolean) : [];
                      const bugTickets = uniqueTickets(r.bug_tickets);
                      const statusKey = String(r.cr_status || "").replace(/\s+/g, "_");
                      const canExpand = extra.length > 0 || lstFiles.length > 0;
                      return (
                        <React.Fragment key={r._key}>
                          <tr className="ho-records-row">
                            <td className="col-type">
                              <span className={`ho-records-kind ho-records-kind--${r._kind}`}>
                                {r._kind === "deprecation" ? "Deprecation" : "Handover"}
                              </span>
                            </td>
                            <td className="col-name">
                              <span className="ho-records-ellipsis ho-records-name" title={r.test_name || ""}>
                                {r.test_name || "-"}
                              </span>
                            </td>
                            <td className="col-date">{formatDateIST(r._date)}</td>
                            <td className="col-lst">
                              {lstFiles.length ? (
                                <span className="ho-records-lst-row" title={lstFiles.join("\n")}>
                                  <code>{lstFileBasename(lstFiles[0])}</code>
                                  {lstFiles.length > 1 ? (
                                    <span className="ho-records-more">+{lstFiles.length - 1}</span>
                                  ) : null}
                                </span>
                              ) : (
                                <span className="ho-records-empty">-</span>
                              )}
                            </td>
                            <td className="col-branch">
                              <span className="ho-records-ellipsis" title={r.branch || ""}>{r.branch || "-"}</span>
                            </td>
                            <td className="col-tickets">
                              <SavedRecordTickets record={r} />
                            </td>
                            <td className="col-tickets">
                              {bugTickets.length || r.bug_type ? (
                                <div>
                                  <TicketLinks tickets={bugTickets} />
                                  {r.bug_type ? <div className="ho-records-meta">{r.bug_type}</div> : null}
                                </div>
                              ) : (
                                <span className="ho-records-empty">-</span>
                              )}
                            </td>
                            <td className="col-reviewers">
                              {reviewers.length ? (
                                <span className="ho-records-ellipsis" title={reviewers.join(", ")}>
                                  {reviewers.map(formatByWhom).join(", ")}
                                </span>
                              ) : (
                                <span className="ho-records-empty">-</span>
                              )}
                            </td>
                            <td className="col-whom">
                              <span className="ho-records-ellipsis" title={r.by_whom || ""}>{formatByWhom(r.by_whom)}</span>
                            </td>
                            <td className="col-status">
                              {r.cr_status ? (
                                <span className={`ho-records-status ho-records-status--${statusKey}`}>{r.cr_status}</span>
                              ) : (
                                <span className="ho-records-empty">-</span>
                              )}
                            </td>
                            <td className="col-actions">
                              <div className="ho-records-actions">
                                {canExpand && (
                                  <button
                                    type="button"
                                    onClick={() => toggleRecordsExpanded(r._key)}
                                    className="ho-records-btn"
                                  >
                                    {expanded ? "Hide" : "Details"}
                                  </button>
                                )}
                                {recordsEditMode && r.can_delete && (
                                  <button
                                    type="button"
                                    onClick={() => handleRecordsDelete(r._kind, r)}
                                    className="ho-records-btn ho-records-btn--danger"
                                  >
                                    Delete
                                  </button>
                                )}
                              </div>
                            </td>
                          </tr>
                          {expanded && canExpand && (
                            <tr className="ho-records-detail-row">
                              <td colSpan={11}>
                                {lstFiles.length > 0 && (
                                  <div className="ho-records-detail-block">
                                    <div className="ho-records-detail-label">LST file(s)</div>
                                    {lstFiles.map((f) => (
                                      <div key={f} className="ho-records-detail-path"><code>{f}</code></div>
                                    ))}
                                  </div>
                                )}
                                {extra.map(([label, value]) => (
                                  <div key={label} className="ho-records-detail-block">
                                    <div className="ho-records-detail-label">{label}</div>
                                    <pre className="ho-records-extra">{String(value).trim()}</pre>
                                  </div>
                                ))}
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
