import React, { useState, useRef, useCallback, useEffect } from 'react';
import axios from 'axios';
import { API_BASE_URL, jitaJobProfileWebUrl, jitaTestSetWebUrl } from '../config';
import ManageJobProfile from './ManageJobProfile';
import { useAuth } from '../context/AuthContext';
import './DynamicJobProfile.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/dynamic-jp`;

const derivePcBranch = (branch) =>
  branch.trim().toLowerCase() === 'master' ? 'master' : `${branch}-pc`;

const buildDefaultConfig = (branchName = 'master') => ({
  nosBranch: branchName,
  nosTag: 'Latest Smoke Passed',
  pcBranch: derivePcBranch(branchName),
  pcTag: 'Latest Smoke Passed',
  nutestBranch: branchName,
  provider: 'global_pool',
  resourceType: 'nested_2.0',
  nodePool: [],
  frameworkPatchUrl: '',
  testPatchUrl: '',
});

const getReleaseType = (branchName) =>
  branchName.trim().toLowerCase() === 'master' ? 'opt' : 'release';

const RESOURCE_TYPE_OPTIONS = [
  { value: 'nested_2.0', label: 'NestedAHV 2.0' },
  { value: 'nested_1.0', label: 'NestedAHV 1.0' },
  { value: 'physical',   label: 'Physical' },
];

/** Local calendar YYYYMMDD — matches backend `dyn_name_date` for generated names. */
const formatLocalYyyymmdd = () => {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}${m}${day}`;
};

const formatLocalDdmm = () => {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, '0')}${String(d.getMonth() + 1).padStart(2, '0')}`;
};

