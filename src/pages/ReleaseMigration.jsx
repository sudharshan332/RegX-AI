import React, { useMemo, useState } from 'react';
import api from '../api';
import { API_BASE_URL, jitaJobProfileWebUrl } from '../config';
import './DynamicJobProfile.css';
import './ReleaseMigration.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/dynamic-jp`;

/** Number of JP clones triggered in parallel. Kept small to avoid JITA rate-limiting. */
const CONCURRENCY = 3;

/** Local calendar YYYYMMDD — matches backend `dyn_name_date` for generated names. */
const formatLocalYyyymmdd = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}${m}${day}`;
};

/** Replace every literal occurrence of `find` with `replace` (no regex interpretation). */
const replaceAllLiteral = (str, find, replace) => {
  if (!find) return str;
  return String(str).split(find).join(replace);
};

/**
 * Matches a dotted release-version token, e.g. "7.7", "7.6.0.6" or "7.6.X".
 * Each segment after the first is digits or a single-letter wildcard (X/x).
 */
const VERSION_TOKEN_RE = /\d+(?:\.(?:\d+|[xX]))+/;

/**
 * Resolve the old release version for a JP. Uses the explicit form value when given,
 * otherwise auto-detects the version token from the JP name (client only has the name;
 * the backend additionally falls back to the JP's existing NOS branch when needed).
 */
export const detectOldVersion = (jp, explicitOldVersion) => {
  if (explicitOldVersion) return explicitOldVersion;
  const m = String(jp?.name || '').match(VERSION_TOKEN_RE);
  return m ? m[0] : '';
};

/**
 * Conditional version rewrite used for the JP name/description preview.
 * If `oldVersion` is present in the text, every occurrence is replaced with
 * `newVersion`; otherwise the text is returned unchanged (spec: "leave as is").
 */
export const migrateVersionString = (text, oldVersion, newVersion) => {
  const s = text == null ? '' : String(text);
  if (!oldVersion || oldVersion === newVersion) return s;
  return s.includes(oldVersion) ? replaceAllLiteral(s, oldVersion, newVersion) : s;
};

/**
 * Build the `/dynamic-jp/create` clone payload for one source JP.
 *
 * Name & description keep the source policy name and only rewrite the release
 * version (conditional replace; unchanged when the old version isn't present).
 * The migrated name is sent as `custom_jp_name` so the clone always keeps the
 * policy name (never the auto-generated fallback). Branches & toggles are absolute
 * overwrites; the clone reuses the existing create/clone engine with
 * `override_source_branches` + `preserve_source_config`.
 *
 * @param {{_id:string, name:string, description?:string}} jp source job profile
 * @param {object} form migration form values
 * @returns {object} POST body for /dynamic-jp/create
 */
export const buildMigrationPayload = (jp, form) => {
  const oldVersion = detectOldVersion(jp, form.oldVersion);
  const newName = migrateVersionString(jp.name, oldVersion, form.newVersion);
  const newDescription = migrateVersionString(jp.description || '', oldVersion, form.newVersion);
  return {
    create_fresh: false,
    source_jp_id: jp._id,
    // Keep the source policy name; only the version segment changes.
    custom_jp_name: newName,
    custom_jp_description: newDescription,
    // Passed for backend logging / as a fallback rewrite source (old is optional;
    // auto-detected server-side from the JP name/NOS branch when blank).
    version_from: oldVersion,
    version_to: form.newVersion,
    // Branch & toggle replacements (absolute overwrite).
    nos_branch: form.nosBranch,
    pc_branch: form.pcBranch,
    nutest_branch: form.testOptionBranch,
    override_source_branches: true,
    preserve_source_config: true,
    // Sync to TCMS is always enabled for release migration.
    sync_to_tcms: true,
    tcms_sync_branch: form.tcmsSyncBranch,
    // Reuse the source JP's existing test set unchanged (no new test set created).
    testcase_names: [],
    reuse_source_ts: true,
    dyn_name_date: formatLocalYyyymmdd(),
  };
};

const getErrorMessage = (error) => {
  if (error?.response?.data?.error) return error.response.data.error;
  if (error?.response?.status === 503) return 'Backend is unreachable. Is the Flask server running?';
  if (error?.response?.status === 504) return 'Request timed out. JITA may be slow or unreachable.';
  if (error?.code === 'ERR_NETWORK') return 'Network error. Check the connection and that the backend is running.';
  if (error?.code === 'ECONNABORTED') return 'Request timed out.';
  return error?.message || 'An unknown error occurred';
};

export default function ReleaseMigration({ embedded = false }) {
  // ── JP search ──
  const [searchQuery, setSearchQuery] = useState('');
  const [useRegex, setUseRegex] = useState(true);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [searched, setSearched] = useState(false);
  const [jobProfiles, setJobProfiles] = useState([]);
  const [selectedIds, setSelectedIds] = useState(() => new Set());

  // ── Migration form ──
  const [oldVersion, setOldVersion] = useState('');
  const [newVersion, setNewVersion] = useState('');
  const [tcmsSyncBranch, setTcmsSyncBranch] = useState('');
  const [nosBranch, setNosBranch] = useState('');
  const [pcBranch, setPcBranch] = useState('');
  const [testOptionBranch, setTestOptionBranch] = useState('');

  // ── Migration run ──
  const [migrating, setMigrating] = useState(false);
  const [progress, setProgress] = useState({ done: 0, total: 0 });
  const [results, setResults] = useState([]);
  const [formError, setFormError] = useState(null);

  const form = {
    oldVersion: oldVersion.trim(),
    newVersion: newVersion.trim(),
    tcmsSyncBranch: tcmsSyncBranch.trim(),
    nosBranch: nosBranch.trim(),
    pcBranch: pcBranch.trim(),
    testOptionBranch: testOptionBranch.trim(),
  };

  const allSelected = jobProfiles.length > 0 && selectedIds.size === jobProfiles.length;
  const selectedProfiles = useMemo(
    () => jobProfiles.filter((jp) => selectedIds.has(jp._id)),
    [jobProfiles, selectedIds]
  );

  const successCount = results.filter((r) => r.status === 'success').length;
  const failedCount = results.filter((r) => r.status === 'failed').length;
  const progressPct = progress.total > 0 ? Math.round((progress.done / progress.total) * 100) : 0;

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (q.length < 2) {
      setSearchError('Enter at least 2 characters to search for job profiles.');
      return;
    }
    setSearching(true);
    setSearchError(null);
    setResults([]);
    setSelectedIds(new Set());
    try {
      const resp = await api.post(`${API_BASE}/search`, {
        query: q,
        regex: useRegex,
        // Migration only targets job profiles; skipping the test-set scan avoids a
        // second slow JITA round-trip. No small limit — return every match (JITA
        // honors a large limit and reports the true total), mirroring the JITA UI.
        include_test_sets: false,
      });
      const jps = Array.isArray(resp.data?.job_profiles) ? resp.data.job_profiles : [];
      const warnings = Array.isArray(resp.data?.warnings) ? resp.data.warnings : [];
      setJobProfiles(jps);
      setSearched(true);
      if (jps.length === 0) {
        setSearchError(
          warnings.length
            ? warnings.join(' ')
            : `No job profiles matched ${useRegex ? 'regex' : ''} "${q}".`
        );
      } else if (warnings.length) {
        setSearchError(warnings.join(' '));
      }
    } catch (err) {
      setJobProfiles([]);
      setSearched(true);
      setSearchError(`Search failed: ${getErrorMessage(err)}`);
    } finally {
      setSearching(false);
    }
  };

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelectedIds((prev) =>
      prev.size === jobProfiles.length ? new Set() : new Set(jobProfiles.map((jp) => jp._id))
    );
  };

  /** Returns an error message string if the form/selection is invalid, otherwise null. */
  const validate = () => {
    if (selectedProfiles.length === 0) return 'Select at least one job profile to migrate.';
    if (!form.newVersion) return 'New Release Version is required.';
    if (form.oldVersion && form.oldVersion === form.newVersion) return 'Old and New Release Versions must differ.';
    if (!form.nosBranch) return 'NOS Cluster Branch is required.';
    if (!form.pcBranch) return 'Prism Central Branch is required.';
    if (!form.testOptionBranch) return 'Test Option Branch is required.';
    if (!form.tcmsSyncBranch) return 'TCMS Sync Branch is required.';
    return null;
  };

  const updateResult = (id, patch) =>
    setResults((prev) => prev.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  /**
   * Iterate over every selected JP, clone each one with the transformed payload,
   * and track per-JP success/failure. Runs a small pool of `CONCURRENCY` workers
   * (controlled parallel batches) and never aborts the whole run on a single failure.
   */
  const runMigration = async () => {
    const err = validate();
    if (err) {
      setFormError(err);
      return;
    }
    setFormError(null);

    const queue = [...selectedProfiles];
    setResults(
      queue.map((jp) => ({
        id: jp._id,
        sourceName: jp.name,
        newName: migrateVersionString(jp.name, detectOldVersion(jp, form.oldVersion), form.newVersion),
        status: 'pending',
        message: '',
        jpUrl: '',
      }))
    );
    setMigrating(true);
    setProgress({ done: 0, total: queue.length });

    let cursor = 0;
    let done = 0;

    const worker = async () => {
      // Pull the next JP off the shared queue until it is exhausted.
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const i = cursor;
        cursor += 1;
        if (i >= queue.length) break;
        const jp = queue[i];
        updateResult(jp._id, { status: 'running' });
        try {
          const payload = buildMigrationPayload(jp, form);
          const resp = await api.post(`${API_BASE}/create`, payload);
          if (resp.data?.success) {
            const created = resp.data.job_profile || {};
            const jpUrl = created.ui_url || jitaJobProfileWebUrl(created._id, created.name);
            updateResult(jp._id, {
              status: 'success',
              newName: created.name || migrateVersionString(jp.name, detectOldVersion(jp, form.oldVersion), form.newVersion),
              message: resp.data.message || 'Cloned successfully.',
              jpUrl: jpUrl || '',
              warnings: Array.isArray(resp.data.warnings) ? resp.data.warnings : [],
            });
          } else {
            updateResult(jp._id, {
              status: 'failed',
              message: resp.data?.error || 'Clone returned without a success flag.',
            });
          }
        } catch (e) {
          // Log the failure in the UI but keep the loop going for the rest.
          updateResult(jp._id, { status: 'failed', message: `Failed on JP: ${jp.name} — ${getErrorMessage(e)}` });
        } finally {
          done += 1;
          setProgress({ done, total: queue.length });
        }
      }
    };

    const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, () => worker());
    await Promise.all(workers);
    setMigrating(false);
  };

  const statusLabel = { pending: 'Queued', running: 'Cloning…', success: 'Done', failed: 'Failed' };

  const content = (
    <>
      {!embedded && (
        <div className="djp-header">
          <h1>Release Migration</h1>
        </div>
      )}

      {/* ── Step 1: find the job profiles ── */}
      <div className="djp-section">
        <div className="rm-step-head">
          <span className="rm-step-num">1</span>
          <div className="rm-step-title">Select job profiles</div>
        </div>
        <div className="djp-search-row">
          <div className="djp-form-group" style={{ flex: 1, minWidth: 260 }}>
            <label>JP name search {useRegex ? '(regex)' : '(contains)'}</label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  if (!searching) handleSearch();
                }
              }}
              placeholder={useRegex ? 'e.g. CDP_Regression_FullReg_7\\.6\\.0\\.6_.*' : 'e.g. CDP_Regression_FullReg_7.6.0.6'}
            />
          </div>
          <div className="djp-toggle-group">
            <label className="djp-toggle-label">Regex</label>
            <div
              className={`djp-toggle ${useRegex ? 'active' : ''}`}
              onClick={() => setUseRegex((v) => !v)}
              role="switch"
              aria-checked={useRegex}
              title="Treat the search text as a regular expression"
            >
              <div className="djp-toggle-knob" />
            </div>
          </div>
          <div className="djp-search-action">
            <button className="djp-btn djp-btn-primary" onClick={handleSearch} disabled={searching}>
              {searching ? 'Searching…' : 'Search JPs'}
            </button>
          </div>
        </div>

        {searchError && <div className="djp-inline-error"><span>{searchError}</span><button onClick={() => setSearchError(null)} title="Dismiss">&times;</button></div>}

        {searched && jobProfiles.length > 0 && (
          <>
            <div className="rm-results-toolbar">
              <button className="djp-btn djp-btn-sm" onClick={toggleSelectAll}>
                {allSelected ? 'Deselect all' : 'Select all'}
              </button>
              <span className="rm-results-count">
                {selectedIds.size} of {jobProfiles.length} selected
              </span>
            </div>
            <div className="djp-name-list-selectable rm-jp-list">
              {jobProfiles.map((jp) => {
                const selected = selectedIds.has(jp._id);
                const preview = migrateVersionString(jp.name, detectOldVersion(jp, form.oldVersion), form.newVersion);
                const changed = preview !== jp.name;
                return (
                  <div
                    key={jp._id}
                    className={`djp-name-item ${selected ? 'selected' : ''}`}
                    onClick={() => toggleSelect(jp._id)}
                  >
                    <span className="djp-checkbox-dot">{selected ? '✓' : ''}</span>
                    <div className="rm-jp-info">
                      <div className="rm-jp-name">{jp.name}</div>
                      {changed && (
                        <div className="rm-jp-preview">
                          <span className="rm-arrow">→</span> {preview}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

      {/* ── Step 2: migration parameters ── */}
      <div className="djp-section">
        <div className="rm-step-head">
          <span className="rm-step-num">2</span>
          <div className="rm-step-title">Configure target release</div>
        </div>

        <div className="rm-subsection">
          <div className="rm-subsection-title">Version</div>
          <div className="rm-form-grid">
            <div className="djp-form-group">
              <label>Old version <span className="rm-optional">optional</span></label>
              <input
                type="text"
                value={oldVersion}
                onChange={(e) => setOldVersion(e.target.value)}
                placeholder="e.g. 7.6.0.6"
              />
            </div>
            <div className="djp-form-group">
              <label>New version</label>
              <input
                type="text"
                value={newVersion}
                onChange={(e) => setNewVersion(e.target.value)}
                placeholder="e.g. 7.8.5"
              />
            </div>
          </div>
        </div>

        <div className="rm-subsection">
          <div className="rm-subsection-title">Branches</div>
          <div className="rm-form-grid">
            <div className="djp-form-group">
              <label>NOS cluster branch</label>
              <input
                type="text"
                value={nosBranch}
                onChange={(e) => setNosBranch(e.target.value)}
                placeholder="e.g. ganges7.7-stable"
              />
            </div>
            <div className="djp-form-group">
              <label>Prism Central branch</label>
              <input
                type="text"
                value={pcBranch}
                onChange={(e) => setPcBranch(e.target.value)}
                placeholder="e.g. ganges7.7-stable-pc"
              />
            </div>
            <div className="djp-form-group">
              <label>Test option branch</label>
              <input
                type="text"
                value={testOptionBranch}
                onChange={(e) => setTestOptionBranch(e.target.value)}
                placeholder="e.g. ganges7.7-stable"
              />
            </div>
            <div className="djp-form-group">
              <label>TCMS sync branch</label>
              <input
                type="text"
                value={tcmsSyncBranch}
                onChange={(e) => setTcmsSyncBranch(e.target.value)}
                placeholder="e.g. ganges7.7-stable"
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Step 3: run ── */}
      <div className="djp-section">
        <div className="rm-step-head">
          <span className="rm-step-num">3</span>
          <div className="rm-step-title">Run</div>
        </div>

        {(migrating || progress.total > 0) && (
          <div className="rm-progress-wrap">
            <div className="rm-progress-head">
              <span>
                {migrating ? 'Cloning…' : 'Completed'} {progress.done}/{progress.total}
              </span>
              <span className="rm-progress-summary">
                <span className="rm-chip rm-chip-success">{successCount} ok</span>
                <span className="rm-chip rm-chip-failed">{failedCount} failed</span>
              </span>
            </div>
            <div className="rm-progress-track">
              <div className="rm-progress-bar" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        <div className="djp-form-actions">
          <button
            className="djp-btn djp-btn-success djp-btn-lg"
            onClick={runMigration}
            disabled={migrating || selectedProfiles.length === 0}
          >
            {migrating
              ? `Cloning ${progress.done}/${progress.total}…`
              : `Start Migration${selectedProfiles.length ? ` (${selectedProfiles.length})` : ''}`}
          </button>
        </div>

        {formError && (
          <div className="djp-inline-error">
            <span>{formError}</span>
            <button onClick={() => setFormError(null)} title="Dismiss">&times;</button>
          </div>
        )}

        {results.length > 0 && (
          <div className="rm-results-list">
            {results.map((r) => (
              <div key={r.id} className={`rm-result-item rm-result-${r.status}`}>
                <span className={`rm-status-chip rm-status-${r.status}`}>
                  {statusLabel[r.status] || r.status}
                </span>
                <div className="rm-result-body">
                  <div className="rm-result-name">
                    {r.jpUrl && r.status === 'success' ? (
                      <a href={r.jpUrl} target="_blank" rel="noreferrer">{r.newName}</a>
                    ) : (
                      <span>{r.newName}</span>
                    )}
                    {r.newName !== r.sourceName && (
                      <span className="rm-result-source"> (from {r.sourceName})</span>
                    )}
                  </div>
                  {r.message && r.status === 'failed' && (
                    <div className="rm-result-msg rm-result-msg-error">{r.message}</div>
                  )}
                  {r.warnings && r.warnings.length > 0 && (
                    <div className="rm-result-msg rm-result-msg-warn">
                      {r.warnings.join(' · ')}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );

  if (embedded) {
    return <div className="rm-embedded">{content}</div>;
  }

  return <div className="djp-container rm-container">{content}</div>;
}
