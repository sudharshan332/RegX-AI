import React, { useState } from 'react';
import axios from 'axios';
import api from '../api';
import { API_BASE_URL } from '../config';
import './DynamicJobProfile.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/dynamic-jp`;

// Tool went live in April 2026 — no entities exist before this date.
const TOOL_START_DATE = '2026-04-01';
const todayLocalDate = () => {
  const d = new Date();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${mm}-${dd}`;
};

export default function ManageJobProfile({ embedded = false }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedDate, setSelectedDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  const [jobProfiles, setJobProfiles] = useState([]);
  const [testSets, setTestSets] = useState([]);
  const [totals, setTotals] = useState({ job_profiles: 0, test_sets: 0 });
  const [searched, setSearched] = useState(false);

  const [selectedJPs, setSelectedJPs] = useState(new Set());
  const [selectedTSs, setSelectedTSs] = useState(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deleteResults, setDeleteResults] = useState(null);

  const getErrorMessage = (err) =>
    err?.response?.data?.error || err?.message || 'Unknown error';

  const handleSearch = async () => {
    const q = searchQuery.trim();
    if (q.length < 2 && !selectedDate) {
      setErrorMsg('Enter at least 2 characters or pick a date to search');
      return;
    }
    setLoading(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    setDeleteResults(null);
    setSelectedJPs(new Set());
    setSelectedTSs(new Set());
    try {
      // No small limit — return everything that matches (JITA honors a large
      // limit and reports the true total), so the list mirrors the JITA UI.
      const resp = await axios.post(`${API_BASE}/search`, {
        query: q,
        date: selectedDate || null,
      });
      const jps = resp.data?.job_profiles || [];
      const tss = resp.data?.test_sets || [];
      setJobProfiles(jps);
      setTestSets(tss);
      setTotals(resp.data?.totals || { job_profiles: jps.length, test_sets: tss.length });
      setSearched(true);
      const warnings = Array.isArray(resp.data?.warnings) ? resp.data.warnings : [];
      if (!jps.length && !tss.length) {
        const where = [
          q.length >= 2 ? `matching "${q}"` : '',
          selectedDate ? `created on ${selectedDate}` : '',
        ].filter(Boolean).join(' and ');
        setErrorMsg(`No Job Profiles or Test Sets found ${where}`);
      } else if (warnings.length) {
        setErrorMsg(warnings.join(' '));
      }
    } catch (err) {
      setErrorMsg(`Search failed: ${getErrorMessage(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const toggleJP = (id) => {
    setSelectedJPs((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleTS = (id) => {
    setSelectedTSs((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const handleDelete = async () => {
    const jpIds = [...selectedJPs];
    const tsIds = [...selectedTSs];
    if (jpIds.length === 0 && tsIds.length === 0) {
      setErrorMsg('Please select at least one Job Profile or Test Set to delete');
      return;
    }

    const count = jpIds.length + tsIds.length;
    const confirmMsg = `Are you sure you want to delete ${count} item(s)?\n\n` +
      (jpIds.length ? `Job Profiles: ${jpIds.length}\n` : '') +
      (tsIds.length ? `Test Sets: ${tsIds.length}\n` : '') +
      '\nThis action cannot be undone.';

    if (!window.confirm(confirmMsg)) return;

    setDeleting(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    setDeleteResults(null);
    try {
      // Use the shared `api` instance so the JWT is attached — the backend deletes
      // with the user's own JITA credentials and enforces delete permissions.
      const resp = await api.post(`/mcp/regression/dynamic-jp/delete`, {
        jp_ids: jpIds,
        ts_ids: tsIds,
      });
      setDeleteResults(resp.data?.results || {});

      const jpResults = resp.data?.results?.job_profiles || [];
      const tsResults = resp.data?.results?.test_sets || [];
      const allResults = [...jpResults, ...tsResults];
      const okCount = allResults.filter((r) => r.success).length;
      const unauthorizedCount = allResults.filter((r) => r.unauthorized).length;
      const otherFailCount = allResults.filter((r) => !r.success && !r.unauthorized).length;

      if (okCount > 0) setSuccessMsg(`Successfully deleted ${okCount} item(s).`);
      else setSuccessMsg(null);

      if (unauthorizedCount > 0 || otherFailCount > 0) {
        const parts = [];
        if (unauthorizedCount > 0) parts.push(`${unauthorizedCount} blocked — you are not the owner`);
        if (otherFailCount > 0) parts.push(`${otherFailCount} failed`);
        setErrorMsg(
          `${okCount} deleted, ${parts.join(', ')}. ` +
          `The item(s) you don't own were not deleted. See details below.`
        );
      } else {
        setErrorMsg(null);
      }

      // Remove successfully deleted items from lists
      const deletedJPIds = new Set(
        (resp.data?.results?.job_profiles || []).filter((r) => r.success).map((r) => r._id)
      );
      const deletedTSIds = new Set(
        (resp.data?.results?.test_sets || []).filter((r) => r.success).map((r) => r._id)
      );
      setJobProfiles((prev) => prev.filter((jp) => !deletedJPIds.has(jp._id)));
      setTestSets((prev) => prev.filter((ts) => !deletedTSIds.has(ts._id)));
      setSelectedJPs(new Set());
      setSelectedTSs(new Set());
    } catch (err) {
      setErrorMsg(`Delete failed: ${getErrorMessage(err)}`);
    } finally {
      setDeleting(false);
    }
  };

  const totalSelected = selectedJPs.size + selectedTSs.size;

  const headerBlock = !embedded ? (
    <div className="djp-header">
      <h1>Manage Job Profiles &amp; Test Sets</h1>
    </div>
  ) : null;

  const inner = (
    <>
      {headerBlock}

      {/* Search bar */}
      <div className="djp-section">
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div style={{ flex: '1 1 320px', minWidth: 240 }}>
            <label className="djp-label">Search by name</label>
            <input
              className="djp-input"
              style={{ width: '100%' }}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
              placeholder="Name (partial match). Combine terms with | e.g. CDP | 7.5.1"
              disabled={loading}
            />
          </div>
          <div style={{ flex: '0 0 auto' }}>
            <label className="djp-label">Created on (optional)</label>
            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input
                className="djp-input"
                type="date"
                value={selectedDate}
                min={TOOL_START_DATE}
                max={todayLocalDate()}
                onChange={(e) => setSelectedDate(e.target.value)}
                disabled={loading}
              />
              {selectedDate && (
                <button
                  type="button"
                  className="djp-btn"
                  style={{ padding: '6px 10px' }}
                  onClick={() => setSelectedDate('')}
                  disabled={loading}
                  title="Clear date filter"
                >
                  Clear
                </button>
              )}
            </div>
          </div>
          <button
            className="djp-btn djp-btn-primary"
            onClick={handleSearch}
            disabled={loading || (searchQuery.trim().length < 2 && !selectedDate)}
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: 12, color: '#64748b' }}>
          Pick a date to list only items this tool created that day. The name search
          is optional and can be combined with the date. Separate multiple terms with
          <code style={{ padding: '0 4px' }}>|</code> (e.g. <code>CDP | 7.5.1</code>) to
          match names containing <strong>all</strong> of them (narrows results, like JITA).
        </p>
      </div>

      {/* Messages */}
      {errorMsg && <div className="djp-error-box">{errorMsg}</div>}
      {successMsg && (
        <div className="djp-result-box" style={{ borderLeftColor: '#22c55e' }}>
          <p style={{ margin: 0, fontWeight: 600, color: '#16a34a' }}>{successMsg}</p>
        </div>
      )}

      {/* Results */}
      {searched && (
        <div className="djp-two-col" style={{ marginTop: 20 }}>
          {/* Job Profiles column */}
          <div className="djp-section">
            <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>
              Job Profiles ({totals.job_profiles > jobProfiles.length
                ? `${jobProfiles.length} of ${totals.job_profiles}`
                : jobProfiles.length})
            </h3>
            {jobProfiles.length === 0 ? (
              <p style={{ color: '#64748b', fontSize: 13 }}>No Job Profiles found</p>
            ) : (
              <div className="djp-name-list-selectable" style={{ maxHeight: 400 }}>
                {jobProfiles.map((jp) => (
                  <div
                    key={jp._id}
                    className={`djp-name-item ${selectedJPs.has(jp._id) ? 'selected' : ''}`}
                    onClick={() => toggleJP(jp._id)}
                  >
                    <span className="djp-checkbox-dot">
                      {selectedJPs.has(jp._id) ? '✓' : ''}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, wordBreak: 'break-all' }}>
                        {jp.name}
                      </div>
                      {jp.description && (
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                          {jp.description.slice(0, 80)}
                        </div>
                      )}
                      <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>
                        ID: {jp._id}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Test Sets column */}
          <div className="djp-section">
            <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>
              Test Sets ({totals.test_sets > testSets.length
                ? `${testSets.length} of ${totals.test_sets}`
                : testSets.length})
            </h3>
            {testSets.length === 0 ? (
              <p style={{ color: '#64748b', fontSize: 13 }}>No Test Sets found</p>
            ) : (
              <div className="djp-name-list-selectable" style={{ maxHeight: 400 }}>
                {testSets.map((ts) => (
                  <div
                    key={ts._id}
                    className={`djp-name-item ${selectedTSs.has(ts._id) ? 'selected' : ''}`}
                    onClick={() => toggleTS(ts._id)}
                  >
                    <span className="djp-checkbox-dot">
                      {selectedTSs.has(ts._id) ? '✓' : ''}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, wordBreak: 'break-all' }}>
                        {ts.name}
                      </div>
                      {ts.description && (
                        <div style={{ fontSize: 11, color: '#64748b', marginTop: 2 }}>
                          {ts.description.slice(0, 80)}
                        </div>
                      )}
                      <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>
                        ID: {ts._id}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* Delete button */}
      {searched && (jobProfiles.length > 0 || testSets.length > 0) && (
        <div style={{ marginTop: 20, display: 'flex', alignItems: 'center', gap: 16 }}>
          <button
            className="djp-btn djp-btn-danger"
            onClick={handleDelete}
            disabled={deleting || totalSelected === 0}
          >
            {deleting
              ? 'Deleting...'
              : totalSelected > 0
              ? `Delete ${totalSelected} selected item(s)`
              : 'Select items to delete'}
          </button>
          {totalSelected > 0 && (
            <span style={{ fontSize: 13, color: '#64748b' }}>
              {selectedJPs.size > 0 && `${selectedJPs.size} JP(s)`}
              {selectedJPs.size > 0 && selectedTSs.size > 0 && ', '}
              {selectedTSs.size > 0 && `${selectedTSs.size} TS(s)`}
            </span>
          )}
        </div>
      )}

      {/* Delete results detail */}
      {deleteResults && (
        <div className="djp-section" style={{ marginTop: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700 }}>Delete Results</h3>
          {(deleteResults.job_profiles || []).map((r) => (
            <div
              key={r._id}
              style={{
                padding: '8px 12px',
                marginBottom: 6,
                borderRadius: 6,
                fontSize: 13,
                background: r.success ? '#f0fdf4' : '#fef2f2',
                color: r.success ? '#16a34a' : '#dc2626',
                border: `1px solid ${r.success ? '#bbf7d0' : '#fecaca'}`,
              }}
            >
              <strong>JP</strong> {r._id}: {r.message}
            </div>
          ))}
          {(deleteResults.test_sets || []).map((r) => (
            <div
              key={r._id}
              style={{
                padding: '8px 12px',
                marginBottom: 6,
                borderRadius: 6,
                fontSize: 13,
                background: r.success ? '#f0fdf4' : '#fef2f2',
                color: r.success ? '#16a34a' : '#dc2626',
                border: `1px solid ${r.success ? '#bbf7d0' : '#fecaca'}`,
              }}
            >
              <strong>TS</strong> {r._id}: {r.message}
            </div>
          ))}
        </div>
      )}
    </>
  );

  if (embedded) {
    return <div className="djp-manage-embedded">{inner}</div>;
  }

  return (
    <div className="djp-container">
      {inner}
    </div>
  );
}
