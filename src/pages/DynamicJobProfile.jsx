import React, { useState, useRef, useCallback, useEffect } from 'react';
import api from '../api';
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
  nosUpdateType: 'by_tag',
  nosCommitId: '',
  nosGbn: '',
  pcBranch: derivePcBranch(branchName),
  pcTag: 'Latest Smoke Passed',
  pcUpdateType: 'by_tag',
  pcCommitId: '',
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
  const [creating, setCreating] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);
  const [showExisting, setShowExisting] = useState(false);
  const [testcaseInput, setTestcaseInput] = useState('');
  const [branch, setBranch] = useState('master');

  // Search results (showExisting mode)
  const [execHistoryFetched, setExecHistoryFetched] = useState(false);
  const [uniquePairs, setUniquePairs] = useState([]);
  const historySearchReqId = useRef(0);

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
  /** Clone mode only: use latest commit configuration (Latest Smoke Passed + auto build type). Default OFF to preserve source JP config. */
  const [useLatestCommit, setUseLatestCommit] = useState(false);
  /** Keeps the last "New test set" name if user toggles to use existing (field hidden) and back. */
  const newTestSetNameWhenNewMode = useRef('');

  // Tag support
  const [showTagInput, setShowTagInput] = useState(false);
  const [tagInput, setTagInput] = useState('');
  const [jpTags, setJpTags] = useState([]);
  const [syncToTcms, setSyncToTcms] = useState(false);

  // Test Arguments
  const [showTestArgs, setShowTestArgs] = useState(false);
  const [testArgs, setTestArgs] = useState([{ key: '', value: '' }]);
  const [frameworkOptions, setFrameworkOptions] = useState([{ key: '', value: '' }]);

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

  const clearPatchUrls = () => {
    setConfig((prev) => ({
      ...prev,
      frameworkPatchUrl: '',
      testPatchUrl: '',
    }));
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
    setSyncToTcms(false);
    setReuseSourceTS(false);
    setRetainSetupOnFailure(false);
    setShowTestArgs(false);
    setTestArgs([{ key: '', value: '' }]);
    setFrameworkOptions([{ key: '', value: '' }]);
  };

  const fetchNextNumbers = async ({ jpName = '', tsName = '' } = {}) => {
    const dynNameDate = formatLocalYyyymmdd();
    const userPrefix = `${userInitials(user)}_${formatLocalDdmm()}_P`;
    const fallbackJpPrefix = userPrefix;
    const fallbackTsPrefix = userPrefix;
    const jpSuffix = meaningfulNameSuffix(jpName);
    const tsSuffix = meaningfulNameSuffix(tsName);
    try {
      const response = await api.post(`${API_BASE}/check-existing`, {
        dyn_name_date: dynNameDate,
        jp_pattern: fallbackJpPrefix,
        ts_pattern: fallbackTsPrefix,
        jp_suffix: jpSuffix,
        ts_suffix: tsSuffix,
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
    // For JP: Check if source name has _P{number} pattern and increment it directly
    if (jpName) {
      const jpPNumberMatch = String(jpName).match(/^(.+)(_P)(\d+)(.*)$/);
      if (jpPNumberMatch) {
        // Source has _P{number} pattern - increment the number in place
        const [, beforeP, pMarker, oldNum, afterP] = jpPNumberMatch;
        const newNum = d.jpNum;
        setCustomJPName(formatPatchTestName(`${beforeP}${pMarker}${newNum}${afterP}`, showPatch));
      } else {
        // No _P{number} pattern - use normal suffix logic
        const jpSuffix = meaningfulNameSuffix(jpName);
        if (jpSuffix) {
          setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP', jpSuffix), showPatch));
        } else {
          setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP'), showPatch));
        }
      }
    } else {
      setCustomJPName(formatPatchTestName(buildSuggestedEntityName(d.jpPrefix, d.jpNum, 'JP'), showPatch));
    }

    // For TS: Check if source name has _P{number} pattern and increment it directly
    if (tsName) {
      const tsPNumberMatch = String(tsName).match(/^(.+)(_P)(\d+)(.*)$/);
      if (tsPNumberMatch) {
        // Source has _P{number} pattern - increment the number in place
        const [, beforeP, pMarker, oldNum, afterP] = tsPNumberMatch;
        const newNum = d.tsNum;
        setCustomTSName(formatPatchTestName(`${beforeP}${pMarker}${newNum}${afterP}`, showPatch));
      } else {
        // No _P{number} pattern - use normal suffix logic
        const tsSuffix = meaningfulNameSuffix(tsName);
        if (tsSuffix) {
          setCustomTSName(formatPatchTestName(buildSuggestedEntityName(d.tsPrefix, d.tsNum, 'TS', tsSuffix), showPatch));
        } else {
          setCustomTSName(formatPatchTestName(buildSuggestedEntityName(d.tsPrefix, d.tsNum, 'TS'), showPatch));
        }
      }
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
        api.post(`${API_BASE}/resolve-names`, { jp_name: jpName }),
        fetchNextNumbers({ jpName, tsName }),
      ]);
      if (resp.data?.jp?._id) {
        setSelectedJP(resp.data.jp._id);
        setResolvedJPId(resp.data.jp._id);
        applyNamesFromCheckData(d, jpName, tsName);
        setShowTagInput(false);
      } else {
        setSelectedJP(null);
        setErrorMsg(`Could not resolve job profile "${jpName}" to an ID. It may not exist in JITA.`);
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
        api.post(`${API_BASE}/resolve-names`, { ts_name: tsName }),
        fetchNextNumbers({ jpName, tsName }),
      ]);
      if (resp.data?.ts?._id) {
        setResolvedTSId(resp.data.ts._id);
        setTestSetDetails(resp.data.ts);
        applyNamesFromCheckData(d, jpName, tsName);
      } else {
        setErrorMsg(`Could not resolve test set "${tsName}" to an ID. It may not exist in JITA.`);
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
    const reqId = ++historySearchReqId.current;
    const names = parseTestcaseNames();
    if (names.length === 0 && showExisting) {
      setErrorMsg('Please enter at least one testcase name.');
      return;
    }

    setCreateResult(null);
    setErrorMsg(null);
    clearPatchUrls();
    setSyncToTcms(false);

    if (showExisting) {
      setLoading(true);
      setExecHistoryFetched(false);
      setUniquePairs([]);
      resetSelections();
      try {
        const [histResp, numData] = await Promise.all([
          api.post(`${API_BASE}/test-execution-history`, {
            test_name: names[0],
            page: 1,
            limit: 200,
            sort: '-start_time',
            branch: branch || '',
          }),
          fetchNextNumbers(),
        ]);
        if (reqId !== historySearchReqId.current) return;
        const data = histResp.data || {};
        const pairRows = Array.isArray(data.unique_pairs) ? data.unique_pairs : [];
        setUniquePairs(pairRows);
        setExecHistoryFetched(true);
        const num = Math.max(numData.jpNum, numData.tsNum);
        setCustomJPName(formatPatchTestName(buildSuggestedEntityName(numData.jpPrefix, num, 'JP'), showPatch));
        setCustomTSName(formatPatchTestName(buildSuggestedEntityName(numData.tsPrefix, num, 'TS'), showPatch));
        setReadyToConfigure(true);
        setLoading(false);

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
        if (reqId !== historySearchReqId.current) return;
        console.error('Error fetching execution history:', error);
        setErrorMsg(`Failed to fetch test history: ${getErrorMessage(error)}`);
      } finally {
        if (reqId === historySearchReqId.current) setLoading(false);
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
        const response = await api.post(`${API_BASE}/search-node-pools`, { query });
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
        const response = await api.post(`${API_BASE}/search-clusters`, { query });
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
        const response = await api.post(`${API_BASE}/search-branches`, { query });
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
      setErrorMsg('Please enter at least one testcase name, or enable "Use Existing Test Set" in clone mode.');
      return;
    }
    if (showExisting && !selectedJP) {
      setErrorMsg('Please select a source job profile from the list.');
      return;
    }

    setLoading(true);
    setCreating(true);
    setCreateResult(null);
    setCreateResultCopyFlash(null);
    if (createResultCopyTimerRef.current) {
      clearTimeout(createResultCopyTimerRef.current);
      createResultCopyTimerRef.current = null;
    }
    setErrorMsg(null);
    try {
      const allTags = [...new Set(jpTags)];

      // When "Use Latest Commit" is ON, override config to use Latest Smoke Passed (both fresh create and clone)
      // Preserve user's provider and resourceType selection
      const effectiveConfig = useLatestCommit ? {
        ...config,
        nosTag: 'Latest Smoke Passed',
        pcTag: 'Latest Smoke Passed',
        provider: config.provider || 'global_pool',
        resourceType: config.resourceType || 'nested_2.0',
      } : config;

      // Build test args and framework options from key-value pairs
      const customTestArgs = showTestArgs 
        ? testArgs.filter(pair => pair.key.trim()).reduce((acc, pair) => {
            acc[pair.key.trim()] = pair.value;
            return acc;
          }, {})
        : {};
      
      const customFrameworkOptions = showTestArgs
        ? frameworkOptions.filter(pair => pair.key.trim()).reduce((acc, pair) => {
            acc[pair.key.trim()] = pair.value;
            return acc;
          }, {})
        : {};

      // Log custom args for debugging
      if (Object.keys(customTestArgs).length > 0) {
        console.log('[DynamicJobProfile] Sending custom_test_args:', customTestArgs);
      }
      if (Object.keys(customFrameworkOptions).length > 0) {
        console.log('[DynamicJobProfile] Sending custom_framework_options:', customFrameworkOptions);
      }

      const response = await api.post(`${API_BASE}/create`, {
        source_jp_id: showExisting ? selectedJP : null,
        source_testset_id: showExisting ? (resolvedTSId || testSetDetails?._id || null) : null,
        source_testset_name: showExisting ? (selectedTestSetName || null) : null,
        nos_branch: effectiveConfig.nosBranch || 'master',
        nos_tag: effectiveConfig.nosTag || 'Latest Smoke Passed',
        nos_update_type: effectiveConfig.nosUpdateType || 'by_tag',
        nos_commit_id: effectiveConfig.nosCommitId || '',
        nos_gbn: effectiveConfig.nosGbn || '',
        pc_branch: effectiveConfig.pcBranch || 'master',
        pc_tag: effectiveConfig.pcTag || 'Latest Smoke Passed',
        pc_update_type: effectiveConfig.pcUpdateType || 'by_tag',
        pc_commit_id: effectiveConfig.pcCommitId || '',
        nutest_branch: effectiveConfig.nutestBranch || 'master',
        provider: effectiveConfig.provider || 'global_pool',
        resource_type: effectiveConfig.resourceType || 'nested_2.0',
        node_pool: Array.isArray(effectiveConfig.nodePool) ? effectiveConfig.nodePool : [],
        framework_patch_url: showPatch ? (effectiveConfig.frameworkPatchUrl || '') : '',
        test_patch_url: showPatch ? (effectiveConfig.testPatchUrl || '') : '',
        testcase_names: names,
        create_fresh: !showExisting,
        custom_jp_name: customJPName || null,
        custom_ts_name: customTSName || null,
        dyn_name_date: formatLocalYyyymmdd(),
        jp_tags: allTags.length > 0 ? allTags : [],
        sync_to_tcms: syncToTcms,
        reuse_source_ts: !!(showExisting && reuseSourceTS),
        retain_setup_on_failure: !!retainSetupOnFailure,
        use_latest_commit: !!useLatestCommit,
        custom_test_args: Object.keys(customTestArgs).length > 0 ? customTestArgs : null,
        custom_framework_options: Object.keys(customFrameworkOptions).length > 0 ? customFrameworkOptions : null,
      });
      if (response.data?.success) {
        setCreateResult(response.data);
        clearPatchUrls();
        setShowPatch(false);
        setSyncToTcms(false);
        setShowTestArgs(false);
        setTestArgs([{ key: '', value: '' }]);
        setFrameworkOptions([{ key: '', value: '' }]);
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
      setCreating(false);
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
      <div className="djp-tag-patch-toggles djp-toggles-compact" role="group" aria-label="Options">
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Latest</label>
          <div
            className={`djp-toggle djp-toggle--sm ${useLatestCommit ? 'active' : ''}`}
            onClick={() => setUseLatestCommit(!useLatestCommit)}
            role="switch"
            aria-checked={useLatestCommit}
            title="Auto-select Latest Smoke Passed"
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Test Args</label>
          <div
            className={`djp-toggle djp-toggle--sm ${showTestArgs ? 'active' : ''}`}
            onClick={() => setShowTestArgs(!showTestArgs)}
            role="switch"
            aria-checked={showTestArgs}
            title="Add custom test arguments"
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Patch</label>
          <div
            className={`djp-toggle djp-toggle--sm ${showPatch ? 'active' : ''}`}
            onClick={() => setShowPatch(!showPatch)}
            role="switch"
            aria-checked={showPatch}
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Add Tags</label>
          <div
            className={`djp-toggle djp-toggle--sm ${showTagInput ? 'active' : ''}`}
            onClick={() => setShowTagInput(!showTagInput)}
            role="switch"
            aria-checked={showTagInput}
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Retain Setup</label>
          <div
            className={`djp-toggle djp-toggle--sm ${retainSetupOnFailure ? 'active' : ''}`}
            onClick={() => setRetainSetupOnFailure(!retainSetupOnFailure)}
            role="switch"
            aria-checked={retainSetupOnFailure}
            title="Retain live deployments on failure"
          >
            <div className="djp-toggle-knob" />
          </div>
        </div>
        <div className="djp-toggle-row djp-toggle-row--sm">
          <label>Sync TCMS</label>
          <div
            className={`djp-toggle djp-toggle--sm ${syncToTcms ? 'active' : ''}`}
            onClick={() => setSyncToTcms(!syncToTcms)}
            role="switch"
            aria-checked={syncToTcms}
            title="Enable JITA Sync to TCMS"
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
          <small className="djp-section-note">Tags will be added to the job profile's advanced options.</small>
        </div>
      )}
      {showPatch && (
        <div className="djp-patch-fields djp-tag-patch-expand">
          <div className="djp-form-group">
            <label>Framework patch URL</label>
            <input
              type="text"
              value={config.frameworkPatchUrl}
              onChange={(e) => setConfig({ ...config, frameworkPatchUrl: e.target.value })}
              placeholder="https://nugerrit.ntnxdpro.com/changes/nutest-py3~.../patch?zip"
            />
          </div>
          <div className="djp-form-group">
            <label>NuTest Py3 tests patch URL</label>
            <input
              type="text"
              value={config.testPatchUrl}
              onChange={(e) => setConfig({ ...config, testPatchUrl: e.target.value })}
              placeholder="https://nugerrit.ntnxdpro.com/changes/nutest-py3-tests~.../patch?zip"
            />
          </div>
        </div>
      )}
      {showTestArgs && (
        <div className="djp-test-args-fields djp-tag-patch-expand">
          <div className="djp-test-args-section">
            <h4>Test Arguments</h4>
            {testArgs.map((pair, idx) => (
              <div key={idx} className="djp-kv-row">
                <input
                  type="text"
                  value={pair.key}
                  onChange={(e) => {
                    const updated = [...testArgs];
                    updated[idx].key = e.target.value;
                    setTestArgs(updated);
                  }}
                  placeholder="Key"
                />
                <input
                  type="text"
                  value={pair.value}
                  onChange={(e) => {
                    const updated = [...testArgs];
                    updated[idx].value = e.target.value;
                    setTestArgs(updated);
                  }}
                  placeholder="Value"
                />
                <button
                  className="djp-btn djp-btn-sm"
                  onClick={() => {
                    if (testArgs.length > 1) {
                      setTestArgs(testArgs.filter((_, i) => i !== idx));
                    }
                  }}
                  disabled={testArgs.length === 1}
                  title="Remove"
                >
                  &times;
                </button>
              </div>
            ))}
            <button
              className="djp-btn djp-btn-primary djp-btn-sm"
              onClick={() => setTestArgs([...testArgs, { key: '', value: '' }])}
            >
              + Add Test Arg
            </button>
          </div>
          <div className="djp-test-args-section">
            <h4>Framework Options</h4>
            {frameworkOptions.map((pair, idx) => (
              <div key={idx} className="djp-kv-row">
                <input
                  type="text"
                  value={pair.key}
                  onChange={(e) => {
                    const updated = [...frameworkOptions];
                    updated[idx].key = e.target.value;
                    setFrameworkOptions(updated);
                  }}
                  placeholder="Key"
                />
                <input
                  type="text"
                  value={pair.value}
                  onChange={(e) => {
                    const updated = [...frameworkOptions];
                    updated[idx].value = e.target.value;
                    setFrameworkOptions(updated);
                  }}
                  placeholder="Value"
                />
                <button
                  className="djp-btn djp-btn-sm"
                  onClick={() => {
                    if (frameworkOptions.length > 1) {
                      setFrameworkOptions(frameworkOptions.filter((_, i) => i !== idx));
                    }
                  }}
                  disabled={frameworkOptions.length === 1}
                  title="Remove"
                >
                  &times;
                </button>
              </div>
            ))}
            <button
              className="djp-btn djp-btn-primary djp-btn-sm"
              onClick={() => setFrameworkOptions([...frameworkOptions, { key: '', value: '' }])}
            >
              + Add Framework Option
            </button>
          </div>
          <small className="djp-section-note">Custom arguments will be merged with default test set configuration.</small>
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

      {/* Testcase input, branch, and mode selection */}
      <div className="djp-section djp-step1-section">
        <h3 className="djp-section-title">Testcase names</h3>
        <div className="djp-form-group">
          <textarea
            value={testcaseInput}
            onChange={(e) => setTestcaseInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter' || e.shiftKey) return;
              e.preventDefault();
              if (loading) return;
              handleSearch();
            }}
            placeholder="Testcase names separated by commas, spaces, or newlines"
            rows={4}
          />
        </div>

        <div className="djp-search-row">
          <div className="djp-form-group djp-branch-field">
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
            {branchLoading && <small className="djp-field-status">Searching...</small>}
            {branchResults.length > 0 && (
              <div className="djp-pool-results djp-branch-results">
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
            <label className="djp-toggle-label">Show existing</label>
            <div
              className={`djp-toggle ${showExisting ? 'active' : ''}`}
              onClick={() => {
                historySearchReqId.current += 1;
                setLoading(false);
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
          </div>

          <div className="djp-search-action" style={{ marginLeft: 'auto' }}>
            <button
              className="djp-btn djp-btn-primary"
              onClick={handleSearch}
              disabled={loading}
            >
              {loading ? 'Searching...' : showExisting ? 'Search' : 'Continue'}
            </button>
          </div>
        </div>
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
                <div className="djp-section-title-row djp-section-title-row--compact">
                  <h3 className="djp-section-title">Source JP &amp; TS</h3>
                  {(selectedJPName || selectedTestSetName || resolvedJPId || resolvedTSId) && (
                    <button
                      type="button"
                      className="djp-btn djp-btn-secondary djp-btn-sm"
                      onClick={clearJPAndTSSelection}
                    >
                      Clear
                    </button>
                  )}
                </div>
                <div className="djp-unique-lists">
                  <div className="djp-unique-list-col">
                    <div className="djp-list-heading-row">
                      <h4 className="djp-list-heading">
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
                            <span className="djp-resolving-text">Resolving...</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div className="djp-unique-list-col">
                    <div className="djp-list-heading-row">
                      <h4 className="djp-list-heading">
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
                            <span className="djp-resolving-text">Resolving...</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                <div className="djp-clone-config">
                  <div className="djp-ts-mode-row" role="radiogroup" aria-label="Test set mode">
                    <label className={`djp-ts-mode-option ${!reuseSourceTS ? 'selected' : ''}`}>
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
                        <strong>New Test Set</strong>
                      </span>
                    </label>
                    <label className={`djp-ts-mode-option ${reuseSourceTS ? 'selected' : ''}`}>
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
                        <strong>Use Existing Test Set</strong>
                      </span>
                    </label>
                  </div>
                  {reuseSourceTS ? (
                    <div className="djp-form-group djp-single-name-field">
                      <label>New JP</label>
                      <input
                        type="text"
                        value={customJPName}
                        onChange={(e) => setCustomJPName(e.target.value)}
                        placeholder="e.g., SW_2005_P1"
                      />
                    </div>
                  ) : (
                    <div className="djp-name-editor-row">
                      <div className="djp-form-group djp-flex-field">
                      <label>New Test Set</label>
                        <input
                          type="text"
                          value={customTSName}
                          onChange={(e) => setCustomTSName(e.target.value)}
                          placeholder="e.g., SW_2005_P1"
                        />
                      </div>
                      <div className="djp-form-group djp-flex-field">
                        <label>New Job Profile</label>
                        <input
                          type="text"
                          value={customJPName}
                          onChange={(e) => setCustomJPName(e.target.value)}
                          placeholder="e.g., SW_2005_P1"
                        />
                      </div>
                    </div>
                  )}
                  {renderTagsAndPatchSection()}
                </div>

                <div className="djp-form-actions">
                  <button
                    className="djp-btn djp-btn-success djp-btn-lg"
                    onClick={handleCreate}
                    disabled={creating || loading || !selectedJP || resolving}
                  >
                    {creating ? 'Creating...' : 'Clone and create'}
                  </button>
                  {!selectedJP && (
                    <small className="djp-action-hint djp-action-hint-error">
                      Select a source JP.
                    </small>
                  )}
                </div>
                {renderErrorMsg()}
                {renderResultBox('Profile cloned successfully')}
              </>
            )}
          </div>
        );
      })()}

      {/* Configuration: shown only in fresh create mode */}
      {readyToConfigure && !showExisting && (
        <div className="djp-section">
          <h3 className="djp-section-title">Configuration</h3>

          <div className="djp-clone-config djp-name-panel">
            <h4 className="djp-list-heading">
              New Job Profile and Test Set Names
            </h4>
            <div className="djp-name-editor-row">
              <div className="djp-form-group djp-flex-field">
                <label>Job Profile Name</label>
                <input
                  type="text"
                  value={customJPName}
                  onChange={(e) => setCustomJPName(e.target.value)}
                  placeholder="e.g., SW_2005_P1"
                />
              </div>
              <div className="djp-form-group djp-flex-field">
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
                    <small style={{ color: '#e74c3c' }}>No node pools match "{nodePoolSearch}".</small>
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
                            {alreadySelected && <span style={{ marginLeft: '8px', color: '#27ae60', fontSize: '12px' }}>Selected</span>}
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
                    <small style={{ color: '#e74c3c' }}>No clusters match "{clusterSearch}".</small>
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
                            {alreadySelected && <span style={{ marginLeft: '8px', color: '#27ae60', fontSize: '12px' }}>Selected</span>}
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
              <h4>NOS Cluster</h4>
              <div className="djp-form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                  <label style={{ marginBottom: 0 }}>Branch</label>
                  <span className={`djp-release-badge ${getReleaseType(config.nosBranch)}`} style={{ fontSize: '12px', padding: '2px 6px', fontWeight: 'bold', borderRadius: '4px' }}>
                    {getReleaseType(config.nosBranch).toUpperCase()}
                  </span>
                </div>
                <input 
                  type="text" 
                  value={config.nosBranch} 
                  onChange={(e) => setConfig({ ...config, nosBranch: e.target.value })} 
                  placeholder="e.g., ganges-7.3-stable" 
                />
              </div>
              
              <div className="djp-form-group">
                <label>Update Type</label>
                <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.5rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 'normal' }}>
                    <input
                      type="radio"
                      name="nosUpdateType"
                      value="by_tag"
                      checked={config.nosUpdateType === 'by_tag'}
                      onChange={(e) => setConfig({ ...config, nosUpdateType: e.target.value })}
                    />
                    By Tag
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 'normal' }}>
                    <input
                      type="radio"
                      name="nosUpdateType"
                      value="by_commit"
                      checked={config.nosUpdateType === 'by_commit'}
                      onChange={(e) => setConfig({ ...config, nosUpdateType: e.target.value })}
                    />
                    By Commit
                  </label>
                </div>
              </div>

              {config.nosUpdateType === 'by_tag' ? (
                <div className="djp-form-group">
                  <label>Tag</label>
                  <select value={config.nosTag} onChange={(e) => setConfig({ ...config, nosTag: e.target.value })}>
                    <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                    <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                  </select>
                </div>
              ) : (
                <>
                  <div className="djp-form-group">
                    <label>Commit ID</label>
                    <input 
                      type="text" 
                      value={config.nosCommitId} 
                      onChange={(e) => setConfig({ ...config, nosCommitId: e.target.value })} 
                      placeholder="e.g., cd8cd937b6288cf2c58a44a0bc1c58d85bf5c0bb" 
                    />
                  </div>
                  <div className="djp-form-group">
                    <label>GBN</label>
                    <input 
                      type="text" 
                      value={config.nosGbn} 
                      onChange={(e) => setConfig({ ...config, nosGbn: e.target.value })} 
                      placeholder="e.g., 1764602295" 
                    />
                  </div>
                </>
              )}
            </div>

            <div className="djp-config-card">
              <h4>Prism Central</h4>
              <div className="djp-form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                  <label style={{ marginBottom: 0 }}>Branch</label>
                  <span className={`djp-release-badge ${getReleaseType(config.pcBranch)}`} style={{ fontSize: '12px', padding: '2px 6px', fontWeight: 'bold', borderRadius: '4px' }}>
                    {getReleaseType(config.pcBranch).toUpperCase()}
                  </span>
                </div>
                <input 
                  type="text" 
                  value={config.pcBranch} 
                  onChange={(e) => setConfig({ ...config, pcBranch: e.target.value })} 
                  placeholder="e.g., master" 
                />
              </div>
              
              <div className="djp-form-group">
                <label>Update Type</label>
                <div style={{ display: 'flex', gap: '1.5rem', marginTop: '0.5rem' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 'normal' }}>
                    <input
                      type="radio"
                      name="pcUpdateType"
                      value="by_tag"
                      checked={config.pcUpdateType === 'by_tag'}
                      onChange={(e) => setConfig({ ...config, pcUpdateType: e.target.value })}
                    />
                    By Tag
                  </label>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontWeight: 'normal' }}>
                    <input
                      type="radio"
                      name="pcUpdateType"
                      value="by_commit"
                      checked={config.pcUpdateType === 'by_commit'}
                      onChange={(e) => setConfig({ ...config, pcUpdateType: e.target.value })}
                    />
                    By Commit
                  </label>
                </div>
              </div>

              {config.pcUpdateType === 'by_tag' ? (
                <div className="djp-form-group">
                  <label>Tag</label>
                  <select value={config.pcTag} onChange={(e) => setConfig({ ...config, pcTag: e.target.value })}>
                    <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                    <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                  </select>
                </div>
              ) : (
                <div className="djp-form-group">
                  <label>Commit ID</label>
                  <input 
                    type="text" 
                    value={config.pcCommitId} 
                    onChange={(e) => setConfig({ ...config, pcCommitId: e.target.value })} 
                    placeholder="e.g., cd8cd937b6288cf2c58a44a0bc1c58d85bf5c0bb" 
                  />
                </div>
              )}
            </div>

            <div className="djp-config-card">
              <h4>NuTest</h4>
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
              disabled={loading || (showExisting && (!selectedJP || resolving))}
            >
              {loading ? 'Creating...' : showExisting ? 'Clone and create' : 'Create Job Profile'}
            </button>
            {showExisting && !selectedJP && (
              <small className="djp-action-hint djp-action-hint-error">
                Select a source JP.
              </small>
            )}
          </div>
          {renderErrorMsg()}
          {renderResultBox(showExisting ? 'Profile cloned successfully' : 'Profile created successfully')}
        </div>
      )}
      </>
      )}
    </div>
  );
}
