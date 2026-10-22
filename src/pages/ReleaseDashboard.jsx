import React, { useEffect, useState } from "react";
import api from "../api";
import { API_BASE_URL } from "../config";
import "./ReleaseDashboard.css";

const API = `${API_BASE_URL}/mcp/regression/release-dashboard`;
const JIRA_URL = "https://jira.nutanix.com/browse/";
const RELEASES = ["7.7", "7.6"];

const COLOR_LABEL = {
  green: "Passed",
  not_run: "Not run",
};

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

function testColor(test) {
  if (!test.in_regression) return "black";
  const status = (test.status || "").trim().toLowerCase();
  if (["succeeded", "passed", "success", "pass"].includes(status)) return "green";
  if (["failed", "failure", "fail", "error"].includes(status)) return "red";
  return "not_run";
}

function FeatTests({ title, tests }) {
  return (
    <div className="rd-split">
      <h3>{title} ({tests.length})</h3>
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
                <td className="rd-test-name">{test.name}</td>
                <td>{test.status || "—"}</td>
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

export default function ReleaseDashboard() {
  const [milestone, setMilestone] = useState("7.7");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [openFeat, setOpenFeat] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setData(null);
    setOpenFeat("");
    api
      .get(API, { params: { milestone }, timeout: 180000 })
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
  }, [milestone]);

  const feats = data?.feats || [];

  return (
    <div className="rd-page">
      <header className="rd-header">
        <h1>Release Dashboard</h1>
        <p>
          Feats are the folders under{" "}
          {data?.sourcegraph ? (
            <a href={data.sourcegraph} target="_blank" rel="noreferrer">{data.root}</a>
          ) : (
            <span>the release tree</span>
          )}
          . Each folder under FEATS is its own row. A feat is fully handed over only when its tests also match the REGRESSION folder. Read only.
        </p>
      </header>

      <div className="rd-toolbar">
        <label htmlFor="rd-release">Release</label>
        <select
          id="rd-release"
          value={milestone}
          onChange={(event) => setMilestone(event.target.value)}
        >
          {RELEASES.map((release) => (
            <option key={release} value={release}>{release}</option>
          ))}
        </select>
        {data && !loading && (
          <span className="rd-summary">
            {data.feat_count} feats
            {" · "}
            <span className="rd-swatch rd-black" /> {data.summary?.black || 0}
            {" · "}
            <span className="rd-swatch rd-red" /> {data.summary?.red || 0}
            {" · "}
            <span className="rd-swatch rd-yellow" /> {data.summary?.yellow || 0}
            {" · "}
            <span className="rd-swatch rd-green" /> {data.summary?.green || 0}
            {" · "}
            <span className="rd-swatch rd-not_run" /> {data.summary?.not_run || 0}
          </span>
        )}
      </div>

      <ul className="rd-legend">
        <li><span className="rd-swatch rd-black" /> Handover not started (0%), or only some tests match regression (shows the percent).</li>
        <li><span className="rd-swatch rd-red" /> Feat and regression tests match, all executed, pass rate 80% or below.</li>
        <li><span className="rd-swatch rd-yellow" /> Feat and regression tests match, all executed, pass rate above 80% with failures.</li>
        <li><span className="rd-swatch rd-green" /> Feat and regression tests match, all executed, all passed.</li>
        <li><span className="rd-swatch rd-not_run" /> Fully handed over, and at least one test has no pass or fail result.</li>
      </ul>

      {loading && <p className="rd-status">Loading feats from TCMS…</p>}
      {error && <p className="rd-error">{error}</p>}

      {!loading && !error && data && feats.length === 0 && (
        <p className="rd-status">No feats found under {data.root}.</p>
      )}

      {feats.length > 0 && (
        <table className="rd-table">
          <thead>
            <tr>
              <th>Feat</th>
              <th>Handed over</th>
              <th>Passed</th>
              <th>Failed</th>
              <th>Not run</th>
              <th>Pass %</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {feats.map((feat) => {
              const isOpen = openFeat === feat.name;
              return (
                <React.Fragment key={feat.name}>
                  <tr>
                    <td>
                      <button
                        type="button"
                        className="rd-feat-link"
                        onClick={() => setOpenFeat(isOpen ? "" : feat.name)}
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
                      <span className={`rd-status-box rd-${feat.color}`}>{statusLabel(feat)}</span>
                    </td>
                  </tr>
                  {isOpen && (
                    <tr className="rd-expand">
                      <td colSpan={7}>
                        <p>{feat.handed_over}/{feat.total} feat tests match the regression folder.</p>
                        <FeatTests
                          title="In the feat folder only"
                          tests={feat.tests.filter((test) => !test.in_regression)}
                        />
                        <FeatTests
                          title="In both feat and regression"
                          tests={feat.tests.filter((test) => test.in_regression)}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      )}

    </div>
  );
}
