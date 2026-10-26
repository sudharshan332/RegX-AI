import React, { useEffect, useState } from "react";
import * as XLSX from "xlsx";
import api from "../api";
import { API_BASE_URL } from "../config";
import { useAuth } from "../context/AuthContext";
import "./ReleaseDashboard.css";

const API = `${API_BASE_URL}/mcp/regression/release-dashboard`;
const JIRA_URL = "https://jira.nutanix.com/browse/";
const DEFAULT_RELEASES = [
  { milestone: "7.7" },
  { milestone: "7.6" },
];
const SAVED_RELEASES_KEY = "regx.release-dashboard.releases";
const LAST_MILESTONE_PREFIX = "regx.release-dashboard.last";
const BUILTIN = new Set(DEFAULT_RELEASES.map((item) => item.milestone));
const VIEW_TYPES = [
  { id: "all", label: "All" },
  { id: "feat", label: "Feat" },
  { id: "regression", label: "Regression" },
];
const TAG_PRESETS = ["Full regression", "Upgrade", "External storage", "Other"];

function savedReleases() {
  try {
    const parsed = JSON.parse(localStorage.getItem(SAVED_RELEASES_KEY) || "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((item) => item && item.milestone && !BUILTIN.has(item.milestone));
  } catch (err) {
    return [];
  }
}

function rememberReleases(releases) {
  const extras = releases
    .filter((item) => item && item.milestone && !BUILTIN.has(item.milestone))
    .map((item) => ({
      milestone: item.milestone,
      root: item.root || "",
      branch: item.branch || "",
      sourcegraph: item.sourcegraph || "",
      lookedUp: true,
    }));
  localStorage.setItem(SAVED_RELEASES_KEY, JSON.stringify(extras));
}

function lastMilestoneKey(username) {
  return `${LAST_MILESTONE_PREFIX}.${username || "anonymous"}`;
}

function readLastMilestone(username) {
  try {
    return localStorage.getItem(lastMilestoneKey(username)) || "7.7";
  } catch (err) {
    return "7.7";
  }
}

const COLOR_LABEL = {
  green: "Passed",
  not_run: "Not run",
};

const COLOR_HELP = {
  black: "Not handed over, or only some tests match. The number is the percent handed over.",
  red: "Handed over and executed. Pass rate is 80% or below.",
  yellow: "Handed over and executed. Pass rate is above 80%, with failures.",
  green: "Handed over, executed, and all passed.",
  not_run: "Handed over, and at least one test has no result.",
};

const TEST_HELP = {
  black: "Not handed over.",
  red: "Failed.",
  green: "Passed.",
  not_run: "Not run on this branch.",
};

function ColorTip({ color, help, className, children }) {
  const text = help || COLOR_HELP[color];
  return (
    <span className={`rd-color${className ? ` ${className}` : ""}`}>
      {children}
      {text ? <span className="rd-color-note">{text}</span> : null}
    </span>
  );
}

function jiraId(ticket) {
  const match = String(ticket || "").match(/[A-Z][A-Z0-9]+-\d+/i);
  return match ? match[0].toUpperCase() : String(ticket || "");
}

function statusLabel(feat) {
  if (feat.color === "black") {
    const pct = feat.total ? Math.round((100 * feat.handed_over) / feat.total) : 0;
    return `${pct}%`;
  }
  if (feat.pass_rate != null) return `${feat.pass_rate}%`;
  return COLOR_LABEL[feat.color] || "";
}

function countOf(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return 0;
  return number;
}

function executionPct(feat) {
  const total = countOf(feat.total);
  if (!total) return null;
  const executed = Math.min(countOf(feat.passed) + countOf(feat.failed), total);
  return Math.round((100 * executed) / total);
}

function executedPassPct(feat) {
  const executed = countOf(feat.passed) + countOf(feat.failed);
  if (!executed) return 0;
  return Math.round((100 * countOf(feat.passed)) / executed);
}

function pctLabel(pct) {
  return pct == null ? "—" : `${pct}%`;
}

function bandColor(pct) {
  if (pct == null || pct <= 0) return "black";
  if (pct <= 79) return "red";
  if (pct < 100) return "yellow";
  return "green";
}

const BAND_HELP = {
  black: "0%.",
  red: "1% to 79%.",
  yellow: "80% to 99%.",
  green: "100%.",
};

function resultLabel(test) {
  const status = (test.status || "").trim();
  if (!status || status.toLowerCase() === "not run" || status.toLowerCase() === "not_run") {
    return "Not run";
  }
  return status;
}

function testColor(test) {
  if (!test.in_regression) return "black";
  const status = (test.status || "").trim().toLowerCase();
  if (["succeeded", "passed", "success", "pass"].includes(status)) return "green";
  if (["failed", "failure", "fail", "error"].includes(status)) return "red";
  return "not_run";
}

function jiraSearchUrl(tickets) {
  const ids = [];
  (tickets || []).forEach((ticket) => {
    const id = jiraId(ticket);
    if (id && !ids.includes(id)) ids.push(id);
  });
  if (!ids.length) return "";
  return `https://jira.nutanix.com/issues/?jql=issuekey%20in%20(${ids.join("%2C")})`;
}

function formatQi(value) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (Number.isNaN(number)) return "—";
  if (Number.isInteger(number)) return `${number}%`;
  const fixed = number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
  return `${fixed}%`;
}

