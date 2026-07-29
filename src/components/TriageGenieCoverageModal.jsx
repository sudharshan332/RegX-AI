import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api from '../api';
import { buildJitaResultsUrl, buildViewInTriageGenieUrl } from '../utils/jitaTaskIds';
import {
  resolveRegressionScope,
  scopeToQueryParams,
  scopeToRequestPayload,
  shouldPostTriageScope,
} from '../utils/regressionScope';
import './TriageGenieCoverageModal.css';

function formatTime(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

async function fetchTriageGenieCoverage(scope, { reload = false } = {}) {
  // Coverage is fast (JITA + cached TG tickets); keep timeout modest
  const timeout = 180000;
  if (shouldPostTriageScope(scope)) {
    const body = scopeToRequestPayload(scope, { reload });
    return api.post('/mcp/regression/triage-genie-coverage', body, { timeout });
  }
  const params = scopeToQueryParams(scope, { reload });
  return api.get('/mcp/regression/triage-genie-coverage', { params, timeout });
}

export default function TriageGenieCoverageModal({ open, onClose }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [scope, setScope] = useState(null);

  // Instant links from dashboard Regression_Run_Tasks (no backend wait)
  const instantLinks = useMemo(() => {
    const ids = scope?.taskIds || [];
    return {
      jita_results_url: buildJitaResultsUrl(ids),
      triage_genie_url: buildViewInTriageGenieUrl(ids),
    };
  }, [scope]);

  const fetchCoverage = useCallback(async ({ reload = false } = {}) => {
    setLoading(true);
    setError(null);
    try {
      const resolved = await resolveRegressionScope();
      setScope(resolved);
      if (!resolved.tag && !(resolved.taskIds && resolved.taskIds.length)) {
        setError('No active regression tag or task IDs. Set a default tag in Configuration (Home).');
        setData(null);
        return;
      }
      const resp = await fetchTriageGenieCoverage(resolved, { reload });
      setData(resp.data);
    } catch (err) {
      const hint = err?.response?.data?.hint;
      const msg =
        err?.response?.data?.error ||
        err?.message ||
        'Failed to load Triage Genie coverage';
      const lower = String(msg).toLowerCase();
      if (err?.code === 'ECONNABORTED' || lower.includes('timeout')) {
        setError(
          `${msg}${hint ? ` — ${hint}` : ''} Coverage refresh uses JITA only (fast). For full TG ticket re-scan use Triage Accuracy → Reload data.`,
        );
      } else if (lower.includes('credential') || lower.includes('triage genie') || lower.includes('login')) {
        setError(`${msg} — check TRIAGE_GENIE_* credentials on the backend.`);
      } else {
        setError(hint ? `${msg} — ${hint}` : msg);
      }
      if (!reload) setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    // Resolve scope immediately so View-in-TG link is clickable before stats load
    resolveRegressionScope().then((resolved) => setScope(resolved)).catch(() => {});
    fetchCoverage({ reload: false });
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    const onLinkUpdated = () => {
      fetchCoverage({ reload: false });
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('regressionFullLinkUpdated', onLinkUpdated);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('regressionFullLinkUpdated', onLinkUpdated);
    };
  }, [open, fetchCoverage, onClose]);

  if (!open) return null;

  const summary = data?.summary || {};
  const byOwner = data?.by_owner || [];
  // Prefer instant View-in-TG / JITA links from Full link; fall back to API links
  const jitaUrl = instantLinks.jita_results_url || data?.links?.jita_results_url;
  const tgUrl =
    instantLinks.triage_genie_url ||
    data?.links?.triage_genie_view_url ||
    data?.links?.triage_genie_url;
  const activeTag = data?.tag || scope?.tag || '—';
  const taskCount = Array.isArray(scope?.taskIds)
    ? scope.taskIds.length
    : Array.isArray(data?.task_ids)
      ? data.task_ids.length
      : 0;

  return (
    <div
      className="tg-cov-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="tg-cov-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div className="tg-cov-panel">
        <header className="tg-cov-header">
          <div>
            <h2 id="tg-cov-title" className="tg-cov-title">
              Triage Genie coverage
            </h2>
            <p className="tg-cov-subtitle">
              Selected job: <strong>{activeTag || '—'}</strong>
              {taskCount ? ` · Regression_Run_Tasks (${taskCount})` : ''}
              {summary.pct_tg != null && data ? ` · ${summary.pct_tg}% via TG` : ''}
            </p>
          </div>
          <div className="tg-cov-header-actions">
            <button
              type="button"
              className="tg-cov-btn tg-cov-btn-primary"
              onClick={() => fetchCoverage({ reload: true })}
              disabled={loading}
              title="Re-fetch JITA failed/warning counts (fast). Does not re-scan every TG ticket."
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
            <button
              type="button"
              className="tg-cov-close"
              onClick={onClose}
              title="Close"
              aria-label="Close"
            >
              ×
            </button>
          </div>
        </header>

        <div className="tg-cov-body">
          {/* Links available immediately from Regression_Run_Tasks — no wait for stats */}
          <div className="tg-cov-actions" style={{ marginBottom: 12 }}>
            {jitaUrl && (
              <a
                className="tg-cov-link"
                href={jitaUrl}
                target="_blank"
                rel="noopener noreferrer"
                title={jitaUrl}
              >
                Open JITA (Regression_Run_Tasks)
              </a>
            )}
            {tgUrl && (
              <a
                className="tg-cov-link"
                href={tgUrl}
                target="_blank"
                rel="noopener noreferrer"
                title={tgUrl}
              >
                Open Triage Genie (View in TG)
              </a>
            )}
            {!tgUrl && (
              <span className="tg-cov-status-hint">
                No Regression_Run_Tasks IDs yet — select a tag / wait for the Full link.
              </span>
            )}
          </div>

          {error && <div className="tg-cov-error">{error}</div>}

          {loading && !data && (
            <div className="tg-cov-status">
              Loading coverage stats from JITA…
              <br />
              <span className="tg-cov-status-hint">
                Open Triage Genie link above is ready now (same as JITA → View in Triage Genie).
                Stats use cache when available; Refresh reloads JITA only (no slow TG re-scan).
              </span>
            </div>
          )}

          {data && (
            <>
              <div className="tg-cov-tiles">
                <div className="tg-cov-tile">
                  <span className="tg-cov-tile-label">Total failed/warn</span>
                  <span className="tg-cov-tile-value">{summary.total ?? 0}</span>
                </div>
                <div className="tg-cov-tile ok">
                  <span className="tg-cov-tile-label">Via Triage Genie</span>
                  <span className="tg-cov-tile-value">{summary.via_triage_genie ?? 0}</span>
                </div>
                <div className={`tg-cov-tile ${(summary.remaining_need_tg || 0) > 0 ? 'bad' : 'ok'}`}>
                  <span className="tg-cov-tile-label">Remaining (need TG)</span>
                  <span className="tg-cov-tile-value">{summary.remaining_need_tg ?? 0}</span>
                </div>
                <div className={`tg-cov-tile ${(summary.manual_only || 0) > 0 ? 'warn' : ''}`}>
                  <span className="tg-cov-tile-label">Manual-only (JIRA, no TG)</span>
                  <span className="tg-cov-tile-value">{summary.manual_only ?? 0}</span>
                </div>
              </div>

              <div className="tg-cov-table-wrap">
                <table className="tg-cov-table">
                  <thead>
                    <tr>
                      <th>Owner</th>
                      <th className="num">Total</th>
                      <th className="num">Via TG</th>
                      <th className="num">JIRA</th>
                      <th className="num">Remaining</th>
                      <th className="num">Manual-only</th>
                      <th className="num">% TG</th>
                    </tr>
                  </thead>
                  <tbody>
                    {byOwner.length === 0 ? (
                      <tr>
                        <td colSpan={7}>No failed/warning tests for this scope.</td>
                      </tr>
                    ) : (
                      byOwner.map((row) => (
                        <tr
                          key={row.owner}
                          className={row.remaining_need_tg > 0 ? 'needs-work' : undefined}
                        >
                          <td>{row.owner}</td>
                          <td className="num">{row.total}</td>
                          <td className="num">{row.via_triage_genie}</td>
                          <td className="num">{row.jira_tagged}</td>
                          <td className="num">{row.remaining_need_tg}</td>
                          <td className="num">{row.manual_only}</td>
                          <td className="num">{row.pct_tg}%</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              <p className="tg-cov-meta">
                Generated {formatTime(data.generated_time)}
                {taskCount ? ` · Full regression: ${taskCount} JITA task(s)` : ''}
                {' · Via-TG counts reuse cached TG tickets; full re-scan: Triage Accuracy → Reload data'}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