const userInitials = (user) => {
  const raw = user?.email || user?.sub || user?.username || user?.name || 'john.doe';
  const local = String(raw).split('@')[0];
  const parts = local.split(/[._\-\s]+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return local.slice(0, 2).toUpperCase();
};

const meaningfulNameSuffix = (name) => {
  const cleaned = String(name || '')
    .trim()
    .replace(/^CDP[_-]+/i, '')
    .replace(/>=/g, '_GTE_')
    .replace(/<=/g, '_LTE_')
    .replace(/>/g, '_GT_')
    .replace(/</g, '_LT_')
    .replace(/[^A-Za-z0-9]+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
  return cleaned.slice(0, 80);
};

const PATCH_TEST_MARKER = 'TEMP_PATCH_TEST';

const formatPatchTestName = (name) => {
  const raw = String(name || '').trim();
  if (!raw) return raw;

  return raw
    .replace(new RegExp(`_${PATCH_TEST_MARKER}(?=_|$)`, 'g'), '')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '');
};

const buildSuggestedEntityName = (prefix, num, kind, suffix = '') => {
  const cleanSuffix = suffix ? `_${suffix}` : '';
  if (new RegExp(`_${kind}_$`, 'i').test(prefix)) {
    return `${prefix}${num}${cleanSuffix}`;
  }
  return `${prefix}${num}${cleanSuffix}`;
};

/** Clipboard icon for JP/TS result copy buttons */
function DjpCopyGlyph() {
  return (
    <svg
      className="djp-copy-glyph"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h5a2 2 0 0 1 2 2v1" />
    </svg>
  );
}

export default function DynamicJobProfile() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [showExisting, setShowExisting] = useState(false);
  const [testcaseInput, setTestcaseInput] = useState('');
  const [branch, setBranch] = useState('master');

  // Search results (showExisting mode)
  const [execHistoryFetched, setExecHistoryFetched] = useState(false);
  const [uniquePairs, setUniquePairs] = useState([]);

  // Selected source JP / TS
  const [selectedJP, setSelectedJP] = useState(null);
  const [selectedJPName, setSelectedJPName] = useState('');
  const [selectedTestSetName, setSelectedTestSetName] = useState('');
  const [testSetDetails, setTestSetDetails] = useState(null);
  const [resolvedJPId, setResolvedJPId] = useState(null);
  const [resolvedTSId, setResolvedTSId] = useState(null);
  const [resolving, setResolving] = useState(false);

  // Custom names for the new JP and TS
  const [customJPName, setCustomJPName] = useState('');
  const [customTSName, setCustomTSName] = useState('');
  /** Clone mode only: link new JP to source TS instead of creating a TS with only the typed testcases. */
  const [reuseSourceTS, setReuseSourceTS] = useState(false);
  /** Clone mode only: retain deployment after each test failure, without DataCorruptionError exception. */
  const [retainSetupOnFailure, setRetainSetupOnFailure] = useState(false);
  /** Keeps the last "New Testset" name if user toggles to Use Existing (field hidden) and back. */
  const newTestSetNameWhenNewMode = useRef('');

  // Tag support
  const [showTagInput, setShowTagInput] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [jpTags, setJpTags] = useState([]);

  // Config for fresh creation
  const [config, setConfig] = useState(() => buildDefaultConfig(branch));
  const [nextJPNum, setNextJPNum] = useState(1);
  const [nextTSNum, setNextTSNum] = useState(1);
  const [createResult, setCreateResult] = useState(null);
  /** Brief feedback after copying JP/TS line ('jp' | 'ts'). */
  const [createResultCopyFlash, setCreateResultCopyFlash] = useState(null);
  const createResultCopyTimerRef = useRef(null);
  const [readyToConfigure, setReadyToConfigure] = useState(false);

  // Patch toggle and search helpers
  const [showPatch, setShowPatch] = useState(false);
  const [nodePoolSearch, setNodePoolSearch] = useState('');
  const [nodePoolResults, setNodePoolResults] = useState([]);
  const [nodePoolLoading, setNodePoolLoading] = useState(false);
  const nodePoolReqId = useRef(0);
  const nodePoolDebounce = useRef(null);

  const [clusterSearch, setClusterSearch] = useState('');
  const [clusterResults, setClusterResults] = useState([]);
  const [clusterLoading, setClusterLoading] = useState(false);
  const clusterReqId = useRef(0);
  const clusterDebounce = useRef(null);

  const [branchResults, setBranchResults] = useState([]);
  const [branchLoading, setBranchLoading] = useState(false);
  const branchReqId = useRef(0);
  const branchDebounce = useRef(null);

  const [djpSubView, setDjpSubView] = useState('create');
  const [showDjpManageMenu, setShowDjpManageMenu] = useState(false);
  const djpManageMenuRef = useRef(null);

  useEffect(() => {
    const onDocMouseDown = (e) => {
      if (djpManageMenuRef.current && !djpManageMenuRef.current.contains(e.target)) {
        setShowDjpManageMenu(false);
      }
    };
    if (showDjpManageMenu) {
      document.addEventListener('mousedown', onDocMouseDown);
    }
    return () => document.removeEventListener('mousedown', onDocMouseDown);
  }, [showDjpManageMenu]);

  useEffect(
    () => () => {
      if (createResultCopyTimerRef.current) clearTimeout(createResultCopyTimerRef.current);
    },
    []
  );

  useEffect(() => {
    if (!reuseSourceTS) {
      newTestSetNameWhenNewMode.current = customTSName;
    }
  }, [customTSName, reuseSourceTS]);

  useEffect(() => {
    if (!readyToConfigure) return;
    setCustomJPName((prev) => formatPatchTestName(prev, showPatch));
    if (!reuseSourceTS) {
      setCustomTSName((prev) => formatPatchTestName(prev, showPatch));
    }
  }, [showPatch, readyToConfigure, reuseSourceTS]);

  const parseTestcaseNames = () =>
    testcaseInput
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);

  const getErrorMessage = (error) => {
    if (error.response?.data?.error) return error.response.data.error;
    if (error.response?.status === 503) return 'Backend is unreachable. Is the Flask server running?';
    if (error.response?.status === 504) return 'Request timed out. JITA may be slow or unreachable.';
    if (error.code === 'ERR_NETWORK') return 'Network error. Check your connection and ensure the backend is running.';
    if (error.code === 'ECONNABORTED') return 'Request timed out.';
    return error.message || 'An unknown error occurred';
  };

  const resetSelections = () => {
    setSelectedJP(null);
    setSelectedJPName('');
    setSelectedTestSetName('');
    setTestSetDetails(null);
    setResolvedJPId(null);
    setResolvedTSId(null);
    setCustomJPName('');
    setCustomTSName('');
    setJpTags([]);
    setTagInput('');
    setShowTagInput(false);
    setReuseSourceTS(false);
    setRetainSetupOnFailure(false);
  };

  const fetchNextNumbers = async () => {
    const dynNameDate = formatLocalYyyymmdd();
    const userPrefix = `${userInitials(user)}_${formatLocalDdmm()}_P`;
    const fallbackJpPrefix = userPrefix;
    const fallbackTsPrefix = userPrefix;
    try {
      const response = await axios.post(`${API_BASE}/check-existing`, {
        dyn_name_date: dynNameDate,
        jp_pattern: fallbackJpPrefix,
        ts_pattern: fallbackTsPrefix,
      });
      const data = response.data || {};
      const jpNum = typeof data.next_jp_number === 'number' ? data.next_jp_number : 1;
      const tsNum = typeof data.next_ts_number === 'number' ? data.next_ts_number : 1;
      const jpPrefix = typeof data.jp_name_prefix === 'string' && data.jp_name_prefix
        ? data.jp_name_prefix
        : fallbackJpPrefix;
      const tsPrefix = typeof data.ts_name_prefix === 'string' && data.ts_name_prefix
        ? data.ts_name_prefix
        : fallbackTsPrefix;
      setNextJPNum(jpNum);
      setNextTSNum(tsNum);
      return { jpNum, tsNum, jpPrefix, tsPrefix };
    } catch (_) {
      return { jpNum: nextJPNum, tsNum: nextTSNum, jpPrefix: fallbackJpPrefix, tsPrefix: fallbackTsPrefix };
    }
  };

  /** Apply suggested temporary JP/TS names from a check-existing result (no extra network). */
  const applyNamesFromCheckData = (d, jpName, tsName) => {
    const jpSuffix = meaningfulNameSuffix(jpName);
    const tsSuffix = meaningfulNameSuffix(tsName);
    if (jpSuffix) {
      setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP', jpSuffix), showPatch));
    } else {
      setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP'), showPatch));
    }
    if (tsSuffix) {
      setCustomTSName(formatPatchTestName(buildSuggestedEntityName(d.tsPrefix, d.tsNum, 'TS', tsSuffix), showPatch));
    } else {
      setCustomTSName(formatPatchTestName(buildSuggestedEntityName(d.tsPrefix, d.tsNum, 'TS'), showPatch));
    }
  };

  const clearJPAndTSSelection = (e) => {
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    setSelectedJP(null);
    setSelectedJPName('');
    setResolvedJPId(null);
    setSelectedTestSetName('');
    setResolvedTSId(null);
    setTestSetDetails(null);
    setErrorMsg(null);
    (async () => {
      const d = await fetchNextNumbers();
      setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP'), showPatch));
      setCustomTSName(formatPatchTestName(buildSuggestedEntityName(d.tsPrefix, d.tsNum, 'TS'), showPatch));
    })();
  };

  /**
   * @param {string} jpName
   * @param {{ testSetName?: string | null }} [pair] — use when batching with TS so naming sees both before state updates.
   */
  const handleSelectJP = async (jpName, pair = {}) => {
    const tsName =
      pair.testSetName !== undefined ? pair.testSetName : (selectedTestSetName || null);
    setSelectedJPName(jpName);
    setResolvedJPId(null);
    setResolving(true);
    setErrorMsg(null);
    try {
      const [resp, d] = await Promise.all([
        axios.post(`${API_BASE}/resolve-names`, { jp_name: jpName }),
        fetchNextNumbers(),
      ]);
      if (resp.data?.jp?._id) {
        setSelectedJP(resp.data.jp._id);
        setResolvedJPId(resp.data.jp._id);
        applyNamesFromCheckData(d, jpName, tsName);
      } else {
        setSelectedJP(null);
        setErrorMsg(`Could not resolve Job Profile "${jpName}" to an ID. It may not exist in JITA.`);
      }
    } catch (err) {
      if (err.response?.status === 404) {
        setErrorMsg('Backend needs restart — the resolve-names endpoint is not loaded yet.');
      } else {
        setErrorMsg(`Failed to resolve JP name: ${getErrorMessage(err)}`);
      }
    } finally {
      setResolving(false);
    }
  };

  /**
   * @param {string} tsName
   * @param {{ jobProfileName?: string | null }} [pair] — use when batching with JP so naming sees both before state updates.
   */
  const handleSelectTS = async (tsName, pair = {}) => {
    const jpName =
      pair.jobProfileName !== undefined ? pair.jobProfileName : (selectedJPName || null);
    setSelectedTestSetName(tsName);
    setResolvedTSId(null);
    setTestSetDetails(null);
    setResolving(true);
    setErrorMsg(null);
    try {
      const [resp, d] = await Promise.all([
        axios.post(`${API_BASE}/resolve-names`, { ts_name: tsName }),
        fetchNextNumbers(),
      ]);
      if (resp.data?.ts?._id) {
        setResolvedTSId(resp.data.ts._id);
        setTestSetDetails(resp.data.ts);
        applyNamesFromCheckData(d, jpName, tsName);
      } else {
        setErrorMsg(`Could not resolve Test Set "${tsName}" to an ID. It may not exist in JITA.`);
      }
    } catch (err) {
      if (err.response?.status === 404) {
        setErrorMsg('Backend needs restart — the resolve-names endpoint is not loaded yet.');
      } else {
        setErrorMsg(`Failed to resolve TS name: ${getErrorMessage(err)}`);
      }
    } finally {
      setResolving(false);
    }
  };

  const handleAddTag = () => {
    const tag = tagInput.trim();
    if (tag && !jpTags.includes(tag)) {
      setJpTags([...jpTags, tag]);
    }
    setTagInput('');
  };

  const handleRemoveTag = (tag) => {
    setJpTags(jpTags.filter(t => t !== tag));
  };

  const handleSearch = async () => {
    const names = parseTestcaseNames();
    if (names.length === 0 && showExisting) {
      setErrorMsg('Please enter at least one testcase name');
      return;
    }

    setCreateResult(null);
    setErrorMsg(null);

    if (showExisting) {
      setLoading(true);
      setExecHistoryFetched(false);
      setUniquePairs([]);
      resetSelections();
      try {
        const [histResp, numData] = await Promise.all([
          axios.post(`${API_BASE}/test-execution-history`, {
            test_name: names[0],
            page: 1,
            limit: 200,
            sort: '-start_time',
            branch: branch || '',
          }),
          fetchNextNumbers(),
        ]);
        const data = histResp.data || {};
        const pairRows = Array.isArray(data.unique_pairs) ? data.unique_pairs : [];
        setUniquePairs(pairRows);
        setExecHistoryFetched(true);
        const num = Math.max(numData.jpNum, numData.tsNum);
        setCustomJPName(formatPatchTestName(buildSuggestedEntityName(numData.jpPrefix, num, 'JP'), showPatch));
        setCustomTSName(formatPatchTestName(buildSuggestedEntityName(numData.tsPrefix, num, 'TS'), showPatch));
        setReadyToConfigure(true);

        const firstFullPair = pairRows.find(
          (p) =>
            p &&
            String(p.test_set || '').trim() &&
            String(p.job_profile || '').trim()
        );
        if (firstFullPair) {
          const tsN = String(firstFullPair.test_set).trim();
          const jpN = String(firstFullPair.job_profile).trim();
          await handleSelectTS(tsN, { jobProfileName: jpN });
          await handleSelectJP(jpN, { testSetName: tsN });
        } else {
          const tsSet = new Set();
          const jpSet = new Set();
          for (const p of pairRows) {
            if (p.test_set) tsSet.add(p.test_set.trim());
            if (p.job_profile) jpSet.add(p.job_profile.trim());
          }
          const sortedTS = [...tsSet].sort();
          const sortedJP = [...jpSet].sort();
          const ts0 = sortedTS[0];
          const jp0 = sortedJP[0];
          if (ts0 && jp0) {
            await handleSelectTS(ts0, { jobProfileName: jp0 });
            await handleSelectJP(jp0, { testSetName: ts0 });
          } else if (ts0) {
            await handleSelectTS(ts0);
          } else if (jp0) {
            await handleSelectJP(jp0);
          }
        }
      } catch (error) {
        console.error('Error fetching execution history:', error);
        setErrorMsg(`Failed to fetch test history: ${getErrorMessage(error)}`);
      } finally {
        setLoading(false);
      }
    } else {
      resetSelections();
      setReadyToConfigure(true);
      const numData = await fetchNextNumbers();
      const num = Math.max(numData.jpNum, numData.tsNum);
      setCustomJPName(formatPatchTestName(buildSuggestedEntityName(numData.jpPrefix, num, 'JP'), showPatch));
      setCustomTSName(formatPatchTestName(buildSuggestedEntityName(numData.tsPrefix, num, 'TS'), showPatch));
    }
  };

  const handleApplyLatest = () => {
    setConfig(buildDefaultConfig(branch));
    setShowPatch(false);
  };

  const handleSearchNodePools = useCallback((query) => {
    setNodePoolSearch(query);
    if (nodePoolDebounce.current) clearTimeout(nodePoolDebounce.current);
    if (!query || query.length < 2) {
      setNodePoolResults([]);
      setNodePoolLoading(false);
      return;
    }
    setNodePoolLoading(true);
    nodePoolDebounce.current = setTimeout(async () => {
      const reqId = ++nodePoolReqId.current;
      try {
        const response = await axios.post(`${API_BASE}/search-node-pools`, { query });
        if (reqId === nodePoolReqId.current) {
          setNodePoolResults(Array.isArray(response.data?.pools) ? response.data.pools : []);
        }
      } catch (_) {
        if (reqId === nodePoolReqId.current) setNodePoolResults([]);
      } finally {
        if (reqId === nodePoolReqId.current) setNodePoolLoading(false);
      }
    }, 300);
  }, []);

  const handleSearchClusters = useCallback((query) => {
    setClusterSearch(query);
    if (clusterDebounce.current) clearTimeout(clusterDebounce.current);
    if (!query || query.length < 2) {
      setClusterResults([]);
      setClusterLoading(false);
      return;
    }
    setClusterLoading(true);
    clusterDebounce.current = setTimeout(async () => {
      const reqId = ++clusterReqId.current;
      try {
        const response = await axios.post(`${API_BASE}/search-clusters`, { query });
        if (reqId === clusterReqId.current) {
          setClusterResults(Array.isArray(response.data?.clusters) ? response.data.clusters : []);
        }
      } catch (_) {
        if (reqId === clusterReqId.current) setClusterResults([]);
      } finally {
        if (reqId === clusterReqId.current) setClusterLoading(false);
      }
    }, 300);
  }, []);

  const handleSearchBranches = useCallback((query) => {
    if (branchDebounce.current) clearTimeout(branchDebounce.current);
    if (!query || query.length < 2) {
      setBranchResults([]);
      setBranchLoading(false);
      return;
    }
    setBranchLoading(true);
    branchDebounce.current = setTimeout(async () => {
      const reqId = ++branchReqId.current;
      try {
        const response = await axios.post(`${API_BASE}/search-branches`, { query });
        if (reqId === branchReqId.current) {
          setBranchResults(Array.isArray(response.data?.branches) ? response.data.branches : []);
        }
      } catch (_) {
        if (reqId === branchReqId.current) setBranchResults([]);
      } finally {
        if (reqId === branchReqId.current) setBranchLoading(false);
      }
    }, 300);
  }, []);

  const handleCreate = async () => {
    const names = parseTestcaseNames();
    if (names.length === 0 && !(showExisting && reuseSourceTS)) {
      setErrorMsg('Please enter at least one testcase name (or enable “Use existing test set” in clone mode)');
      return;
    }
    if (showExisting && !selectedJP) {
      setErrorMsg('Please select a source Job Profile from the list');
      return;
    }

    setLoading(true);
    setCreateResult(null);
    setCreateResultCopyFlash(null);
    if (createResultCopyTimerRef.current) {
      clearTimeout(createResultCopyTimerRef.current);
      createResultCopyTimerRef.current = null;
    }
    setErrorMsg(null);
    try {
      const allTags = [...new Set(jpTags)];

      const response = await axios.post(`${API_BASE}/create`, {
        source_jp_id: showExisting ? selectedJP : null,
        source_testset_id: showExisting ? (resolvedTSId || testSetDetails?._id || null) : null,
        source_testset_name: showExisting ? (selectedTestSetName || null) : null,
        nos_branch: config.nosBranch || 'master',
        nos_tag: config.nosTag || 'Latest Smoke Passed',
        pc_branch: config.pcBranch || 'master',
        pc_tag: config.pcTag || 'Latest Smoke Passed',
        nutest_branch: config.nutestBranch || 'master',
        provider: config.provider || 'global_pool',
        resource_type: config.resourceType || 'nested_2.0',
        node_pool: Array.isArray(config.nodePool) ? config.nodePool : [],
        framework_patch_url: showPatch ? (config.frameworkPatchUrl || '') : '',
        test_patch_url: showPatch ? (config.testPatchUrl || '') : '',
        testcase_names: names,
        create_fresh: !showExisting,
        custom_jp_name: customJPName || null,
        custom_ts_name: customTSName || null,
        dyn_name_date: formatLocalYyyymmdd(),
        jp_tags: allTags.length > 0 ? allTags : [],
        reuse_source_ts: !!(showExisting && reuseSourceTS),
        retain_setup_on_failure: !!(showExisting && retainSetupOnFailure),
      });
      if (response.data?.success) {
        setCreateResult(response.data);
      } else {
        setErrorMsg(response.data?.error || 'Creation returned without success flag');
      }
    } catch (error) {
      console.error('Error creating dynamic profile:', error);
      const serverMsg = error?.response?.data?.error;
      if (serverMsg) {
        setErrorMsg(serverMsg);
      } else {
        setErrorMsg(`Failed to create dynamic profile: ${getErrorMessage(error)}`);
      }
    } finally {
      setLoading(false);
    }
  };

  const handleCopyResultEntity = useCallback((which, text) => {
    const t = (text || '').trim();
    if (!t) return;
    const flash = () => {
      if (createResultCopyTimerRef.current) clearTimeout(createResultCopyTimerRef.current);
      setCreateResultCopyFlash(which);
      createResultCopyTimerRef.current = setTimeout(() => {
        setCreateResultCopyFlash(null);
        createResultCopyTimerRef.current = null;
      }, 1600);
    };
    const fallback = () => {
      try {
        const ta = document.createElement('textarea');
        ta.value = t;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        flash();
      } catch (_) {
        /* ignore */
      }
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(t).then(flash).catch(fallback);
    } else {
      fallback();
    }
  }, []);

  // Shared tag input UI used by both clone and fresh modes
  const renderErrorMsg = () =>
    errorMsg ? (
      <div className="djp-inline-error">
        <span>{errorMsg}</span>
        <button onClick={() => setErrorMsg(null)} title="Dismiss">&times;</button>
      </div>
    ) : null;

  /** Add tags and Patch toggles on one row; tag fields then patch fields open below. */
  const renderTagsAndPatchSection = () => (
    <div className="djp-tag-section">
      <div className="djp-tag-patch-toggles" role="group" aria-label="Tags and patches">
        <div className="djp-toggle-row djp-toggle-row--inline">
          <label>Add tags</label>
          <div
            className={`djp-toggle ${showTagInput ? 'active' : ''}`}
            onClick={() => setShowTagInput(!showTagInput)}
            role="switch"
            aria-checked={showTagInput}
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        {showExisting && (
          <div className="djp-toggle-row djp-toggle-row--inline">
            <label>Retain setup</label>
            <div
              className={`djp-toggle ${retainSetupOnFailure ? 'active' : ''}`}
              onClick={() => setRetainSetupOnFailure(!retainSetupOnFailure)}
              role="switch"
              aria-checked={retainSetupOnFailure}
              title="Retain deployments after each test failure"
            >
              <div className="djp-toggle-knob" />
            </div>
          </div>
        )}
        <div className="djp-toggle-row djp-toggle-row--inline">
          <label>Patch</label>
          <div
            className={`djp-toggle ${showPatch ? 'active' : ''}`}
            onClick={() => setShowPatch(!showPatch)}
            role="switch"
            aria-checked={showPatch}
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
      </div>
      {showTagInput && (
        <div className="djp-tag-input-area djp-tag-patch-expand">
          <div className="djp-tag-input-row">
            <input
              type="text"
              value={tagInput}
              onChange={(e) => setTagInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleAddTag(); } }}
              placeholder="Type a tag and press Enter"
            />
            <button
              className="djp-btn djp-btn-primary djp-btn-sm"
              onClick={handleAddTag}
              disabled={!tagInput.trim()}
            >
              Add
            </button>
          </div>
          {jpTags.length > 0 && (
            <div className="djp-tag-chips">
              {jpTags.map((tag) => (
                <span key={tag} className="djp-tag-chip">
                  {tag}
                  <button onClick={() => handleRemoveTag(tag)} title="Remove tag">&times;</button>
                </span>
              ))}
            </div>
          )}
          <small style={{ color: '#64748b' }}>Tags will be added to the JP's advanced options</small>
        </div>
      )}
      {showPatch && (
        <div className="djp-patch-fields djp-tag-patch-expand">
          <div className="djp-form-group">
            <label>Framework Patch URL</label>
            <input
              type="text"
              value={config.frameworkPatchUrl}
              onChange={(e) => setConfig({ ...config, frameworkPatchUrl: e.target.value })}
              placeholder="https://nugerrit.ntnxdpro.com/changes/nutest-py3~.../patch?zip"
            />
          </div>
          <div className="djp-form-group">
            <label>Nutest-Py3-Tests Patch URL</label>
            <input
              type="text"
              value={config.testPatchUrl}
              onChange={(e) => setConfig({ ...config, testPatchUrl: e.target.value })}
              placeholder="https://nugerrit.ntnxdpro.com/changes/nutest-py3-tests~.../patch?zip"
            />
          </div>
        </div>
      )}
    </div>
  );

  // Shared result box UI
  const renderResultBox = (title) => {
    if (!createResult?.success) return null;
    const jp = createResult.job_profile;
    const ts = createResult.test_set;
    const jpName = jp?.name || 'Unknown';
    const tsName = ts?.name || 'Unknown';
    const jpId = jp?._id;
    const tsId = ts?._id;
    const jpHref = jp?.ui_url || jitaJobProfileWebUrl(jpId, jpName);
    const tsHref = ts?.ui_url || jitaTestSetWebUrl(tsId, tsName);
    return (
      <div className="djp-result-box">
        <h3>{title}</h3>
        <p className="djp-result-entity-line">
          {jpHref ? (
            <a
              href={jpHref}
              target="_blank"
              rel="noreferrer"
              className="djp-jita-entity-link"
              aria-label={`Open job profile ${jpName} in JITA`}
            >
              <span className="djp-jita-entity-prefix">JP</span>
              <code>{jpName}</code>
            </a>
          ) : (
            <>
              <span className="djp-jita-entity-prefix djp-jita-entity-prefix--static">JP</span>
              <code>{jpName}</code>
            </>
          )}
          <button
            type="button"
            className="djp-result-copy-btn"
            title="Copy job profile name"
            aria-label="Copy job profile name"
            onClick={() => handleCopyResultEntity('jp', jpName)}
          >
            <DjpCopyGlyph />
          </button>
          {createResultCopyFlash === 'jp' && (
            <span className="djp-result-copied" role="status">
              Copied
            </span>
          )}
        </p>
        {ts && (
          <p className="djp-result-entity-line">
            {tsHref ? (
              <a
                href={tsHref}
                target="_blank"
                rel="noreferrer"
                className="djp-jita-entity-link"
                aria-label={`Open test set ${tsName} in JITA`}
              >
                <span className="djp-jita-entity-prefix">TS</span>
                <code>{tsName}</code>
              </a>
            ) : (
              <>
                <span className="djp-jita-entity-prefix djp-jita-entity-prefix--static">TS</span>
                <code>{tsName}</code>
              </>
            )}
            <button
              type="button"
              className="djp-result-copy-btn"
              title="Copy test set name"
              aria-label="Copy test set name"
              onClick={() => handleCopyResultEntity('ts', tsName)}
            >
              <DjpCopyGlyph />
            </button>
            {createResultCopyFlash === 'ts' && (
              <span className="djp-result-copied" role="status">
                Copied
              </span>
            )}
            {ts.reused && (
              <span className="djp-info-banner info" style={{ display: 'inline', marginLeft: '8px', padding: '2px 8px', fontSize: '11px' }}>
                Already existed &mdash; reused
              </span>
            )}
          </p>
        )}
        {!ts && (
          <p style={{ color: '#856404', fontSize: '13px' }}>
            Note: No test set was created (test set creation may have failed).
          </p>
        )}
        <p style={{ color: '#7f8c8d', fontSize: '13px' }}>{createResult.message || ''}</p>
        {createResult.warnings?.length > 0 && (
          <div className="djp-info-banner warning" style={{ marginTop: '10px' }}>
            <strong>Warnings:</strong>
            <ul style={{ margin: '5px 0 0 0', paddingLeft: '20px' }}>
              {createResult.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="djp-container">
      <div className="djp-header">
        <h1>Dynamic Job Profile</h1>
        <div className="djp-header-actions">
          <div className="djp-actions-wrapper" ref={djpManageMenuRef}>
            <button
              type="button"
              className="djp-btn djp-btn-manage-actions"
              onClick={() => setShowDjpManageMenu((v) => !v)}
              aria-expanded={showDjpManageMenu}
              aria-haspopup="true"
            >
              Action ▾
            </button>
            {showDjpManageMenu && (
              <div className="djp-actions-dropdown" role="menu">
                <button
                  type="button"
                  className="djp-actions-item"
                  role="menuitem"
                  onClick={() => {
                    setDjpSubView('create');
                    setShowDjpManageMenu(false);
                  }}
                >
                  Create
                </button>
                <button
                  type="button"
                  className="djp-actions-item"
                  role="menuitem"
                  onClick={() => {
                    setDjpSubView('manage');
                    setShowDjpManageMenu(false);
                  }}
                >
                  Delete
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {djpSubView === 'manage' ? (
        <ManageJobProfile embedded />
      ) : (
      <>
      {/* Error messages are displayed below the Create buttons */}

      {/* Step 1: Testcase input + Branch + Toggle */}
      <div className="djp-section">
        <h3 className="djp-section-title">Step 1: Enter Testcase Names</h3>
        <div className="djp-form-group">
          <textarea
            value={testcaseInput}
            onChange={(e) => setTestcaseInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter' || e.shiftKey) return;
              e.preventDefault();
              if (loading || (showExisting && !testcaseInput.trim())) return;
              handleSearch();
            }}
            placeholder="Enter fully qualified testcase names (space, comma, or line break between names)&#10;e.g.&#10;cdp.stargate.storage_policy.api.test_storage_policy.TestStoragePolicy.test_storage_policy___duplicate_name"
            rows={4}
          />
          <small>Space, comma, or newline between testcase names. Enter runs search; Shift+Enter adds a line.</small>
        </div>

        <div className="djp-search-row">
          <div className="djp-form-group" style={{ flex: 1, minWidth: 0, position: 'relative' }}>
            <label>Branch</label>
            <input
              type="text"
              value={branch}
              onChange={(e) => {
                const val = e.target.value;
                setBranch(val);
                setConfig(prev => ({
                  ...prev,
                  nosBranch: val,
                  pcBranch: derivePcBranch(val),
                  nutestBranch: val,
                }));
                handleSearchBranches(val);
              }}
              onBlur={() => setTimeout(() => setBranchResults([]), 150)}
              placeholder="Type to search (e.g., master, ganges-7.6)"
            />
            {branchLoading && <small style={{ color: '#64748b' }}>Searching...</small>}
            {branchResults.length > 0 && (
              <div className="djp-pool-results" style={{ position: 'absolute', zIndex: 10, left: 0, right: 0, marginTop: '2px' }}>
                {branchResults.map((b) => (
                  <div
                    key={b}
                    className={`djp-pool-item ${branch === b ? 'selected' : ''}`}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      setBranch(b);
                      setConfig(prev => ({
                        ...prev,
                        nosBranch: b,
                        pcBranch: derivePcBranch(b),
                        nutestBranch: b,
                      }));
                      setBranchResults([]);
                    }}
                  >
                    {b}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="djp-toggle-group">
            <label className="djp-toggle-label">Show Existing</label>
            <div
              className={`djp-toggle ${showExisting ? 'active' : ''}`}
              onClick={() => {
                setShowExisting(!showExisting);
                setReadyToConfigure(false);
                setExecHistoryFetched(false);
                setUniquePairs([]);
                resetSelections();
                setCreateResult(null);
              }}
            >
              <div className="djp-toggle-knob" />
            </div>
            <small className="djp-toggle-hint">
              {showExisting ? 'Show execution history' : 'Create new JP & test set'}
            </small>
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-end' }}>
            <button
              className="djp-btn djp-btn-primary"
              onClick={handleSearch}
              disabled={loading || (showExisting && !testcaseInput.trim())}
            >
              {loading ? 'Searching...' : showExisting ? 'Search History' : 'Proceed'}
            </button>
          </div>
        </div>
        {!showExisting && (
          <small className="djp-toggle-hint" style={{ display: 'block', marginTop: '8px' }}>
            In direct create you can proceed with an empty testcase list and add names later in the box above.
          </small>
        )}
      </div>

      {/* Clone mode: selectable JP & TS lists */}
      {showExisting && execHistoryFetched && (() => {
        const tsSet = new Set();
        const jpSet = new Set();
        for (const p of uniquePairs) {
          if (p.test_set) tsSet.add(p.test_set.trim());
          if (p.job_profile) jpSet.add(p.job_profile.trim());
        }
        const uniqueTS = [...tsSet].sort();
        const uniqueJP = [...jpSet].sort();
        return (
          <div className="djp-section">
            {uniqueTS.length === 0 && uniqueJP.length === 0 ? (
              <div className="djp-info-banner warning">
                No test sets or job profiles found for this testcase.
              </div>
            ) : (
              <>
                <h3 className="djp-section-title">Step 2: Select Source JP & Test Set to Clone</h3>
                {(selectedJPName || selectedTestSetName || resolvedJPId || resolvedTSId) && (
                  <div className="djp-clear-selection-row">
                    <button
                      type="button"
                      className="djp-btn djp-btn-secondary"
                      style={{ fontSize: '12px', padding: '4px 10px' }}
                      onClick={clearJPAndTSSelection}
                    >
                      Clear selection
                    </button>
                  </div>
                )}
                <div className="djp-unique-lists">
                  <div className="djp-unique-list-col">
                    <div className="djp-list-heading-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                      <h4 className="djp-list-heading" style={{ margin: 0 }}>
                        Test Sets <span className="djp-list-count">{uniqueTS.length}</span>
                      </h4>
                    </div>
                    <ul className="djp-name-list djp-name-list-selectable">
                      {uniqueTS.map((name, i) => (
                        <li
                          key={i}
                          className={`djp-name-item ${selectedTestSetName === name ? 'selected' : ''}`}
                          onClick={() => handleSelectTS(name)}
                        >
                          <span className="djp-radio-dot">
                            {selectedTestSetName === name && <span className="djp-radio-dot-inner" />}
                          </span>
                          <span className="djp-name-text">{name}</span>
                          {selectedTestSetName === name && resolvedTSId && (
                            <span className="djp-resolved-badge">ID: {resolvedTSId.slice(-8)}</span>
                          )}
                          {selectedTestSetName === name && resolving && (
                            <span className="djp-resolving-text">resolving...</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="djp-unique-list-col">
                    <div className="djp-list-heading-row" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', flexWrap: 'wrap' }}>
                      <h4 className="djp-list-heading" style={{ margin: 0 }}>
                        Job Profiles <span className="djp-list-count">{uniqueJP.length}</span>
                      </h4>
                    </div>
                    <ul className="djp-name-list djp-name-list-selectable">
                      {uniqueJP.map((name, i) => (
                        <li
                          key={i}
                          className={`djp-name-item ${selectedJPName === name ? 'selected' : ''}`}
                          onClick={() => handleSelectJP(name)}
                        >
                          <span className="djp-radio-dot">
                            {selectedJPName === name && <span className="djp-radio-dot-inner" />}
                          </span>
                          <span className="djp-name-text">{name}</span>
                          {selectedJPName === name && resolvedJPId && (
                            <span className="djp-resolved-badge">ID: {resolvedJPId.slice(-8)}</span>
                          )}
                          {selectedJPName === name && resolving && (
                            <span className="djp-resolving-text">resolving...</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="djp-clone-config">
                  <h4 className="djp-list-heading" style={{ marginTop: '20px', marginBottom: '12px' }}>
                    Test set for cloned job profile
                  </h4>
                  <div className="djp-ts-mode-row" role="radiogroup" aria-label="Test set for cloned job profile">
                    <label className="djp-ts-mode-option">
                      <input
                        type="radio"
                        name="djp-ts-mode"
                        checked={!reuseSourceTS}
                        onChange={() => {
                          setReuseSourceTS(false);
                          if (newTestSetNameWhenNewMode.current) {
                            setCustomTSName(newTestSetNameWhenNewMode.current);
                          }
                        }}
                      />
                      <span>
                        <strong>New Testset</strong> — contains only the testcase above, copies <code>test_args</code> /{' '}
                        <code>framework_args</code>
                      </span>
                    </label>
                    <label className="djp-ts-mode-option">
                      <input
                        type="radio"
                        name="djp-ts-mode"
                        checked={reuseSourceTS}
                        onChange={() => {
                          newTestSetNameWhenNewMode.current = customTSName;
                          setReuseSourceTS(true);
                        }}
                      />
                      <span>
                        <strong>Use Existing Testset</strong> — no clone; new job profile uses that test set. pick a
                        test set below, or clear ts selection to use the source job profile’s first test set
                      </span>
                    </label>
                  </div>
                  <h4 className="djp-list-heading" style={{ marginTop: '8px', marginBottom: '12px' }}>
                    {reuseSourceTS ? 'New job profile name' : 'New JP & TS names'}
                  </h4>
                  {reuseSourceTS ? (
                    <div className="djp-form-group" style={{ maxWidth: '520px' }}>
                      <label>New job profile name</label>
                      <input
                        type="text"
                        value={customJPName}
                        onChange={(e) => setCustomJPName(e.target.value)}
                        placeholder="e.g., SW_2005_P1"
                      />
                      {selectedJPName && (
                        <small>Cloning <strong>JP</strong></small>
                      )}
                      {selectedTestSetName && (
                        <small style={{ display: 'block', marginTop: '6px' }}>
                          Test set linked to the new JP
                        </small>
                      )}
                    </div>
                  ) : (
                    <div className="djp-name-editor-row">
                      <div className="djp-form-group" style={{ flex: 1 }}>
                        <label>New TestSet</label>
                        <input
                          type="text"
                          value={customTSName}
                          onChange={(e) => setCustomTSName(e.target.value)}
                          placeholder="e.g., SW_2005_P1"
                        />
                        {selectedTestSetName && (
                          <small>Cloning <strong>TS</strong></small>
                        )}
                      </div>
                      <div className="djp-form-group" style={{ flex: 1 }}>
                        <label>New Job Profile</label>
                        <input
                          type="text"
                          value={customJPName}
                          onChange={(e) => setCustomJPName(e.target.value)}
                          placeholder="e.g., SW_2005_P1"
                        />
                        {selectedJPName && (
                          <small>Cloning <strong>JP</strong></small>
                        )}
                      </div>
                    </div>
                  )}
                  {renderTagsAndPatchSection()}
                </div>

                <div className="djp-form-actions">
                  <button
                    className="djp-btn djp-btn-success djp-btn-lg"
                    onClick={handleCreate}
                    disabled={loading || !selectedJP || resolving}
                  >
                    {loading ? 'Cloning...' : 'Clone & Create'}
                  </button>
                  {!selectedJP && (
                    <small style={{ color: '#e74c3c', marginLeft: '12px', alignSelf: 'center' }}>
                      select a source job profile
                    </small>
                  )}
                </div>
                {renderErrorMsg()}
                {renderResultBox('Profile Cloned Successfully')}
              </>
            )}
          </div>
        );
      })()}

      {/* Fresh create: info banner */}
      {!showExisting && readyToConfigure && (
        <div className="djp-section">
          <div className="djp-info-banner info">
            <strong>Direct Create Mode</strong> — A new test set and job profile will be created
            {parseTestcaseNames().length > 0
              ? (
                <>
                  {' '}containing <strong>{parseTestcaseNames().length}</strong> testcase{parseTestcaseNames().length !== 1 ? 's' : ''}.
                </>
                )
              : ' — add testcases above, or use Add Tags below if you need JP tags.'}
          </div>
        </div>
      )}

      {/* Fresh create: configuration */}
      {readyToConfigure && !showExisting && (
        <div className="djp-section">
          <div className="djp-section-title-row">
            <h3 className="djp-section-title">Step 2: Configuration</h3>
            <button
              className="djp-btn djp-btn-latest"
              onClick={handleApplyLatest}
              title={`Auto-fill: Latest Smoke Passed on ${branch}, nutest ${branch}, global_nested_2.0`}
            >
              Latest
            </button>
          </div>

          <div className="djp-clone-config" style={{ marginBottom: '16px' }}>
            <h4 className="djp-list-heading" style={{ marginBottom: '12px' }}>
              New JP &amp; TS Names
            </h4>
            <div className="djp-name-editor-row">
              <div className="djp-form-group" style={{ flex: 1 }}>
                <label>Job Profile Name</label>
                <input
                  type="text"
                  value={customJPName}
                  onChange={(e) => setCustomJPName(e.target.value)}
                  placeholder="e.g., SW_2005_P1"
                />
              </div>
              <div className="djp-form-group" style={{ flex: 1 }}>
                <label>Test Set Name</label>
                <input
                  type="text"
                  value={customTSName}
                  onChange={(e) => setCustomTSName(e.target.value)}
                  placeholder="e.g., SW_2005_P1"
                />
              </div>
            </div>
            {renderTagsAndPatchSection()}
          </div>

          <div className="djp-config-panel">
            <div className="djp-config-card">
              <h4>Provider</h4>
              <div className="djp-form-group">
                <label>Type</label>
                <select
                  value={config.provider}
                  onChange={(e) => setConfig({ ...config, provider: e.target.value, nodePool: [] })}
                >
                  <option value="global_pool">Global Pool</option>
                  <option value="node_pool">Private Node Pool</option>
                  <option value="static">Static Resources</option>
                </select>
              </div>

              {config.provider === 'global_pool' && (
                <div className="djp-form-group">
                  <label>Resource Type</label>
                  <select
                    value={config.resourceType}
                    onChange={(e) => setConfig({ ...config, resourceType: e.target.value })}
                  >
                    {RESOURCE_TYPE_OPTIONS.map((opt) => (
                      <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                  </select>
                </div>
              )}

              {config.provider === 'node_pool' && (
                <>
                  <div className="djp-form-group">
                    <label>Search Node Pool</label>
                    <input
                      type="text"
                      value={nodePoolSearch}
                      onChange={(e) => handleSearchNodePools(e.target.value)}
                      placeholder="Type to search (e.g., Regression_CDP)"
                    />
                    {nodePoolLoading && <small style={{ color: '#7f8c8d' }}>Searching...</small>}
                  </div>
                  {nodePoolSearch.length >= 2 && !nodePoolLoading && nodePoolResults.length === 0 && (
                    <small style={{ color: '#e74c3c' }}>No node pools matching "{nodePoolSearch}"</small>
                  )}
                  {nodePoolResults.length > 0 && (
                    <div className="djp-pool-results">
                      {nodePoolResults.map((pool, idx) => {
                        const alreadySelected = config.nodePool.includes(pool);
                        return (
                          <div
                            key={idx}
                            className={`djp-pool-item ${alreadySelected ? 'selected' : ''}`}
                            onClick={() => {
                              if (!alreadySelected) setConfig({ ...config, nodePool: [...config.nodePool, pool] });
                              setNodePoolSearch('');
                              setNodePoolResults([]);
                            }}
                          >
                            {pool}
                            {alreadySelected && <span style={{ marginLeft: '8px', color: '#27ae60', fontSize: '12px' }}>selected</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {config.nodePool.length > 0 && (
                    <div className="djp-tag-chips" style={{ marginTop: '8px' }}>
                      {config.nodePool.map((pool) => (
                        <span key={pool} className="djp-node-pool-chip">
                          {pool}
                          <button
                            onClick={() => setConfig({ ...config, nodePool: config.nodePool.filter(p => p !== pool) })}
                            title="Remove"
                          >
                            &times;
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                  <div className="djp-form-group" style={{ marginTop: '8px' }}>
                    <label>Resource Type</label>
                    <select
                      value={config.resourceType}
                      onChange={(e) => setConfig({ ...config, resourceType: e.target.value })}
                    >
                      {RESOURCE_TYPE_OPTIONS.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                  </div>
                </>
              )}

              {config.provider === 'static' && (
                <>
                  <div className="djp-form-group">
                    <label>Search Cluster / IP</label>
                    <input
                      type="text"
                      value={clusterSearch}
                      onChange={(e) => handleSearchClusters(e.target.value)}
                      placeholder="Type cluster name or IP (e.g., 10.124.83.160)"
                    />
                    {clusterLoading && <small style={{ color: '#7f8c8d' }}>Searching...</small>}
                  </div>
                  {clusterSearch.length >= 2 && !clusterLoading && clusterResults.length === 0 && (
                    <small style={{ color: '#e74c3c' }}>No clusters matching "{clusterSearch}"</small>
                  )}
                  {clusterResults.length > 0 && (
                    <div className="djp-pool-results">
                      {clusterResults.map((cluster, idx) => {
                        const alreadySelected = config.nodePool.includes(cluster.name);
                        return (
                          <div
                            key={idx}
                            className={`djp-pool-item ${alreadySelected ? 'selected' : ''}`}
                            onClick={() => {
                              if (!alreadySelected) setConfig({ ...config, nodePool: [...config.nodePool, cluster.name] });
                              setClusterSearch('');
                              setClusterResults([]);
                            }}
                          >
                            <span style={{ fontWeight: 500 }}>{cluster.name}</span>
                            {cluster.status && (
                              <span style={{
                                marginLeft: '8px', fontSize: '11px', padding: '1px 6px', borderRadius: '8px',
                                background: cluster.status === 'free' ? '#e8f8f0' : '#fef3e5',
                                color: cluster.status === 'free' ? '#27ae60' : '#e67e22',
                              }}>
                                {cluster.status}
                              </span>
                            )}
                            {alreadySelected && <span style={{ marginLeft: '8px', color: '#27ae60', fontSize: '12px' }}>selected</span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  {config.nodePool.length > 0 && (
                    <div className="djp-tag-chips" style={{ marginTop: '8px' }}>
                      {config.nodePool.map((name) => (
                        <span key={name} className="djp-node-pool-chip">
                          {name}
                          <button
                            onClick={() => setConfig({ ...config, nodePool: config.nodePool.filter(p => p !== name) })}
                            title="Remove"
                          >
                            &times;
                          </button>
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            <div className="djp-config-card">
              <h4>NOS_CLUSTER</h4>
              <div className="djp-form-group">
                <label>Branch</label>
                <input type="text" value={config.nosBranch} onChange={(e) => setConfig({ ...config, nosBranch: e.target.value })} placeholder="e.g., master" />
              </div>
              <div className="djp-form-group">
                <label>Release Type</label>
                <span className={`djp-release-badge ${getReleaseType(config.nosBranch)}`}>{getReleaseType(config.nosBranch)}</span>
              </div>
              <div className="djp-form-group">
                <label>Tag</label>
                <select value={config.nosTag} onChange={(e) => setConfig({ ...config, nosTag: e.target.value })}>
                  <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                  <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                </select>
              </div>
            </div>

            <div className="djp-config-card">
              <h4>PRISM_CENTRAL</h4>
              <div className="djp-form-group">
                <label>Branch</label>
                <input type="text" value={config.pcBranch} onChange={(e) => setConfig({ ...config, pcBranch: e.target.value })} placeholder="e.g., master" />
              </div>
              <div className="djp-form-group">
                <label>Release Type</label>
                <span className={`djp-release-badge ${getReleaseType(config.pcBranch)}`}>{getReleaseType(config.pcBranch)}</span>
              </div>
              <div className="djp-form-group">
                <label>Tag</label>
                <select value={config.pcTag} onChange={(e) => setConfig({ ...config, pcTag: e.target.value })}>
                  <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                  <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                </select>
              </div>
            </div>

            <div className="djp-config-card">
              <h4>Nutest</h4>
              <div className="djp-form-group">
                <label>Branch</label>
                <input type="text" value={config.nutestBranch} onChange={(e) => setConfig({ ...config, nutestBranch: e.target.value })} placeholder="e.g., master" />
              </div>
            </div>
          </div>

          <div className="djp-form-actions">
            <button
              className="djp-btn djp-btn-success djp-btn-lg"
              onClick={handleCreate}
              disabled={loading}
            >
              {loading ? 'Creating...' : 'Create Job Profile'}
            </button>
          </div>
          {renderErrorMsg()}
          {renderResultBox('Profile Created Successfully')}
        </div>
      )}
      </>
      )}
    </div>
  );
}