function riskLevel(impact) {
  if (impact == null) return null;
  if (impact <= -5) return { label: "Critical", tone: "rd-risk-critical" };
  if (impact <= -2) return { label: "High", tone: "rd-risk-high" };
  if (impact <= -1) return { label: "Medium", tone: "rd-risk-medium" };
  return { label: "Low", tone: "rd-risk-low" };
}

function FeatTests({ title, tests }) {
  return (
    <div className="rd-split">
      <h3>{title}</h3>
      {tests.length === 0 ? (
        <p className="rd-status">None</p>
      ) : (
        <table className="rd-table">
          <thead>
            <tr>
              <th>Test</th>
              <th>Status</th>
              <th>Bug type</th>
              <th>JIRA</th>
              <th>Owner</th>
            </tr>
          </thead>
          <tbody>
            {tests.map((test) => {
              const color = testColor(test);
              return (
              <tr key={test.name} className={`rd-test-row rd-test-${color}`}>
                <td className="rd-test-name">
                  {test.name}
                  <span className="rd-color-note">{TEST_HELP[color]}</span>
                </td>
                <td>{resultLabel(test)}</td>
                <td>{test.issue_type || "—"}</td>
                <td>
                  {(test.tickets || []).length === 0 && "—"}
                  {(test.tickets || []).map((ticket) => {
                    const id = jiraId(ticket);
                    return (
                      <a key={id} href={`${JIRA_URL}${id}`} target="_blank" rel="noreferrer">
                        {id}
                      </a>
                    );
                  })}
                </td>
                <td>{(test.owners || []).join(", ") || "—"}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className="rd-card">
      <div className="rd-card-label">{label}</div>
      <div className={`rd-card-value${tone ? ` ${tone}` : ""}`}>{value}</div>
    </div>
  );
}

function GapTable({ rows }) {
  if (!rows || rows.length === 0) {
    return <p className="rd-status">None</p>;
  }
  return (
    <table className="rd-table rd-table-left">
      <thead>
        <tr>
          <th>Test</th>
          <th>TCMS</th>
          <th>JITA</th>
          <th>Tags</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <td className="rd-test-name">{row.name}</td>
            <td>{row.tcms_status || "—"}</td>
            <td>{row.jita_status || "—"}</td>
            <td>{(row.jita_tags || []).join(", ") || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function ReleaseDashboard() {
  const { user } = useAuth();
  const username = user?.username || user?.sub || "";
  const [releases, setReleases] = useState(() => [...DEFAULT_RELEASES, ...savedReleases()]);
  const [milestone, setMilestone] = useState(() => readLastMilestone(username));
  const [tab, setTab] = useState("summary");
  const [viewType, setViewType] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [openFeats, setOpenFeats] = useState(() => new Set());
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const [addError, setAddError] = useState("");
  const [addBusy, setAddBusy] = useState(false);
  const [summary, setSummary] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [tags, setTags] = useState([]);
  const [tagsFor, setTagsFor] = useState("");
  const [tagLabel, setTagLabel] = useState(TAG_PRESETS[0]);
  const [customLabel, setCustomLabel] = useState("");
  const [tagName, setTagName] = useState("");
  const [tagError, setTagError] = useState("");
  const [tagBusy, setTagBusy] = useState(false);
  const [tagsOpen, setTagsOpen] = useState(false);
  const [draftTags, setDraftTags] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareError, setCompareError] = useState("");
  const [gap, setGap] = useState("sync_gap");
  const [openComponent, setOpenComponent] = useState("");
  const [qi, setQi] = useState(null);
  const [qiLoading, setQiLoading] = useState(false);
  const [qiError, setQiError] = useState("");

  const selected = releases.find((item) => item.milestone === milestone) || { milestone };

  useEffect(() => {
    try {
      localStorage.setItem(lastMilestoneKey(username), milestone);
    } catch (err) {
      // The selector still works if storage is blocked.
    }
  }, [milestone, username]);

  useEffect(() => {
    if (releases.some((item) => item.milestone === milestone)) return;
    setReleases((prev) => [...prev, { milestone }]);
  }, [milestone, releases]);

  useEffect(() => {
    if (tab !== "feats") return undefined;
    let cancelled = false;
    const current = releases.find((item) => item.milestone === milestone) || { milestone };
    setLoading(true);
    setError("");
    setData(null);
    setOpenFeats(new Set());
    const params = { milestone };
    if (current.root) params.root = current.root;
    if (current.branch) params.branch = current.branch;
    api
      .get(API, { params, timeout: 120000 })
      .then((response) => {
        if (!cancelled) setData(response.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setData(null);
          setError(err.response?.data?.error || err.message || "Failed to load release dashboard");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, milestone, releases]);

  useEffect(() => {
    if (tab !== "summary") return undefined;
    let cancelled = false;
    const current = releases.find((item) => item.milestone === milestone) || { milestone };
    setSummaryLoading(true);
    setSummaryError("");
    setSummary(null);
    setComparison(null);
    setCompareError("");
    setQi(null);
    setQiError("");
    const params = { milestone, type: viewType };
    if (current.root) params.root = current.root;
    if (current.branch) params.branch = current.branch;
    api
      .get(`${API}/summary`, { params, timeout: 180000 })
      .then((response) => {
        if (!cancelled) setSummary(response.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setSummary(null);
          setSummaryError(err.response?.data?.error || err.message || "Failed to load summary");
        }
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, milestone, releases, viewType]);

  useEffect(() => {
    let cancelled = false;
    setTags([]);
    setTagsFor("");
    setTagError("");
    api
      .get(`${API}/jita-tags`, { params: { milestone }, timeout: 60000 })
      .then((response) => {
        if (!cancelled) {
          setTags(response.data?.tags || []);
          setTagsFor(milestone);
        }
      })
      .catch((err) => {
        if (!cancelled) setTagError(err.response?.data?.error || err.message || "Failed to load JITA tags");
      });
    return () => {
      cancelled = true;
    };
  }, [milestone]);

  useEffect(() => {
    if (tab !== "summary" || !summary || tagsFor !== milestone || tags.length === 0) return undefined;
    let cancelled = false;
    const current = releases.find((item) => item.milestone === milestone) || { milestone };
    setCompareLoading(true);
    setCompareError("");
    const body = { milestone, type: viewType };
    if (current.root) body.root = current.root;
    if (current.branch) body.branch = current.branch;
    api
      .post(`${API}/compare`, body, { timeout: 180000 })
      .then((response) => {
        if (!cancelled) setComparison(response.data);
      })
      .catch((err) => {
        if (!cancelled) {
          setComparison(null);
          setCompareError(err.response?.data?.error || err.message || "JITA comparison failed");
        }
      })
      .finally(() => {
        if (!cancelled) setCompareLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tab, summary, tags, tagsFor, milestone, releases, viewType]);

  function addRelease(event) {
    event.preventDefault();
    const nos = draft.trim();
    if (!nos || addBusy) return;
    setAddBusy(true);
    setAddError("");
    api
      .post(`${API}/lookup`, { nos }, { timeout: 60000 })
      .then((response) => {
        const info = response.data || {};
        if (!info.milestone) {
          setAddError("No feat folder found for that version");
          return;
        }
        setReleases((prev) => {
          const rest = prev.filter((item) => item.milestone !== info.milestone);
          const next = [...rest, { ...info, lookedUp: true }];
          rememberReleases(next);
          return next;
        });
        const pending = draftTags;
        const done = () => {
          setMilestone(info.milestone);
          setDraft("");
          setDraftTags([]);
          setAdding(false);
          setTagsOpen(false);
        };
        if (pending.length === 0) {
          done();
          return;
        }
        api
          .put(`${API}/jita-tags`, { milestone: info.milestone, tags: pending }, { timeout: 60000 })
          .then(() => done())
          .catch((err) => {
            done();
            setTagError(err.response?.data?.error || err.message || "Could not save JITA tags");
            setTagsOpen(true);
          });
      })
      .catch((err) => {
        setAddError(err.response?.data?.error || err.message || "Could not find that release");
      })
      .finally(() => setAddBusy(false));
  }

  function saveTags(next) {
    setTagBusy(true);
    setTagError("");
    api
      .put(`${API}/jita-tags`, { milestone, tags: next }, { timeout: 60000 })
      .then((response) => {
        setTags(response.data?.tags || next);
        setTagsFor(milestone);
        setTagName("");
        setCustomLabel("");
      })
      .catch((err) => {
        setTagError(err.response?.data?.error || err.message || "Could not save JITA tags");
      })
      .finally(() => setTagBusy(false));
  }

  function addDraftTag() {
    const label = (tagLabel === "Other" ? customLabel : tagLabel).trim();
    const tag = tagName.trim();
    if (!label || !tag) return;
    setDraftTags((prev) => [...prev, { label, tag }]);
    setTagName("");
    setCustomLabel("");
  }

  function addTag(event) {
    event.preventDefault();
    const label = (tagLabel === "Other" ? customLabel : tagLabel).trim();
    const tag = tagName.trim();
    if (!label || !tag || tagBusy) return;
    saveTags([...tags, { label, tag }]);
  }

  function loadTopQi() {
    if (qiLoading) return;
    const current = releases.find((item) => item.milestone === milestone) || { milestone };
    setQiLoading(true);
    setQiError("");
    const body = { milestone, type: viewType };
    if (current.root) body.root = current.root;
    if (current.branch) body.branch = current.branch;
    api
      .post(`${API}/top-qi`, body, { timeout: 180000 })
      .then((response) => setQi(response.data))
      .catch((err) => {
        setQi(null);
        setQiError(err.response?.data?.error || err.message || "QI lookup failed");
      })
      .finally(() => setQiLoading(false));
  }

  const feats = data?.feats || [];
  const execution = summary?.execution || {};
  const handover = summary?.handover;
  const report = comparison?.comparison;
  const jitaByComponent = {};
  (report?.components || []).forEach((row) => {
    jitaByComponent[row.component] = row;
  });
  const gapKey = ["sync_gap", "status_mismatch", "not_triggered", "outside_tcms"].includes(gap)
    ? gap
    : "sync_gap";
  const gapBlock = report ? report[gapKey] : null;

  function toggleFeat(name) {
    setOpenFeats((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function exportExcel() {
    const rows = [[
      "Feat", "Handed over", "Passed", "Failed", "Not run", "Pass %", "Handover %", "Execution %", "Pass %",
    ]];
    feats.forEach((feat) => {
      const handed = (feat.tests || []).filter((test) => test.in_regression);
      const pending = (feat.tests || []).filter((test) => !test.in_regression);
      rows.push([
        feat.name,
        `${feat.handed_over}/${feat.total}`,
        feat.passed,
        feat.failed,
        feat.not_run,
        feat.pass_rate == null ? "—" : `${feat.pass_rate}%`,
        statusLabel(feat),
        pctLabel(executionPct(feat)),
        pctLabel(executedPassPct(feat)),
      ]);
      rows.push(["Handed over", handed.length, "Not handed over", pending.length]);
      const addTests = (title, tests) => {
        if (title === "Handed over" && tests.length === 0) return;
        rows.push([title]);
        if (tests.length === 0) {
          rows.push(["None"]);
          return;
        }
        rows.push(["Test", "Status", "Bug type", "JIRA", "Owner"]);
        tests.forEach((test) => {
          rows.push([
            test.name,
            resultLabel(test),
            test.issue_type || "—",
            (test.tickets || []).map(jiraId).join(", ") || "—",
            (test.owners || []).join(", ") || "—",
          ]);
        });
      };
      addTests("Handed over", handed);
      addTests("Not handed over", pending);
      rows.push([]);
    });
    const sheet = XLSX.utils.aoa_to_sheet(rows);
    sheet["!cols"] = [
      { wch: 80 }, { wch: 16 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 12 }, { wch: 14 }, { wch: 14 }, { wch: 12 },
    ];
    const book = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(book, sheet, "Release");
    XLSX.writeFile(book, `release-${milestone}.xlsx`);
  }

  return (
    <div className="rd-page">
      <div className="rd-top">
        <div className="rd-heading">
          <h1>Release Dashboard</h1>
          <div className="rd-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "summary"}
              className={`rd-tab${tab === "summary" ? " is-active" : ""}`}
              onClick={() => setTab("summary")}
            >
              Summary
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "feats"}
              className={`rd-tab${tab === "feats" ? " is-active" : ""}`}
              onClick={() => setTab("feats")}
            >
              Feat Readiness
            </button>
          </div>
        </div>
        <div className="rd-release">
          <label htmlFor="rd-release">Release</label>
          <select
            id="rd-release"
            value={milestone}
            onChange={(event) => setMilestone(event.target.value)}
          >
            {releases.map((release) => (
              <option key={release.milestone} value={release.milestone}>
                {release.milestone}
              </option>
            ))}
          </select>
          <button
            type="button"
            className={`rd-add rd-tags-btn${tagsOpen ? " is-active" : ""}`}
            title="Add or delete JITA tags"
            onClick={() => setTagsOpen((open) => !open)}
          >
            Tags
          </button>
          {tagsOpen && !adding ? (
            <div className="rd-tag-pop">
              <strong>JITA tags for {milestone}</strong>
              {tags.length === 0 ? <p className="rd-status">No tags yet.</p> : (
                <ul className="rd-tag-list">
                  {tags.map((item) => (
                    <li key={`${item.label}:${item.tag}`}>
                      <span>{item.label}</span>
                      <code>{item.tag}</code>
                      <button type="button" disabled={tagBusy} onClick={() => saveTags(tags.filter((row) => row !== item))}>
                        Delete
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <form className="rd-tag-form" onSubmit={addTag}>
                <select value={tagLabel} onChange={(event) => setTagLabel(event.target.value)} aria-label="Tag kind">
                  {TAG_PRESETS.map((preset) => (
                    <option key={preset} value={preset}>{preset}</option>
                  ))}
                </select>
                {tagLabel === "Other" ? (
                  <input
                    value={customLabel}
                    onChange={(event) => setCustomLabel(event.target.value)}
                    placeholder="Label"
                    aria-label="Custom tag label"
                  />
                ) : null}
                <input
                  value={tagName}
                  onChange={(event) => setTagName(event.target.value)}
                  placeholder="JITA tester tag"
                  aria-label="JITA tester tag"
                />
                <button type="submit" disabled={tagBusy}>Add tag</button>
              </form>
              {tagError ? <p className="rd-error">{tagError}</p> : null}
            </div>
          ) : null}
          {adding ? (
            <form className="rd-add-form" onSubmit={addRelease}>
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="7.5.1"
                aria-label="NOS version"
                autoFocus
              />
              <select value={tagLabel} onChange={(event) => setTagLabel(event.target.value)} aria-label="Tag kind">
                {TAG_PRESETS.map((preset) => (
                  <option key={preset} value={preset}>{preset}</option>
                ))}
              </select>
              {tagLabel === "Other" ? (
                <input
                  value={customLabel}
                  onChange={(event) => setCustomLabel(event.target.value)}
                  placeholder="Label"
                  aria-label="Custom tag label"
                />
              ) : null}
              <input
                value={tagName}
                onChange={(event) => setTagName(event.target.value)}
                placeholder="JITA tester tag"
                aria-label="JITA tester tag"
              />
              <button type="button" onClick={addDraftTag}>Add tag</button>
              <button type="submit" disabled={addBusy}>Add</button>
              <button type="button" disabled={addBusy} onClick={() => { setAdding(false); setAddError(""); setDraftTags([]); }}>Cancel</button>
              {draftTags.length > 0 ? (
                <ul className="rd-tag-list">
                  {draftTags.map((item) => (
                    <li key={`${item.label}:${item.tag}`}>
                      <span>{item.label}</span>
                      <code>{item.tag}</code>
                      <button type="button" onClick={() => setDraftTags((prev) => prev.filter((row) => row !== item))}>Delete</button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </form>
          ) : (
            <button
              type="button"
              className="rd-add"
              title="Add a NOS version"
              onClick={() => { setAdding(true); setAddError(""); setDraftTags([]); setTagsOpen(false); }}
            >
              +
            </button>
          )}
          {addBusy ? (
            <span className="rd-adding" role="status">
              <span className="rd-spin" aria-hidden="true" />
              Adding {draft.trim()}
            </span>
          ) : null}
          {addError ? <span className="rd-add-error">{addError}</span> : null}
          {selected.branch && selected.milestone !== selected.branch ? (
            <span className="rd-branch" title={selected.sourcegraph || selected.branch}>{selected.branch}</span>
          ) : null}
        </div>
      </div>

      {tab === "summary" && (
        <div role="tabpanel">
          <div className="rd-typebar">
            <div className="rd-types" role="group" aria-label="TCMS type">
              {VIEW_TYPES.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`rd-type${viewType === item.id ? " is-active" : ""}`}
                  onClick={() => setViewType(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            {summary?.tcms_url ? (
              <a className="rd-tcms-link" href={summary.tcms_url} target="_blank" rel="noreferrer">
                Open TCMS
              </a>
            ) : null}
          </div>

          {summaryLoading && <p className="rd-status">Loading TCMS summary…</p>}
          {summaryError && <p className="rd-error">{summaryError}</p>}

          {summary && !summaryLoading && (
            <>
              <div className="rd-cards">
                <Stat label="Total" value={execution.total ?? 0} />
                <Stat label="Passed" value={execution.passed ?? 0} tone="is-ok" />
                <Stat label="Failed" value={execution.failed ?? 0} tone="is-bad" />
                <Stat label="Not run" value={execution.not_run ?? 0} />
                <Stat label="Run %" value={formatQi(execution.run_percentage)} />
                <Stat label="QI" value={formatQi(execution.qi)} />
                <Stat
                  label="Triage %"
                  value={
                    execution.total_triaged != null && execution.triage_percentage != null
                      ? `${execution.total_triaged} (${formatQi(execution.triage_percentage)})`
                      : formatQi(execution.triage_percentage)
                  }
                />
              </div>

              {summary.show_regression && (
                <section className="rd-panel">
                  <h2>{viewType === "regression" ? "Regression execution" : "Execution status"}</h2>
                  <p className="rd-note">
                    TCMS is the release record. Passed {execution.passed ?? 0} of {execution.total ?? 0} tests
                    {execution.qi != null ? `, QI ${formatQi(execution.qi)}` : ""}.
                  </p>
                </section>
              )}

              {summary.show_handover && handover && (
                <section className="rd-panel">
                  <h2>Feat handover</h2>
                  <div className="rd-cards">
                    <Stat label="Feats" value={handover.feat_count ?? 0} />
                    <Stat label="Pending handover" value={handover.pending_feats ?? 0} />
                    <Stat label="Tests not handed over" value={handover.tests_not_handed_over ?? 0} />
                    <Stat label="Tests not run" value={handover.tests_not_run ?? 0} />
                  </div>
                </section>
              )}

              <section className="rd-panel">
                <div className="rd-panel-head">
                  <h2>Components</h2>
                  {summary.components_url ? (
                    <a className="rd-tcms-link" href={summary.components_url} target="_blank" rel="noreferrer">
                      Open TCMS components
                    </a>
                  ) : null}
                </div>
                <p className="rd-note">
                  Counts follow the TCMS components tab for this type. QI below 90% is yellow and below 85% is red.
                  Active bugs and top QI bugs use the newest JITA task across the saved tags.
                </p>
                {(summary.components || []).length === 0 ? (
                  <p className="rd-status">No component data for this type.</p>
                ) : (
                  <table className="rd-table rd-table-left rd-components">
                    <thead>
                      <tr>
                        <th>Component</th>
                        <th>QI</th>
                        <th>Total</th>
                        <th>Run</th>
                        <th>Not run</th>
                        <th>Passed</th>
                        <th>Failed</th>
                        <th>Triaged</th>
                        <th>Open bugs</th>
                        <th>Active bugs</th>
                        <th>Top QI bugs</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(summary.components || []).map((row) => {
                        const jita = jitaByComponent[row.component];
                        const isOpen = openComponent === row.component;
                        const active = jita?.active_bugs || [];
                        const topQi = jita?.top_qi || [];
                        const jitaReady = Boolean(report);
                        return (
                          <React.Fragment key={row.component}>
                            <tr>
                              <td>
                                {row.bugs_url ? (
                                  <a href={row.bugs_url} target="_blank" rel="noreferrer">{row.component}</a>
                                ) : row.component}
                              </td>
                              <td>
                                <span className={`rd-qi rd-qi-${row.qi_tone || "none"}`} title={row.qi_source === "tcms_metrics" ? "TCMS components QI" : "TCMS aggregate unavailable"}>
                                  {formatQi(row.qi)}
                                </span>
                              </td>
                              <td>{row.total ?? 0}</td>
                              <td>{row.run ?? 0}</td>
                              <td>{row.not_run ?? 0}</td>
                              <td>{row.passed ?? 0}</td>
                              <td>{row.failed ?? 0}</td>
                              <td>
                                {row.total_triaged != null && row.triaged_percentage != null
                                  ? `${row.total_triaged} (${formatQi(row.triaged_percentage)})`
                                  : formatQi(row.triaged_percentage)}
                              </td>
                              <td>{row.open_bug_count ?? 0}</td>
                              <td>
                                {!jitaReady ? (tags.length === 0 ? "Add tags" : (compareLoading ? "…" : "—")) : (
                                  <span className="rd-cell-actions">
                                    <button type="button" className="rd-feat-link" onClick={() => setOpenComponent(isOpen ? "" : row.component)}>
                                      {jita?.active_count ?? 0}
                                    </button>
                                    {active.length > 0 ? (
                                      <a className="rd-jira-btn" href={jiraSearchUrl(active.map((bug) => bug.ticket))} target="_blank" rel="noreferrer">Jira</a>
                                    ) : null}
                                  </span>
                                )}
                              </td>
                              <td>
                                {!jitaReady ? (tags.length === 0 ? "Add tags" : (compareLoading ? "…" : "—")) : (
                                  <span className="rd-cell-actions">
                                    <span>{topQi[0] ? jiraId(topQi[0].ticket) : "—"}</span>
                                    {topQi.length > 0 ? (
                                      <a className="rd-jira-btn" href={jiraSearchUrl(topQi.map((bug) => bug.ticket))} target="_blank" rel="noreferrer">Jira</a>
                                    ) : null}
                                  </span>
                                )}
                              </td>
                            </tr>
                            {isOpen && jitaReady && (
                              <tr className="rd-expand">
                                <td colSpan={11}>
                                  <div className="rd-split">
                                    <div className="rd-panel-head">
                                      <h3>Active bugs</h3>
                                      <span className="rd-cell-actions">
                                        {active.length > 0 ? (
                                          <a className="rd-jira-btn" href={jiraSearchUrl(active.map((bug) => bug.ticket))} target="_blank" rel="noreferrer">Jira</a>
                                        ) : null}
                                        <button type="button" className="rd-jira-btn" onClick={() => setOpenComponent("")}>Close</button>
                                      </span>
                                    </div>
                                    {active.length === 0 ? <p className="rd-status">None on the latest JITA run.</p> : (
                                      <ul className="rd-bug-list">
                                        {active.map((bug) => (
                                          <li key={bug.ticket}>
                                            <a href={`${JIRA_URL}${jiraId(bug.ticket)}`} target="_blank" rel="noreferrer">{jiraId(bug.ticket)}</a>
                                            <span className={`rd-match rd-match-${bug.match}`}>{bug.match === "different" ? "Different from TCMS" : "Same as TCMS"}</span>
                                            <span className="rd-test-name">{(bug.tests || []).join(", ")}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                    <div className="rd-panel-head">
                                      <h3>Top QI bugs</h3>
                                      {topQi.length > 0 ? (
                                        <a className="rd-jira-btn" href={jiraSearchUrl(topQi.map((bug) => bug.ticket))} target="_blank" rel="noreferrer">Jira</a>
                                      ) : null}
                                    </div>
                                    {topQi.length === 0 ? <p className="rd-status">None</p> : (
                                      <ul className="rd-bug-list">
                                        {topQi.map((bug) => (
                                          <li key={bug.ticket}>
                                            <a href={`${JIRA_URL}${jiraId(bug.ticket)}`} target="_blank" rel="noreferrer">{jiraId(bug.ticket)}</a>
                                            <span>{bug.testcase_count} tests, QI impact {bug.qi_impact}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                    {(row.open_bugs || []).length > 0 && (
                                      <>
                                        <h3>Open TCMS bugs</h3>
                                        <p>
                                          {(row.open_bugs || []).map((ticket) => (
                                            <a key={ticket} href={`${JIRA_URL}${jiraId(ticket)}`} target="_blank" rel="noreferrer">{jiraId(ticket)}</a>
                                          ))}
                                        </p>
                                      </>
                                    )}
                                  </div>
                                </td>
                              </tr>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="rd-panel">
                <h2>JITA comparison</h2>
                <p className="rd-note">
                  Tags for this release are added and deleted next to the release selector. Full regression, upgrade,
                  and external storage together are the execution status compared with TCMS.
                </p>
                {tags.length === 0 && !tagError ? (
                  <p className="rd-status">No JITA tags yet. Add tags beside the release selector.</p>
                ) : null}

                {tags.length > 0 && compareLoading && <p className="rd-status">Comparing TCMS with JITA…</p>}
                {compareError && <p className="rd-error">{compareError}</p>}
                {report && (
                  <>
                    <h3>Combined execution</h3>
                    <div className="rd-cards">
                      <Stat label="JITA tests" value={report.combined?.total ?? 0} />
                      <Stat label="JITA passed" value={report.combined?.passed ?? 0} tone="is-ok" />
                      <Stat label="JITA failed" value={report.combined?.failed ?? 0} tone="is-bad" />
                      <Stat label="Matched TCMS" value={report.matched_count ?? 0} />
                    </div>
                    <table className="rd-table rd-table-left">
                      <thead>
                        <tr>
                          <th>Kind</th>
                          <th>Tag</th>
                          <th>Tasks</th>
                          <th>Passed</th>
                          <th>Failed</th>
                          <th>Other</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(report.per_tag || []).map((row) => (
                          <tr key={`${row.label}:${row.tag}`}>
                            <td>{row.label}</td>
                            <td><code>{row.tag}</code>{row.error ? <div className="rd-add-error">{row.error}</div> : null}</td>
                            <td>{row.task_count ?? 0}</td>
                            <td>{row.passed ?? 0}</td>
                            <td>{row.failed ?? 0}</td>
                            <td>{row.not_run ?? 0}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <h3>TCMS and JITA differences</h3>
                    <p className="rd-note">
                      Highlighted rows are in the TCMS release record but missing, not synced, or disagreed with by JITA.
                    </p>
                    <div className="rd-types">
                      <button type="button" className={`rd-type${gapKey === "sync_gap" ? " is-active" : ""}`} onClick={() => setGap("sync_gap")}>
                        Sync gap ({report.sync_gap?.count ?? 0})
                      </button>
                      <button type="button" className={`rd-type${gapKey === "status_mismatch" ? " is-active" : ""}`} onClick={() => setGap("status_mismatch")}>
                        Status mismatch ({report.status_mismatch?.count ?? 0})
                      </button>
                      <button type="button" className={`rd-type${gapKey === "not_triggered" ? " is-active" : ""}`} onClick={() => setGap("not_triggered")}>
                        Not in JITA ({report.not_triggered?.count ?? 0})
                      </button>
                      <button type="button" className={`rd-type${gapKey === "outside_tcms" ? " is-active" : ""}`} onClick={() => setGap("outside_tcms")}>
                        Outside TCMS ({report.outside_tcms?.count ?? 0})
                      </button>
                    </div>
                    <GapTable rows={gapBlock?.items || []} />
                    {gapBlock && gapBlock.count > (gapBlock.items || []).length ? (
                      <p className="rd-status">Showing {(gapBlock.items || []).length} of {gapBlock.count}.</p>
                    ) : null}
                  </>
                )}
              </section>

              <section className="rd-panel">
                <div className="rd-panel-head">
                  <h2>Top QI bugs</h2>
                  <button type="button" className="rd-action" onClick={loadTopQi} disabled={qiLoading || summaryLoading}>
                    {qiLoading ? "Loading QI…" : "Load top QI bugs"}
                  </button>
                </div>
                <p className="rd-note">Tickets on more than 5 failed tests in this TCMS set, same cutoff as Home bulk issues.</p>
                {qiError && <p className="rd-error">{qiError}</p>}
                {qi && (qi.bugs || []).length === 0 && <p className="rd-status">No bulk issues for this type.</p>}
                {qi && (qi.bugs || []).length > 0 && (
                  <table className="rd-table rd-table-left">
                    <thead>
                      <tr>
                        <th>Ticket</th>
                        <th>Tests</th>
                        <th>Avg QI</th>
                        <th>QI impact</th>
                        <th>Overall QI impact</th>
                        <th>Risk</th>
                      </tr>
                    </thead>
                    <tbody>
                      {qi.bugs.map((bug) => {
                        const risk = riskLevel(bug.overall_qi_impact);
                        const id = jiraId(bug.ticket);
                        return (
                          <tr key={bug.ticket}>
                            <td>
                              <a href={`${JIRA_URL}${id}`} target="_blank" rel="noreferrer">{id}</a>
                            </td>
                            <td>{bug.testcase_count}</td>
                            <td>{bug.average_qi != null ? bug.average_qi : "—"}</td>
                            <td>{bug.qi_impact != null ? bug.qi_impact : "—"}</td>
                            <td>{bug.overall_qi_impact != null ? bug.overall_qi_impact : "—"}</td>
                            <td>{risk ? <span className={`rd-risk ${risk.tone}`}>{risk.label}</span> : "—"}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </section>
            </>
          )}
        </div>
      )}

      {tab === "feats" && (
        <div role="tabpanel">
          {data && !loading && (
            <div className="rd-metrics">
              <div className="rd-metric">{data.feat_count} feats</div>
              <button type="button" className="rd-export" onClick={exportExcel}>Export</button>
            </div>
          )}

          {loading && <p className="rd-status">Loading…</p>}
          {error && <p className="rd-error">{error}</p>}

          {!loading && !error && data && feats.length === 0 && (
            <p className="rd-status">No feats for this release.</p>
          )}

          {feats.length > 0 && (
            <>
            <div className="rd-legend">
              <span>Execution % is (passed + failed) / total. Pass % next to it is passed / (passed + failed).</span>
              <span className="rd-legend-item"><span className="rd-swatch rd-black" />0%</span>
              <span className="rd-legend-item"><span className="rd-swatch rd-red" />1% to 79%</span>
              <span className="rd-legend-item"><span className="rd-swatch rd-yellow" />80% to 99%</span>
              <span className="rd-legend-item"><span className="rd-swatch rd-green" />100%</span>
            </div>
            <table className="rd-table">
              <thead>
                <tr>
                  <th>Feat</th>
                  <th>Handed over</th>
                  <th>Passed</th>
                  <th>Failed</th>
                  <th>Not run</th>
                  <th>Pass %</th>
                  <th>Handover %</th>
                  <th>Execution %</th>
                  <th>Pass %</th>
                </tr>
              </thead>
              <tbody>
                {feats.map((feat) => {
                  const isOpen = openFeats.has(feat.name);
                  const tests = feat.tests || [];
                  const handed = tests.filter((test) => test.in_regression);
                  const pending = tests.filter((test) => !test.in_regression);
                  return (
                    <React.Fragment key={feat.name}>
                      <tr>
                        <td>
                          <button
                            type="button"
                            className="rd-feat-link"
                            onClick={() => toggleFeat(feat.name)}
                          >
                            {isOpen ? "▾" : "▸"} {feat.name}
                          </button>
                        </td>
                        <td>{feat.handed_over}/{feat.total}</td>
                        <td>{feat.passed}</td>
                        <td>{feat.failed}</td>
                        <td>{feat.not_run}</td>
                        <td>{feat.pass_rate == null ? "—" : `${feat.pass_rate}%`}</td>
                        <td>
                          <ColorTip color={feat.color} className="rd-color-end">
                            <span className={`rd-status-box rd-${feat.color}`}>{statusLabel(feat)}</span>
                          </ColorTip>
                        </td>
                        <td>
                          <ColorTip color={bandColor(executionPct(feat))} help={`(passed + failed) / total. ${BAND_HELP[bandColor(executionPct(feat))]}`} className="rd-color-end">
                            <span className={`rd-status-box rd-${bandColor(executionPct(feat))}`}>{pctLabel(executionPct(feat))}</span>
                          </ColorTip>
                        </td>
                        <td>
                          <ColorTip color={bandColor(executedPassPct(feat))} help={`passed / (passed + failed). ${BAND_HELP[bandColor(executedPassPct(feat))]}`} className="rd-color-end">
                            <span className={`rd-status-box rd-${bandColor(executedPassPct(feat))}`}>{pctLabel(executedPassPct(feat))}</span>
                          </ColorTip>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="rd-expand">
                          <td colSpan={9}>
                            <div className="rd-counts">
                              <div>Handed over <strong>{handed.length}</strong></div>
                              <div>Not handed over <strong>{pending.length}</strong></div>
                            </div>
                            {handed.length > 0 && <FeatTests title="Handed over" tests={handed} />}
                            <FeatTests title="Not handed over" tests={pending} />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
            </>
          )}
        </div>
      )}
    </div>
  );
}
