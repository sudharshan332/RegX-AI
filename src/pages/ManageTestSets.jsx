import React, { useMemo, useRef, useState } from 'react';
import api from '../api';
import { API_BASE_URL } from '../config';
import { buildTsUpdates, extractCanonicalArgs } from '../utils/manageTestSetArgs';
import './DynamicJobProfile.css';

const SEARCH_API = `${API_BASE_URL}/mcp/regression/dynamic-jp/search`;
const FETCH_TESTSET_API = `${API_BASE_URL}/mcp/regression/dynamic-jp/fetch-testset`;
const UPDATE_API = `${API_BASE_URL}/mcp/regression/dynamic-jp/update`;

const newArgRow = () => ({ key: '', value: '', overwrite_existing: false });

export default function ManageTestSets({ embedded = false }) {
  const [searchQuery, setSearchQuery] = useState('');
  const [loadingSearch, setLoadingSearch] = useState(false);
  const [searchResults, setSearchResults] = useState([]);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selectedTsMap, setSelectedTsMap] = useState({});
  const [searched, setSearched] = useState(false);

  const [inspecting, setInspecting] = useState(false);
  const [commonFrameworkArgs, setCommonFrameworkArgs] = useState([]);
  const [commonTestArgs, setCommonTestArgs] = useState([]);
  const [selectedArgEdits, setSelectedArgEdits] = useState({});

  const [newFrameworkArgs, setNewFrameworkArgs] = useState([newArgRow()]);
  const [newTestArgs, setNewTestArgs] = useState([newArgRow()]);

  const [applying, setApplying] = useState(false);
  const [applyResult, setApplyResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const inspectReqId = useRef(0);

  const selectedCount = selectedIds.size;
  const allSelected = useMemo(
    () => searchResults.length > 0 && selectedIds.size === searchResults.length,
    [searchResults, selectedIds]
  );
  const commonLoaded = commonFrameworkArgs.length > 0 || commonTestArgs.length > 0;

  const getErrorMessage = (err) => err?.response?.data?.error || err?.message || 'Unknown error';
  // `|` is a term separator (multiple names), not regex alternation.
  const hasRegexSyntax = (q) => /[.*+?^${}()[\]\\]/.test(q);
  const splitSearchTerms = (q) => q.split('|').map((t) => t.trim()).filter(Boolean);

  const hasNonEmptyRawArgs = (row, kind) => {
    const items = kind === 'framework'
      ? [row.agave_options, row.framework_args, row.frameworkArgs]
      : [row.args_map, row.test_args, row.testArgs];
    return items.some((v) => {
      if (v === null || v === undefined) return false;
      if (typeof v === 'string') return v.trim().length > 0 && v.trim() !== '{}';
      if (typeof v === 'object') return Object.keys(v || {}).length > 0;
      return false;
    });
  };

  const stringifyArgValue = (value) => (
    typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
  );

  const extractUnionRows = (argMaps) => {
    if (!argMaps.length) return [];
    const allKeys = new Set();
    argMaps.forEach((m) => {
      Object.keys(m || {}).forEach((k) => allKeys.add(k));
    });
    return [...allKeys].sort().map((key) => {
      const values = argMaps
        .filter((m) => Object.prototype.hasOwnProperty.call(m || {}, key))
        .map((m) => m[key]);
      const sig = new Set(values.map(stringifyArgValue));
      const multiple = sig.size > 1;
      return {
        key,
        value: multiple ? null : values[0],
        multiple_values: multiple,
      };
    });
  };

  const clearComputed = () => {
    setCommonFrameworkArgs([]);
    setCommonTestArgs([]);
    setSelectedArgEdits({});
    setApplyResult(null);
    setSuccessMsg(null);
    setNewFrameworkArgs([newArgRow()]);
    setNewTestArgs([newArgRow()]);
  };

  const handleSearch = async () => {
    const q = searchQuery.trim();
    const terms = splitSearchTerms(q);
    if (!terms.length || terms.some((t) => t.length < 2)) {
      setErrorMsg(
        terms.length > 1
          ? 'Each pipe-separated name must be at least 2 characters'
          : 'Enter at least 2 characters'
      );
      return;
    }
    setLoadingSearch(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    clearComputed();
    try {
      const regexMode = terms.some((t) => hasRegexSyntax(t));
      const searchOne = (term, limit) =>
        api.post(
          SEARCH_API,
          {
            query: term,
            regex: hasRegexSyntax(term),
            include_job_profiles: false,
            include_test_sets: true,
            limit,
          },
          { timeout: 90000 }
        );

      const responses = await Promise.all(
        terms.map(async (term) => {
          const limit = terms.length > 1 ? 20 : 25;
          const resp = await searchOne(term, limit);
          const data = resp.data || {};
          const got = data.test_sets || [];
          const timedOut = (data.warnings || []).some((w) => /timed out/i.test(String(w || '')));
          if (got.length > 0 || !timedOut) return resp;
          return searchOne(term, 10);
        })
      );
      const byId = new Map();
      const warnings = [];
      responses.forEach((resp) => {
        const data = resp.data || {};
        (data.test_sets || []).forEach((ts) => {
          const id = String(ts?._id || '');
          if (id && !byId.has(id)) byId.set(id, ts);
        });
        if (Array.isArray(data.warnings)) warnings.push(...data.warnings);
      });
      const tss = [...byId.values()];

      setSearchResults(tss);
      setSearched(true);
      const timeoutWarn = warnings.find((w) => /timed out/i.test(String(w || '')));
      if (!tss.length) {
        setErrorMsg(
          timeoutWarn
            ? `${timeoutWarn} Refine the query (more of the name) and retry.`
            : `No Test Sets found for "${q}"`
        );
      } else if (timeoutWarn) {
        setErrorMsg(`${timeoutWarn} Showing best effort results; refine query for faster response.`);
      } else if (terms.length > 1) {
        setSuccessMsg(`Matched ${tss.length} test set(s) across ${terms.length} names.`);
      } else if (regexMode) {
        setSuccessMsg(`Regex search matched ${tss.length} test set(s).`);
      } else if (warnings.length) {
        setSuccessMsg(`Loaded ${tss.length} test set(s). Refine query to narrow results.`);
      }
      // Keep selected set persistent across searches, but DO NOT block rendering
      // of new search output while recomputing common args for prior selections.
      if (selectedIds.size > 0) {
        Promise.resolve().then(() => {
          inspectSelected([...selectedIds], tss);
        });
      }
    } catch (err) {
      setErrorMsg(`Search failed: ${getErrorMessage(err)}`);
      setSearchResults([]);
      setSearched(true);
    } finally {
      setLoadingSearch(false);
    }
  };

  const toggleSelect = (id) => {
    const row = searchResults.find((ts) => String(ts._id) === String(id));
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
    setSelectedTsMap((prev) => {
      const out = { ...prev };
      if (next.has(id) && row) {
        out[String(id)] = { _id: row._id, name: row.name || row._id };
      } else if (!next.has(id)) {
        delete out[String(id)];
      }
      return out;
    });
    setApplyResult(null);
    if (next.size > 0) inspectSelected([...next]);
    else clearComputed();
  };

  const toggleSelectAll = () => {
    setApplyResult(null);
    if (allSelected) {
      const visibleIds = new Set(searchResults.map((ts) => ts._id));
      const next = new Set([...selectedIds].filter((id) => !visibleIds.has(id)));
      setSelectedIds(next);
      setSelectedTsMap((prev) => {
        const out = { ...prev };
        searchResults.forEach((ts) => delete out[String(ts._id)]);
        return out;
      });
      if (next.size > 0) inspectSelected([...next]);
      else clearComputed();
      return;
    }
    const next = new Set(selectedIds);
    searchResults.forEach((ts) => next.add(ts._id));
    setSelectedIds(next);
    setSelectedTsMap((prev) => {
      const out = { ...prev };
      searchResults.forEach((ts) => {
        out[String(ts._id)] = { _id: ts._id, name: ts.name || ts._id };
      });
      return out;
    });
    inspectSelected([...next]);
  };

  const removeSelectedTs = (id) => {
    const next = new Set(selectedIds);
    next.delete(id);
    setSelectedIds(next);
    setSelectedTsMap((prev) => {
      const out = { ...prev };
      delete out[String(id)];
      return out;
    });
    setApplyResult(null);
    if (next.size > 0) inspectSelected([...next]);
    else clearComputed();
  };

  const clearAllSelected = () => {
    setSelectedIds(new Set());
    setSelectedTsMap({});
    clearComputed();
  };

  const inspectSelected = async (explicitIds = null, _explicitResults = null, options = {}) => {
    const ids = Array.isArray(explicitIds) ? explicitIds : [...selectedIds];
    const count = ids.length;
    if (count === 0) {
      setErrorMsg('Select at least one test set');
      return;
    }
    setInspecting(true);
    if (!options.keepApplyResult) {
      setErrorMsg(null);
      setSuccessMsg(null);
      setApplyResult(null);
    }
    const reqId = ++inspectReqId.current;
    try {
      const rowsById = new Map();
      const fetchErrors = [];
      const chunkSize = 8;
      for (let i = 0; i < ids.length; i += chunkSize) {
        const chunk = ids.slice(i, i + chunkSize);
        const settled = await Promise.allSettled(
          chunk.map(async (id) => {
            const r = await api.post(FETCH_TESTSET_API, { testset_id: id });
            if (!r.data?.test_set) {
              throw new Error(`JITA returned no test set for ${id}`);
            }
            return r.data.test_set;
          })
        );
        settled.forEach((res, idx) => {
          const id = String(chunk[idx]);
          if (res.status === 'fulfilled' && res.value) {
            rowsById.set(id, { ...res.value, _id: res.value._id || id });
          } else {
            fetchErrors.push(id);
          }
        });
        if (reqId !== inspectReqId.current) return;
      }

      const rows = ids
        .map((id) => rowsById.get(String(id)))
        .filter(Boolean);

      if (!rows.length) {
        throw new Error('Could not fetch selected testset arguments from JITA.');
      }
      const frameworkMaps = rows.map((r) => extractCanonicalArgs(r, 'framework'));
      const testMaps = rows.map((r) => extractCanonicalArgs(r, 'test'));

      const likelyParseGap = rows.some((r, idx) => {
        const fwEmpty = Object.keys(frameworkMaps[idx] || {}).length === 0 && hasNonEmptyRawArgs(r, 'framework');
        const taEmpty = Object.keys(testMaps[idx] || {}).length === 0 && hasNonEmptyRawArgs(r, 'test');
        return fwEmpty || taEmpty;
      });
      const fw = extractUnionRows(frameworkMaps);
      const ta = extractUnionRows(testMaps);
      if (fw.length === 0 && ta.length === 0 && likelyParseGap) {
        setErrorMsg('Could not reliably parse some existing args from JITA. Restart backend and retry.');
      } else if (fetchErrors.length && !options.keepApplyResult) {
        setErrorMsg(`Could not refresh ${fetchErrors.length} test set(s) from JITA. Showing fetched test sets only.`);
      }

      if (reqId !== inspectReqId.current) return;
      setCommonFrameworkArgs(fw);
      setCommonTestArgs(ta);
      setSelectedArgEdits({});
      setSelectedTsMap((prev) => {
        const out = { ...prev };
        rows.forEach((r) => {
          const id = String(r._id || r.id || '');
          if (!id) return;
          out[id] = { _id: id, name: r.name || prev[id]?.name || id };
        });
        return out;
      });
      if (!options.keepApplyResult && fw.length === 0 && ta.length === 0 && !likelyParseGap) {
        setSuccessMsg('No framework/test arguments were found on the selected test sets.');
      }
    } catch (err) {
      if (reqId !== inspectReqId.current) return;
      setErrorMsg(`Inspect failed: ${getErrorMessage(err)}`);
    } finally {
      if (reqId === inspectReqId.current) setInspecting(false);
    }
  };

  const setArgEditEnabled = (category, key, enabled, initialValue) => {
    const id = `${category}:${key}`;
    setSelectedArgEdits((prev) => {
      const next = { ...prev };
      if (!enabled) delete next[id];
      else next[id] = initialValue === undefined || initialValue === null ? '' : String(initialValue);
      return next;
    });
    setApplyResult(null);
  };

  const updateArgEditValue = (category, key, value) => {
    const id = `${category}:${key}`;
    setSelectedArgEdits((prev) => ({ ...prev, [id]: value }));
    setApplyResult(null);
  };

  const updateNewArgRow = (category, idx, patch) => {
    const setter = category === 'framework' ? setNewFrameworkArgs : setNewTestArgs;
    setter((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
    setApplyResult(null);
  };

  const addNewArgRow = (category) => {
    const setter = category === 'framework' ? setNewFrameworkArgs : setNewTestArgs;
    setter((prev) => [...prev, newArgRow()]);
    setApplyResult(null);
  };

  const removeNewArgRow = (category, idx) => {
    const setter = category === 'framework' ? setNewFrameworkArgs : setNewTestArgs;
    setter((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
    setApplyResult(null);
  };

  const buildPayload = () => {
    const editFramework = {};
    const editTest = {};
    Object.entries(selectedArgEdits).forEach(([id, value]) => {
      const sep = id.indexOf(':');
      const category = sep >= 0 ? id.slice(0, sep) : '';
      const key = sep >= 0 ? id.slice(sep + 1) : '';
      if (!key) return;
      const nextVal = value == null ? '' : value;
      if (category === 'framework') editFramework[key] = nextVal;
      if (category === 'test') editTest[key] = nextVal;
    });

    const toNewArgs = (rows, category) =>
      rows
        .map((r) => ({
          key: (r.key || '').trim(),
          value: r.value == null ? '' : r.value,
          category,
          overwrite_existing: !!r.overwrite_existing,
        }))
        .filter((r) => r.key);

    const allNewArgs = [
      ...toNewArgs(newFrameworkArgs, 'framework'),
      ...toNewArgs(newTestArgs, 'test'),
    ];

    return {
      ts_ids: [...selectedIds],
      edit_framework_args: editFramework,
      edit_test_args: editTest,
      new_arguments: allNewArgs,
    };
  };

  const hasEdits = useMemo(() => {
    if (Object.keys(selectedArgEdits).length > 0) return true;
    return [...newFrameworkArgs, ...newTestArgs].some((r) => (r.key || '').trim());
  }, [selectedArgEdits, newFrameworkArgs, newTestArgs]);

  const handleApply = async () => {
    if (selectedCount === 0) {
      setErrorMsg('Select at least one test set');
      return;
    }
    if (!hasEdits) {
      setErrorMsg('Select args to edit or add a new key before applying');
      return;
    }
    if (!window.confirm(`Go ahead and apply changes to ${selectedCount} selected test set(s)?`)) return;
    setApplying(true);
    setErrorMsg(null);
    setSuccessMsg(null);
    setApplyResult(null);
    try {
      const payload = buildPayload();
      const ids = [...selectedIds];
      const fetchedRows = [];
      const chunkSize = 8;
      const reqTimeout = { timeout: 90000 };
      for (let i = 0; i < ids.length; i += chunkSize) {
        const chunk = ids.slice(i, i + chunkSize);
        const rows = await Promise.all(
          chunk.map(async (id) => {
            const r = await api.post(FETCH_TESTSET_API, { testset_id: id }, reqTimeout);
            if (!r.data?.test_set) throw new Error(`JITA returned no test set for ${id}`);
            return r.data.test_set;
          })
        );
        fetchedRows.push(...rows);
      }

      const applyOne = async (row) => {
        const tsId = row._id;
        const currentFramework = extractCanonicalArgs(row, 'framework');
        const currentTest = extractCanonicalArgs(row, 'test');
        const fwParseGap = Object.keys(currentFramework).length === 0 && hasNonEmptyRawArgs(row, 'framework');
        const taParseGap = Object.keys(currentTest).length === 0 && hasNonEmptyRawArgs(row, 'test');
        if (fwParseGap || taParseGap) {
          return {
            ts_id: tsId,
            ts_name: row.name || tsId,
            success: false,
            message: 'Skipped to protect existing args: backend args format could not be parsed safely. Restart backend and retry.',
          };
        }
        const tsUpdates = buildTsUpdates(row, payload);
        if (Object.keys(tsUpdates).length === 0) {
          const hadExistingEditKey = (
            Object.keys(payload.edit_framework_args || {}).some((k) => (
              Object.prototype.hasOwnProperty.call(currentFramework, k)
            ))
            || Object.keys(payload.edit_test_args || {}).some((k) => (
              Object.prototype.hasOwnProperty.call(currentTest, k)
            ))
          );
          const hadNewArg = (payload.new_arguments || []).length > 0;
          return {
            ts_id: tsId,
            ts_name: row.name || tsId,
            success: true,
            skipped: true,
            message: hadExistingEditKey
              ? 'Skipped — already up to date.'
              : hadNewArg
                ? 'Skipped — new key already exists (enable Overwrite to replace).'
                : 'Skipped — none of the edited keys exist on this test set.',
          };
        }

        const resp = await api.post(UPDATE_API, {
          ts_id: tsId,
          updates: {
            ts_updates: tsUpdates,
          },
        }, reqTimeout);
        const ok = !!resp?.data?.results?.ts?.success;
        return {
          ts_id: tsId,
          ts_name: row.name || tsId,
          success: ok,
          message: ok ? 'Updated' : (resp?.data?.results?.ts?.message || 'Update failed'),
        };
      };

      const results = [];
      for (let i = 0; i < fetchedRows.length; i += chunkSize) {
        const chunk = fetchedRows.slice(i, i + chunkSize);
        const settled = await Promise.allSettled(chunk.map((row) => applyOne(row)));
        settled.forEach((res, idx) => {
          if (res.status === 'fulfilled') {
            results.push(res.value);
            return;
          }
          const row = chunk[idx] || {};
          results.push({
            ts_id: row._id,
            ts_name: row.name || row._id,
            success: false,
            message: res.reason?.response?.data?.error || res.reason?.message || 'Update failed',
          });
        });
      }

      const updatedCount = results.filter((r) => r.success && !r.skipped).length;
      const skippedCount = results.filter((r) => r.skipped).length;
      const failedUpdates = results.filter((r) => !r.success);
      const failedCount = failedUpdates.length;
      setApplyResult({ results, updated_count: updatedCount, failed_updates: failedUpdates });
      if (failedCount > 0) {
        setErrorMsg(`Applied partially: ${updatedCount} updated, ${failedCount} failed`);
      } else if (updatedCount === 0 && skippedCount > 0) {
        setSuccessMsg('No test sets had the selected keys; nothing was changed.');
      } else {
        const skipNote = skippedCount > 0 ? ` ${skippedCount} skipped (key not present).` : '';
        setSuccessMsg(`Updated ${updatedCount} test set(s) successfully.${skipNote}`);
      }
      await inspectSelected(ids, null, { keepApplyResult: true });
    } catch (err) {
      setErrorMsg(`Apply failed: ${getErrorMessage(err)}`);
    } finally {
      setApplying(false);
    }
  };

  const renderExistingArgRows = (title, category, rows) => (
    <div
      className="djp-section"
      style={{ marginTop: 10, border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff' }}
    >
      <h3 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: '#0f172a' }}>{title}</h3>
      {rows.length === 0 ? (
        <p style={{ color: '#64748b', fontSize: 13 }}>No arguments found.</p>
      ) : (
        <div style={{ display: 'grid', gap: 8, maxHeight: 420, overflowY: 'auto' }}>
          {rows.map((row) => {
            const id = `${category}:${row.key}`;
            const enabled = Object.prototype.hasOwnProperty.call(selectedArgEdits, id);
            const displayValue = row.multiple_values ? 'Multiple Values' : String(row.value ?? '');
            return (
              <div key={id} style={{ display: 'grid', gridTemplateColumns: '24px 1fr 1fr', gap: 10, alignItems: 'center' }}>
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setArgEditEnabled(category, row.key, e.target.checked, row.multiple_values ? '' : row.value)}
                />
                <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#1f2937' }}>{row.key}</div>
                <input
                  className="djp-input"
                  type="text"
                  disabled={!enabled}
                  value={enabled ? selectedArgEdits[id] : displayValue}
                  onChange={(e) => updateArgEditValue(category, row.key, e.target.value)}
                  style={!enabled && row.multiple_values ? { color: '#b45309', fontStyle: 'italic' } : undefined}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );

  const renderNewArgRows = (title, category, rows) => (
    <div
      className="djp-section"
      style={{ marginTop: 12, border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff' }}
    >
      <h3 style={{ margin: '0 0 10px', fontSize: 14, fontWeight: 700, color: '#0f172a' }}>{title}</h3>
      <div style={{ display: 'grid', gap: 8 }}>
        {rows.map((row, idx) => (
          <div key={`${category}-new-${idx}`} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 130px auto', gap: 8, alignItems: 'center' }}>
            <input
              className="djp-input"
              type="text"
              placeholder="Key"
              value={row.key}
              onChange={(e) => updateNewArgRow(category, idx, { key: e.target.value })}
            />
            <input
              className="djp-input"
              type="text"
              placeholder="Value (optional)"
              value={row.value}
              onChange={(e) => updateNewArgRow(category, idx, { value: e.target.value })}
            />
            <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12 }}>
              <input
                type="checkbox"
                checked={row.overwrite_existing}
                onChange={(e) => updateNewArgRow(category, idx, { overwrite_existing: e.target.checked })}
              />
              Overwrite
            </label>
            <button
              className="djp-btn"
              style={{ padding: '4px 10px' }}
              onClick={() => removeNewArgRow(category, idx)}
              disabled={rows.length <= 1}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 8 }}>
        <button className="djp-btn djp-btn-primary" onClick={() => addNewArgRow(category)}>
          + Add Row
        </button>
      </div>
    </div>
  );

  const headerBlock = !embedded ? (
    <div className="djp-header">
      <h1>Manage Test Sets</h1>
    </div>
  ) : null;

  const inner = (
    <>
      {headerBlock}
      <div className="djp-section" style={{ border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff' }}>
        <h3 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700 }}>Step 1: Search Test Sets</h3>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 360px' }}>
            <label className="djp-label">Query</label>
            <input
              className="djp-input"
              style={{ width: '100%' }}
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleSearch(); }}
              placeholder="One name, regex, or multiple names with |  (e.g. Testing_sw.* | CDP_Regression_Upgrade)"
              disabled={loadingSearch}
            />
          </div>
          <button className="djp-btn djp-btn-primary" onClick={handleSearch} disabled={loadingSearch || searchQuery.trim().length < 2}>
            {loadingSearch ? 'Searching...' : 'Search'}
          </button>
        </div>
      </div>

      {errorMsg && <div className="djp-error-box">{errorMsg}</div>}
      {successMsg && (
        <div className="djp-result-box" style={{ borderLeftColor: '#22c55e' }}>
          <p style={{ margin: 0, fontWeight: 600, color: '#16a34a' }}>{successMsg}</p>
        </div>
      )}

      {searched && (
        <div className="djp-section" style={{ border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Step 2: Select Test Sets ({searchResults.length})</h3>
            {searchResults.length > 0 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
                Select All
              </label>
            )}
          </div>
          {searchResults.length === 0 ? (
            <p style={{ color: '#64748b', fontSize: 13 }}>No Test Sets found</p>
          ) : (
            <div className="djp-name-list-selectable" style={{ maxHeight: 320 }}>
              {searchResults.map((ts) => (
                <div
                  key={ts._id}
                  className={`djp-name-item ${selectedIds.has(ts._id) ? 'selected' : ''}`}
                  onClick={() => toggleSelect(ts._id)}
                >
                  <span className="djp-checkbox-dot">{selectedIds.has(ts._id) ? '✓' : ''}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 13, wordBreak: 'break-all' }}>{ts.name}</div>
                    <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 2 }}>ID: {ts._id}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {inspecting && (
            <div style={{ marginTop: 10, fontSize: 12, color: '#0f766e' }}>
              Loading arguments...
            </div>
          )}
        </div>
      )}

      {selectedCount > 0 && (
        <div className="djp-section" style={{ border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff', marginTop: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>
              Selected Test Sets ({selectedCount})
            </h3>
            <button className="djp-btn" style={{ padding: '4px 10px' }} onClick={clearAllSelected}>
              Clear All
            </button>
          </div>
          <div style={{ display: 'grid', gap: 6, maxHeight: 220, overflowY: 'auto' }}>
            {[...selectedIds].map((id) => {
              const item = selectedTsMap[String(id)] || { _id: id, name: id };
              return (
                <div key={String(id)} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px', background: '#f8fafc' }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 12, wordBreak: 'break-all' }}>{item.name}</div>
                    <div style={{ fontSize: 10, color: '#64748b' }}>ID: {item._id}</div>
                  </div>
                  <button className="djp-btn" style={{ padding: '2px 8px' }} onClick={() => removeSelectedTs(id)}>
                    Remove
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {(commonLoaded || selectedCount > 0) && (
        <div className="djp-two-col" style={{ marginTop: 14 }}>
          <div>
            <div style={{ marginBottom: 6, fontSize: 12, fontWeight: 700, color: '#0f172a' }}>
              LEFT COLUMN: TEST ARGUMENTS
            </div>
            {renderExistingArgRows('Existing Test Arguments (union across selected TS)', 'test', commonTestArgs)}
            {renderNewArgRows('Add New Test Arguments', 'test', newTestArgs)}
          </div>
          <div>
            <div style={{ marginBottom: 6, fontSize: 12, fontWeight: 700, color: '#0f172a' }}>
              RIGHT COLUMN: FRAMEWORK ARGUMENTS
            </div>
            {renderExistingArgRows('Existing Framework Arguments (union across selected TS)', 'framework', commonFrameworkArgs)}
            {renderNewArgRows('Add New Framework Arguments', 'framework', newFrameworkArgs)}
          </div>
        </div>
      )}

      {(commonLoaded || selectedCount > 0) && (
        <div className="djp-section" style={{ marginTop: 16, border: '1px solid #e2e8f0', borderRadius: 8, background: '#ffffff' }}>
          <h3 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700 }}>Step 4: Apply Changes</h3>
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="djp-btn djp-btn-danger" onClick={handleApply} disabled={applying || selectedCount === 0 || !hasEdits}>
              {applying ? 'Applying...' : 'Apply Changes'}
            </button>
            <span style={{ fontSize: 12, color: '#64748b', alignSelf: 'center' }}>
              Listing uses JITA Test Args / Test Framework Options (fresh GET per test set). Checking a key never copies it onto another test set. Use Add New to introduce a key.
            </span>
          </div>

          {applyResult?.results?.length > 0 && (
            <div style={{ marginTop: 12, display: 'grid', gap: 6 }}>
              {applyResult.results.map((r) => (
                <div key={r.ts_id} style={{ borderRadius: 6, padding: 8, fontSize: 12, border: `1px solid ${r.success && !r.skipped ? '#bbf7d0' : r.skipped ? '#fde68a' : '#fecaca'}`, background: r.success && !r.skipped ? '#f0fdf4' : r.skipped ? '#fffbeb' : '#fef2f2', color: r.success && !r.skipped ? '#166534' : r.skipped ? '#92400e' : '#b91c1c' }}>
                  <strong>{r.ts_name || r.ts_id}</strong>: {r.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );

  if (embedded) return <div className="djp-manage-embedded">{inner}</div>;
  return <div className="djp-container">{inner}</div>;
}
