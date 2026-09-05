import React, { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api';
import { API_BASE_URL } from '../config';
import { useTaskContext } from '../context/TaskContext';
import AiMarkdown from '../components/AiMarkdown';
import * as XLSX from 'xlsx';
import './TestcaseManagement.css';

const PAGE_SIZE_OPTIONS = [50, 100, 200, 'All'];
const DEFAULT_PAGE_SIZE = 50;

const TAG_CLASS_MAP = {
  critical: 'tag-critical',
  major: 'tag-major',
  minor: 'tag-minor',
  cdp_smart_qual: 'tag-smartqual',
  pinned: 'tag-pinned',
};

function getTagClass(tag) {
  return TAG_CLASS_MAP[tag.toLowerCase()] || 'tag-default';
}

function getPctClass(val) {
  if (val == null) return '';
  if (val >= 80) return 'pct-good';
  if (val >= 50) return 'pct-warn';
  return 'pct-bad';
}

const ALL_COLUMNS = [
  { key: 'name',              label: 'Testcase Name',     sortable: true,  defaultVisible: true  },
  { key: 'priority',          label: 'Priority',          sortable: true,  defaultVisible: true  },
  { key: 'tags',              label: 'Tags',              sortable: false, defaultVisible: true  },
  { key: 'last_status',       label: 'Status',            sortable: true,  defaultVisible: true  },
  { key: 'last_run_date',     label: 'Last Run Date',     sortable: true,  defaultVisible: true  },
  { key: 'last_passed_date',  label: 'Last Passed Date',  sortable: true,  defaultVisible: true  },
  { key: 'stability',         label: 'Stability',         sortable: true,  defaultVisible: true  },
  { key: 'effectiveness',     label: 'Effectiveness',     sortable: true,  defaultVisible: false },
  { key: 'success_percentage',label: 'Success %',         sortable: true,  defaultVisible: true  },
  { key: 'published_qi',     label: 'QI',                sortable: true,  defaultVisible: true  },
  { key: 'published_ops',    label: 'Ops',               sortable: false, defaultVisible: true  },
  { key: 'is_triaged',        label: 'Triaged',           sortable: true,  defaultVisible: true  },
  { key: 'issue_type',        label: 'Issue Type',        sortable: true,  defaultVisible: true  },
  { key: 'last_run_tickets',  label: 'Tickets',           sortable: false, defaultVisible: true  },
  { key: 'owners',            label: 'Owners',            sortable: false, defaultVisible: true  },
  { key: 'target_service',    label: 'Target Service',    sortable: true,  defaultVisible: false },
  { key: 'target',            label: 'Target',            sortable: true,  defaultVisible: false },
  { key: 'primary_component', label: 'Primary Component', sortable: true,  defaultVisible: false },
  { key: 'services',          label: 'Services',          sortable: false, defaultVisible: false },
  { key: 'components',        label: 'Components',        sortable: false, defaultVisible: false },
  { key: 'framework',         label: 'Framework',         sortable: true,  defaultVisible: false },
  { key: 'summary',           label: 'Summary',           sortable: false, defaultVisible: false },
  { key: 'path',              label: 'Path',              sortable: true,  defaultVisible: false },
  { key: 'team',              label: 'Team',              sortable: false, defaultVisible: false },
  { key: 'avg_run_duration',  label: 'Avg Duration (s)',  sortable: true,  defaultVisible: false },
  { key: 'total_results',     label: 'Total Results',     sortable: true,  defaultVisible: false },
  { key: 'automated_date',    label: 'Automated Date',    sortable: true,  defaultVisible: false },
  { key: 'one_month_mttr',    label: 'MTTR (1 mo)',       sortable: true,  defaultVisible: false },
  { key: 'three_months_mttr', label: 'MTTR (3 mo)',       sortable: true,  defaultVisible: false },
  { key: 'metadata_tags',     label: 'Metadata Tags',     sortable: false, defaultVisible: false },
];

const DEFAULT_VISIBLE = new Set(ALL_COLUMNS.filter(c => c.defaultVisible).map(c => c.key));

const CUSTOM_BRANCHES_STORAGE_KEY = 'tc-mgmt-custom-branches';

function toShortBranch(name) {
  if (name === 'master') return 'master';
  const m = name.match(/^ganges-(\d+(?:\.\d+)+)-stable$/);
  return m ? m[1] : name;
}

function loadCustomBranches() {
  try {
    const raw = localStorage.getItem(CUSTOM_BRANCHES_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function saveCustomBranches(list) {
  localStorage.setItem(CUSTOM_BRANCHES_STORAGE_KEY, JSON.stringify(list));
}

function renderCell(tc, colKey) {
  switch (colKey) {
    case 'name':
      return <div className="tc-name-cell" title={tc.name}>{tc.name}</div>;
    case 'priority':
      return tc.priority || '—';
    case 'tags':
      return (
        <div className="tc-tag-chips">
          {(tc.tags || []).map(tag => (
            <span key={tag} className={`tc-tag-chip ${getTagClass(tag)}`}>{tag}</span>
          ))}
        </div>
      );
    case 'last_status':
      return (
        <span className={`tc-status-badge status-${tc.last_status || 'unknown'}`}>
          {tc.last_status || '—'}
        </span>
      );
    case 'last_run_date':
    case 'last_passed_date':
    case 'automated_date':
      return <span className="tc-date-cell">{tc[colKey] || '—'}</span>;
    case 'stability':
    case 'effectiveness':
    case 'success_percentage':
      return (
        <span className={`tc-pct ${getPctClass(tc[colKey])}`}>
          {tc[colKey] != null ? `${tc[colKey]}%` : '—'}
        </span>
      );
    case 'published_qi':
      return (
        <span className={`tc-pct ${getPctClass(tc.published_qi)}`}>
          {tc.published_qi != null ? `${tc.published_qi}%` : '—'}
        </span>
      );
    case 'published_ops':
      return (tc.published_success_ops != null && tc.published_total_ops != null)
        ? <span className="tc-ops-cell">{tc.published_success_ops}/{tc.published_total_ops}</span>
        : '—';
    case 'is_triaged':
      return (
        <span className={`tc-triaged-badge ${tc.is_triaged ? 'triaged-yes' : 'triaged-no'}`}>
          {tc.is_triaged ? 'Yes' : 'No'}
        </span>
      );
    case 'issue_type':
      return tc.issue_type
        ? <span className={`tc-issue-type issue-${tc.issue_type}`}>{tc.issue_type}</span>
        : '—';
    case 'last_run_tickets':
      return (
        <div className="tc-tickets">
          {(tc.last_run_tickets || []).length > 0
            ? tc.last_run_tickets.map(t => <span key={t} className="tc-ticket-link">{t}</span>)
            : '—'}
        </div>
      );
    case 'owners':
      return (
        <div className="tc-owners" title={(tc.owners || []).join(', ')}>
          {(tc.owners || []).map(o => o.split('@')[0]).join(', ')}
        </div>
      );
    case 'services':
    case 'components':
    case 'team':
    case 'metadata_tags':
      return (tc[colKey] || []).join(', ') || '—';
    case 'summary':
      return <div className="tc-summary-cell" title={tc.summary}>{tc.summary || '—'}</div>;
    case 'path':
      return <div className="tc-path-cell" title={tc.path}>{tc.path || '—'}</div>;
    case 'avg_run_duration':
      return tc.avg_run_duration != null ? `${Math.round(tc.avg_run_duration)}s` : '—';
    case 'one_month_mttr':
    case 'three_months_mttr':
      return tc[colKey] != null ? `${Math.round(tc[colKey])}s` : '—';
    case 'total_results':
      return tc.total_results != null ? tc.total_results : '—';
    default:
      return tc[colKey] != null ? String(tc[colKey]) : '—';
  }
}

export default function TestcaseManagement() {
  const { addTask, updateTask } = useTaskContext();
  const [branches, setBranches] = useState([]);
  const [customBranches, setCustomBranches] = useState(loadCustomBranches);
  const [teams, setTeams] = useState([]);
  const [branch, setBranch] = useState('master');
  const [team, setTeam] = useState('CDP');
  const [showBranchDropdown, setShowBranchDropdown] = useState(false);
  const [newBranchInput, setNewBranchInput] = useState('');
  const branchDropdownRef = useRef(null);

  const [testcases, setTestcases] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [availableTags, setAvailableTags] = useState([]);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [loading, setLoading] = useState(false);
  const [reloading, setReloading] = useState(false);

  const [nameFilter, setNameFilter] = useState('');
  const [nameExactMatch, setNameExactMatch] = useState(false);
  const [tagFilter, setTagFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [lastRunDate, setLastRunDate] = useState('');
  const [lastRunDateOp, setLastRunDateOp] = useState('>=');
  const [componentFilter, setComponentFilter] = useState('');

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(DEFAULT_PAGE_SIZE);
  const [sortField, setSortField] = useState('name');
  const [sortDir, setSortDir] = useState('asc');

  const [selectedOids, setSelectedOids] = useState(new Set());
  const [tagInput, setTagInput] = useState('');
  const [tagActionLoading, setTagActionLoading] = useState(false);

  const [visibleColumns, setVisibleColumns] = useState(DEFAULT_VISIBLE);
  const [showColPicker, setShowColPicker] = useState(false);
  const colPickerRef = useRef(null);

  const [showActionsMenu, setShowActionsMenu] = useState(false);
  const actionsRef = useRef(null);
  const [showRunPlanModal, setShowRunPlanModal] = useState(false);
  const [rpName, setRpName] = useState('');
  const [jpPrefix, setJpPrefix] = useState('');
  const [resolving, setResolving] = useState(false);
  const [resolvedData, setResolvedData] = useState(null);
  const [selectedJpIds, setSelectedJpIds] = useState(new Set());
  const [showUnmatched, setShowUnmatched] = useState(false);
  const [creatingRp, setCreatingRp] = useState(false);

  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [loadingAi, setLoadingAi] = useState(false);
  const [showAiPanel, setShowAiPanel] = useState(false);

  const allBranches = React.useMemo(() => {
    const shortApi = branches.map(toShortBranch);
    const merged = [...shortApi];
    customBranches.forEach(cb => { if (!merged.includes(cb)) merged.push(cb); });
    return merged;
  }, [branches, customBranches]);

  const showToast = useCallback((msg, type = 'info') => {
    setToast({ msg, type });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  // Close column picker on outside click
  useEffect(() => {
    function handleClickOutside(e) {
      if (colPickerRef.current && !colPickerRef.current.contains(e.target)) {
        setShowColPicker(false);
      }
    }
    if (showColPicker) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showColPicker]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (actionsRef.current && !actionsRef.current.contains(e.target)) {
        setShowActionsMenu(false);
      }
    }
    if (showActionsMenu) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showActionsMenu]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (branchDropdownRef.current && !branchDropdownRef.current.contains(e.target)) {
        setShowBranchDropdown(false);
      }
    }
    if (showBranchDropdown) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showBranchDropdown]);

  const handleAddBranch = () => {
    const val = newBranchInput.trim();
    if (!val) return;
    if (allBranches.includes(val)) {
      setBranch(val);
      setNewBranchInput('');
      setShowBranchDropdown(false);
      return;
    }
    const updated = [...customBranches, val];
    setCustomBranches(updated);
    saveCustomBranches(updated);
    setBranch(val);
    setNewBranchInput('');
    setShowBranchDropdown(false);
  };

  const handleRemoveBranch = (branchToRemove) => {
    const updated = customBranches.filter(b => b !== branchToRemove);
    setCustomBranches(updated);
    saveCustomBranches(updated);
    if (branch === branchToRemove) {
      setBranch(allBranches.find(b => b !== branchToRemove) || 'master');
    }
  };

  useEffect(() => {
    api.get(`${API_BASE_URL}/mcp/regression/testcase-mgmt/branches`)
      .then(res => {
        setBranches(res.data.branches || []);
        setTeams(res.data.teams || []);
      })
      .catch(() => {
        setBranches(['master', '7.6', '7.5']);
        setTeams(['CDP', 'AHV']);
      });
  }, []);

  const fetchTestcases = useCallback(() => {
    setLoading(true);
    
    // Use POST if there's a name filter (to avoid URL length limits for large filters)
    const usePost = nameFilter && nameFilter.length > 0;
    
    if (usePost) {
      // POST method - send data in body
      const body = {
        branch,
        team,
        name: nameFilter,
        exact_match: nameExactMatch,
      };
      if (tagFilter) body.tags = tagFilter;
      if (statusFilter) body.status = statusFilter;
      
      api.post(`${API_BASE_URL}/mcp/regression/testcase-mgmt/testcases`, body)
        .then(res => {
          setTestcases(res.data.testcases || []);
          setTotalCount(res.data.total_count || 0);
          setAvailableTags(res.data.available_tags || []);
          setLastUpdated(res.data.last_updated);
          setPage(1);
          setSelectedOids(new Set());
        })
        .catch(err => {
          console.error('Failed to load testcases', err);
          showToast('Failed to load testcases', 'error');
        })
        .finally(() => setLoading(false));
    } else {
      // GET method - use query parameters for small filters
      const params = { branch, team };
      if (tagFilter) params.tags = tagFilter;
      if (statusFilter) params.status = statusFilter;
      
      api.get(`${API_BASE_URL}/mcp/regression/testcase-mgmt/testcases`, { params })
        .then(res => {
          setTestcases(res.data.testcases || []);
          setTotalCount(res.data.total_count || 0);
          setAvailableTags(res.data.available_tags || []);
          setLastUpdated(res.data.last_updated);
          setPage(1);
          setSelectedOids(new Set());
        })
        .catch(err => {
          console.error('Failed to load testcases', err);
          showToast('Failed to load testcases', 'error');
        })
        .finally(() => setLoading(false));
    }
  }, [branch, team, tagFilter, nameFilter, nameExactMatch, statusFilter, showToast]);

  useEffect(() => { fetchTestcases(); }, [fetchTestcases]);

  const handleReload = () => {
    setReloading(true);
    showToast(`Fetching test cases from TCMS for ${branch} / ${team}...`, 'info');
    const taskId = addTask({ label: `Reload TCMS: ${branch} / ${team}`, page: 'Testcase Management' });
    api.get(`${API_BASE_URL}/mcp/regression/testcase-mgmt/fetch-data`, {
      params: { branch, team },
      timeout: 300000,
    })
      .then(res => {
        const d = res.data || {};
        const tagged = d.tagged_count != null ? `, ${d.tagged_count} with tags` : '';
        const tcms = d.tcms_oid_count != null ? `, ${d.tcms_oid_count} TCMS ids` : '';
        showToast(`Loaded ${d.count || 0} test cases${tagged}${tcms}`, 'success');
        updateTask(taskId, {
          status: 'success',
          detail: `Loaded ${d.count || 0} test cases${tagged}${tcms}`,
        });
        fetchTestcases();
      })
      .catch(err => {
        console.error('Reload failed', err);
        const msg = err.response?.data?.error || err.message;
        showToast('Reload failed: ' + msg, 'error');
        updateTask(taskId, { status: 'error', detail: msg });
      })
      .finally(() => setReloading(false));
  };

  const handleDownloadResourceSpec = () => {
    showToast('Generating resource spec Excel...', 'info');
    const taskId = addTask({ label: `Download Resource Spec: ${branch} / ${team}`, page: 'Testcase Management' });
    api.get(`${API_BASE_URL}/mcp/regression/testcase-mgmt/resource-spec/download`, {
      params: { branch, team },
      responseType: 'blob',
      timeout: 60000,
    })
      .then(res => {
        const url = window.URL.createObjectURL(new Blob([res.data]));
        const link = document.createElement('a');
        link.href = url;
        link.setAttribute('download', `resource_spec_${branch}_${team}.xlsx`);
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.URL.revokeObjectURL(url);
        showToast('Resource spec downloaded', 'success');
        updateTask(taskId, { status: 'success', detail: 'Excel downloaded' });
      })
      .catch(err => {
        console.error('Download failed', err);
        const msg = err.response?.data?.error || err.message;
        showToast('Download failed: ' + msg, 'error');
        updateTask(taskId, { status: 'error', detail: msg });
      });
  };

  const handleAiAnalyse = async () => {
    if (filtered.length === 0) { showToast('No testcases to analyse', 'error'); return; }
    setLoadingAi(true);
    setAiAnalysis(null);
    setShowAiPanel(true);
    try {
      const allFailed = filtered.filter(tc => tc.last_status === 'failed');
      const allSucceeded = filtered.filter(tc => tc.last_status === 'succeeded');

      const issueTypeBreakdown = {};
      const componentBreakdown = {};
      const allTickets = [];
      allFailed.forEach(tc => {
        const it = tc.issue_type || 'Unclassified';
        issueTypeBreakdown[it] = (issueTypeBreakdown[it] || 0) + 1;
        const comp = tc.primary_component || 'Unknown';
        componentBreakdown[comp] = (componentBreakdown[comp] || 0) + 1;
        if (tc.last_run_tickets) allTickets.push(...tc.last_run_tickets);
      });

      const failedTcs = allFailed.slice(0, 80).map(tc => ({
        name: tc.name,
        issue_type: tc.issue_type || '',
        stability: tc.stability,
        success_percentage: tc.success_percentage,
        last_run_tickets: tc.last_run_tickets || [],
        primary_component: tc.primary_component || '',
      }));

      const avgStab = filtered.length
        ? (filtered.reduce((s, tc) => s + (tc.stability || 0), 0) / filtered.length).toFixed(1)
        : '0';
      const avgSucc = filtered.length
        ? (filtered.reduce((s, tc) => s + (tc.success_percentage || 0), 0) / filtered.length).toFixed(1)
        : '0';
      const qiCases = filtered.filter(tc => tc.published_qi != null);
      const avgQi = qiCases.length
        ? (qiCases.reduce((s, tc) => s + tc.published_qi, 0) / qiCases.length).toFixed(1)
        : 'N/A';

      const response = await api.post(
        `${API_BASE_URL}/mcp/regression/ai-analysis/testcase-summary`,
        {
          stats: {
            total: filtered.length,
            succeeded: allSucceeded.length,
            failed: allFailed.length,
            avg_stability: avgStab,
            avg_success: avgSucc,
            avg_qi: avgQi,
            issue_type_breakdown: issueTypeBreakdown,
            component_breakdown: componentBreakdown,
            unique_tickets: [...new Set(allTickets)],
          },
          failed_testcases: failedTcs,
          branch,
          team,
        },
        { timeout: 120000 }
      );

      if (response.data.success) {
        setAiAnalysis(response.data.analysis);
      } else {
        setAiAnalysis(`Error: ${response.data.error || 'Unknown error'}`);
      }
    } catch (err) {
      console.error('AI analysis failed:', err);
      setAiAnalysis(`Error: ${err.response?.data?.error || err.message}`);
    } finally {
      setLoadingAi(false);
    }
  };

  const handleDownloadPageExcel = () => {
    setShowActionsMenu(false);
    if (!paginated.length) { showToast('No data on current page', 'error'); return; }
    const cols = activeColumns;
    const rows = paginated.map(tc =>
      Object.fromEntries(cols.map(col => {
        const v = tc[col.key];
        if (Array.isArray(v)) return [col.label, v.join(', ')];
        if (col.key === 'published_ops')
          return [col.label, (tc.published_success_ops != null && tc.published_total_ops != null)
            ? `${tc.published_success_ops}/${tc.published_total_ops}` : ''];
        if (typeof v === 'boolean') return [col.label, v ? 'Yes' : 'No'];
        return [col.label, v != null ? v : ''];
      }))
    );
    const ws = XLSX.utils.json_to_sheet(rows);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Testcases');
    XLSX.writeFile(wb, `testcases_${branch}_${team}_page${page}.xlsx`);
    showToast(`Downloaded page ${page} (${paginated.length} rows)`, 'success');
  };

  const openRunPlanModal = () => {
    setShowActionsMenu(false);
    setRpName('');
    setJpPrefix('');
    setResolvedData(null);
    setSelectedJpIds(new Set());
    setShowUnmatched(false);
    setCreatingRp(false);
    setShowRunPlanModal(true);
  };

  const handleResolveJobProfiles = () => {
    if (!jpPrefix.trim()) { showToast('Enter a job profile prefix', 'error'); return; }
    setResolving(true);
    setResolvedData(null);
    const filteredNames = filtered.map(tc => tc.name);
    api.post(`${API_BASE_URL}/mcp/regression/testcase-mgmt/resolve-job-profiles`, {
      branch, team,
      testcase_names: filteredNames,
      jp_prefix: jpPrefix.trim(),
    }, { timeout: 60000 })
      .then(res => {
        setResolvedData(res.data);
        const allIds = new Set((res.data.matched || []).map(m => m.job_profile_id));
        setSelectedJpIds(allIds);
        setResolving(false);
      })
      .catch(err => {
        const msg = err.response?.data?.error || err.message;
        showToast('Resolve failed: ' + msg, 'error');
        setResolving(false);
      });
  };

  const handleCreateRunPlan = () => {
    if (!rpName.trim()) { showToast('Enter a run plan name', 'error'); return; }
    if (!selectedJpIds.size) { showToast('Select at least one job profile', 'error'); return; }
    setCreatingRp(true);
    const taskId = addTask({ label: `Create Run Plan: ${rpName}`, page: 'Testcase Management' });
    const jpIds = [...selectedJpIds];
    api.post(`${API_BASE_URL}/mcp/regression/run-plan`, {
      name: rpName.trim(),
      job_profiles: jpIds,
      tag_name: '',
    }, { timeout: 30000 })
      .then(() => {
        showToast('Run plan created successfully!', 'success');
        updateTask(taskId, { status: 'success', detail: `${jpIds.length} job profiles` });
        setShowRunPlanModal(false);
        setCreatingRp(false);
      })
      .catch(err => {
        const msg = err.response?.data?.error || err.message;
        showToast('Create run plan failed: ' + msg, 'error');
        updateTask(taskId, { status: 'error', detail: msg });
        setCreatingRp(false);
      });
  };

  const toggleJpSelect = (jpId) => {
    setSelectedJpIds(prev => {
      const next = new Set(prev);
      if (next.has(jpId)) next.delete(jpId); else next.add(jpId);
      return next;
    });
  };

  const toggleAllJp = () => {
    if (!resolvedData?.matched) return;
    const allIds = resolvedData.matched.map(m => m.job_profile_id);
    const allSelected = allIds.every(id => selectedJpIds.has(id));
    setSelectedJpIds(allSelected ? new Set() : new Set(allIds));
  };

  const availableComponents = React.useMemo(() => {
    const set = new Set();
    testcases.forEach(tc => { if (tc.primary_component) set.add(tc.primary_component); });
    return [...set].sort();
  }, [testcases]);

  const filtered = React.useMemo(() => {
    let list = testcases;
    if (componentFilter) {
      list = list.filter(tc => tc.primary_component === componentFilter);
    }
    if (lastRunDate) {
      list = list.filter(tc => {
        if (!tc.last_run_date) return false;
        const tcDate = tc.last_run_date.slice(0, 10);
        return lastRunDateOp === '>=' ? tcDate >= lastRunDate : tcDate <= lastRunDate;
      });
    }
    return list;
  }, [testcases, componentFilter, lastRunDate, lastRunDateOp]);

  // Sorting
  const sorted = [...filtered].sort((a, b) => {
    let aVal = a[sortField];
    let bVal = b[sortField];
    if (aVal == null) aVal = '';
    if (bVal == null) bVal = '';
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return sortDir === 'asc' ? aVal - bVal : bVal - aVal;
    }
    const cmp = String(aVal).localeCompare(String(bVal));
    return sortDir === 'asc' ? cmp : -cmp;
  });

  const totalPages = pageSize === 'All' ? 1 : Math.max(1, Math.ceil(sorted.length / pageSize));
  const paginated = pageSize === 'All' ? sorted : sorted.slice((page - 1) * pageSize, page * pageSize);

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const toggleSelect = (oid) => {
    setSelectedOids(prev => {
      const next = new Set(prev);
      if (next.has(oid)) next.delete(oid); else next.add(oid);
      return next;
    });
  };

  const toggleSelectAll = () => {
    const pageOids = paginated.map(tc => tc.oid).filter(Boolean);
    const allSelected = pageOids.every(oid => selectedOids.has(oid));
    setSelectedOids(prev => {
      const next = new Set(prev);
      pageOids.forEach(oid => allSelected ? next.delete(oid) : next.add(oid));
      return next;
    });
  };

  const handleTagAction = (action) => {
    const tags = tagInput.split(',').map(t => t.trim()).filter(Boolean);
    if (!tags.length) { showToast('Enter at least one tag', 'error'); return; }
    if (!selectedOids.size) { showToast('Select at least one test case', 'error'); return; }

    setTagActionLoading(true);
    const verb = action === 'add' ? 'Add' : 'Delete';
    const selectedCount = selectedOids.size;
    const taskId = addTask({
      label: `${verb} tags [${tags.join(', ')}] on ${selectedCount} testcase(s)`,
      page: 'Testcase Management',
    });
    const url = action === 'add'
      ? `${API_BASE_URL}/mcp/regression/testcase-mgmt/tags/add`
      : `${API_BASE_URL}/mcp/regression/testcase-mgmt/tags/delete`;

    api.post(url, { testcase_oids: Array.from(selectedOids), tags, branch, team }, { timeout: 120000 })
      .then(res => {
        const d = res.data || {};
        const ok = d.success || 0;
        const fail = d.failed || 0;
        const notPresentTags = [
          ...new Set(
            (d.not_present || [])
              .flatMap(n => n.tags || [])
              .concat(
                (d.errors || []).flatMap(e => e.not_present || [])
              )
          ),
        ];
        const errBits = (d.errors || [])
          .slice(0, 3)
          .map(e => e.error || e.oid)
          .filter(Boolean);

        let detail;
        let toastType;
        if (action === 'delete' && ok === 0 && notPresentTags.length) {
          detail = `Tag not present: ${notPresentTags.join(', ')}`;
          toastType = 'error';
        } else if (action === 'delete' && notPresentTags.length && ok > 0) {
          detail = `${ok} removed, ${fail} failed — Tag not present: ${notPresentTags.join(', ')}`;
          toastType = 'info';
        } else {
          detail = `${ok} succeeded, ${fail} failed`
            + (errBits.length ? ` — ${errBits.join('; ')}` : '');
          toastType = fail > 0 && ok === 0 ? 'error' : fail > 0 ? 'info' : 'success';
        }

        showToast(`${verb} tags: ${detail}`, toastType);
        updateTask(taskId, {
          status: ok > 0 && fail === 0 ? 'success' : fail > 0 && ok === 0 ? 'error' : 'success',
          detail,
        });
        if (ok > 0) {
          setTagInput('');
          const updated = new Set(d.updated_oids || []);
          setSelectedOids(prev => {
            if (!updated.size) return new Set();
            const next = new Set(prev);
            updated.forEach(oid => next.delete(oid));
            return next;
          });
          fetchTestcases();
        }
      })
      .catch(err => {
        const d = err.response?.data || {};
        const notPresentTags = [
          ...new Set(
            (d.not_present || [])
              .flatMap(n => n.tags || [])
              .concat((d.errors || []).flatMap(e => e.not_present || []))
          ),
        ];
        const errBits = (d.errors || [])
          .slice(0, 3)
          .map(e => e.error || e.oid)
          .filter(Boolean);
        let msg = d.error
          || (notPresentTags.length ? `Tag not present: ${notPresentTags.join(', ')}` : null)
          || (errBits.length ? errBits.join('; ') : null)
          || err.message
          || 'Tag operation failed';
        // Prefer explicit not-present phrasing
        if (action === 'delete' && /tag not present/i.test(msg) === false && notPresentTags.length) {
          msg = `Tag not present: ${notPresentTags.join(', ')}`;
        }
        showToast(msg.startsWith('Tag not present') ? msg : `Tag ${verb.toLowerCase()} failed: ${msg}`, 'error');
        updateTask(taskId, { status: 'error', detail: msg });
      })
      .finally(() => setTagActionLoading(false));
  };

  const sortArrow = (field) => {
    if (sortField !== field) return null;
    return <span className="sort-arrow">{sortDir === 'asc' ? '▲' : '▼'}</span>;
  };

  const toggleColumn = (key) => {
    setVisibleColumns(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const activeColumns = ALL_COLUMNS.filter(c => visibleColumns.has(c.key));

  // Stats
  const succeededCount = filtered.filter(tc => tc.last_status === 'succeeded').length;
  const failedCount = filtered.filter(tc => tc.last_status === 'failed').length;
  const avgStability = filtered.length
    ? (filtered.reduce((s, tc) => s + (tc.stability || 0), 0) / filtered.length).toFixed(1)
    : '—';
  const avgSuccess = filtered.length
    ? (filtered.reduce((s, tc) => s + (tc.success_percentage || 0), 0) / filtered.length).toFixed(1)
    : '—';
  const qiCases = filtered.filter(tc => tc.published_qi != null);
  const avgQI = qiCases.length
    ? (qiCases.reduce((s, tc) => s + tc.published_qi, 0) / qiCases.length).toFixed(1)
    : '—';

  const pageOids = paginated.map(tc => tc.oid).filter(Boolean);
  const allPageSelected = pageOids.length > 0 && pageOids.every(oid => selectedOids.has(oid));

  return (
    <div className="tc-mgmt-container">
      {/* Header */}
      <div className="tc-mgmt-header">
        <h1>Testcase Management</h1>
        <div className="tc-mgmt-header-actions">
          {lastUpdated && (
            <span style={{ fontSize: 12, color: '#95a5a6', marginRight: 8 }}>
              Last updated: {new Date(lastUpdated).toLocaleString()}
            </span>
          )}

          {/* Customize Columns */}
          <div className="tc-col-picker-wrapper" ref={colPickerRef}>
            <button
              className="tc-btn tc-btn-outline"
              onClick={() => setShowColPicker(v => !v)}
            >
              Customise Columns
            </button>
            {showColPicker && (
              <div className="tc-col-picker-dropdown">
                <div className="tc-col-picker-header">
                  <span>Show / Hide Columns</span>
                  <button
                    className="tc-col-picker-reset"
                    onClick={() => setVisibleColumns(new Set(DEFAULT_VISIBLE))}
                  >
                    Reset
                  </button>
                </div>
                <div className="tc-col-picker-list">
                  {ALL_COLUMNS.map(col => (
                    <label key={col.key} className="tc-col-picker-item">
                      <input
                        type="checkbox"
                        checked={visibleColumns.has(col.key)}
                        onChange={() => toggleColumn(col.key)}
                      />
                      {col.label}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="tc-actions-wrapper" ref={actionsRef}>
            <button
              className="tc-btn tc-btn-actions"
              onClick={() => setShowActionsMenu(v => !v)}
              disabled={filtered.length === 0}
            >
              Actions ▾
            </button>
            {showActionsMenu && (
              <div className="tc-actions-dropdown">
                <button className="tc-actions-item" onClick={openRunPlanModal}>
                  Create Run Plan
                </button>
                <button className="tc-actions-item" onClick={handleDownloadPageExcel}>
                  Download Current Page (Excel)
                </button>
                <button className="tc-actions-item" onClick={() => { setShowActionsMenu(false); handleDownloadResourceSpec(); }}>
                  Download Resource Spec
                </button>
                <button className="tc-actions-item" disabled title="Coming soon">
                  Bulk Deprecate Testcases
                </button>
                <button className="tc-actions-item" disabled title="Coming soon">
                  Export Filtered to CSV
                </button>
                <button className="tc-actions-item" disabled title="Coming soon">
                  Notify Owners
                </button>
                <button className="tc-actions-item" disabled title="Coming soon">
                  Trigger Re-run for Failed
                </button>
              </div>
            )}
          </div>

          <button
            className="tc-btn tc-btn-ai-analyse"
            onClick={handleAiAnalyse}
            disabled={loadingAi || filtered.length === 0}
          >
            {loadingAi ? 'Analysing...' : 'AI Analyse'}
          </button>

          <button
            className="tc-btn tc-btn-reload"
            onClick={handleReload}
            disabled={reloading}
          >
            {reloading ? 'Fetching...' : 'Reload from TCMS'}
          </button>
        </div>
      </div>

      {/* Controls bar */}
      <div className="tc-mgmt-controls">
        <div className="tc-mgmt-filter-group tc-branch-picker-wrapper" ref={branchDropdownRef}>
          <label>Branch:</label>
          <button
            className="tc-branch-toggle"
            onClick={() => setShowBranchDropdown(v => !v)}
          >
            {branch} <span className="tc-branch-caret">▾</span>
          </button>
          {showBranchDropdown && (
            <div className="tc-branch-dropdown">
              {allBranches.map(b => {
                const isCustom = customBranches.includes(b);
                const isActive = branch === b;
                return (
                  <div key={b} className={`tc-branch-item${isActive ? ' active' : ''}`}>
                    <span
                      className="tc-branch-item-label"
                      onClick={() => { setBranch(b); setShowBranchDropdown(false); }}
                    >
                      {b}
                    </span>
                    {isCustom && (
                      <button
                        className="tc-branch-remove-btn"
                        onClick={e => { e.stopPropagation(); handleRemoveBranch(b); }}
                        title={`Remove ${b}`}
                      >
                        ✕
                      </button>
                    )}
                  </div>
                );
              })}
              <div className="tc-branch-add-row">
                <input
                  type="text"
                  placeholder="e.g. 7.7"
                  value={newBranchInput}
                  onChange={e => setNewBranchInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleAddBranch(); }}
                />
                <button
                  className="tc-branch-add-btn"
                  onClick={handleAddBranch}
                  disabled={!newBranchInput.trim()}
                >
                  Add
                </button>
              </div>
            </div>
          )}
        </div>
        <div className="tc-mgmt-filter-group">
          <label>Team:</label>
          <select value={team} onChange={e => setTeam(e.target.value)}>
            {teams.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="tc-mgmt-filter-group">
          <label>Tags:</label>
          <select value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
            <option value="">All Tags</option>
            {availableTags.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="tc-mgmt-filter-group">
          <label>Status:</label>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}>
            <option value="">All</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
          </select>
        </div>
        <div className="tc-mgmt-filter-group tc-name-filter-group">
          <label>Name:</label>
          <textarea
            className="tc-name-filter-textarea"
            placeholder="Filter by name (comma, pipe, or newline separated)..."
            value={nameFilter}
            onChange={e => setNameFilter(e.target.value)}
            rows={1}
            onInput={(e) => {
              // Auto-resize based on content
              e.target.style.height = 'auto';
              e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
            }}
          />
          <label className="tc-exact-match-label">
            <input
              type="checkbox"
              checked={nameExactMatch}
              onChange={e => setNameExactMatch(e.target.checked)}
            />
            Exact Match
          </label>
        </div>

        <div className="tc-mgmt-filter-group tc-date-filter-group">
          <label>Last Run Date:</label>
          <select
            className="tc-date-op-select"
            value={lastRunDateOp}
            onChange={e => setLastRunDateOp(e.target.value)}
          >
            <option value=">=">≥</option>
            <option value="<=">≤</option>
          </select>
          <input
            type="date"
            value={lastRunDate}
            onChange={e => setLastRunDate(e.target.value)}
          />
          {lastRunDate && (
            <button
              className="tc-filter-clear-btn"
              onClick={() => setLastRunDate('')}
              title="Clear date filter"
            >
              ✕
            </button>
          )}
        </div>

        <div className="tc-mgmt-filter-group">
          <label>Component:</label>
          <select value={componentFilter} onChange={e => setComponentFilter(e.target.value)}>
            <option value="">All Components</option>
            {availableComponents.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* Summary stats */}
      <div className="tc-mgmt-stats">
        <div className="tc-stat-card">
          <div className="stat-value">{totalCount}</div>
          <div className="stat-label">Total (unfiltered)</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value">{filtered.length}</div>
          <div className="stat-label">Filtered</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value" style={{ color: '#27ae60' }}>{succeededCount}</div>
          <div className="stat-label">Succeeded</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value" style={{ color: '#e74c3c' }}>{failedCount}</div>
          <div className="stat-label">Failed</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value">{avgStability}%</div>
          <div className="stat-label">Avg Stability</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value">{avgSuccess}%</div>
          <div className="stat-label">Avg Success</div>
        </div>
        <div className="tc-stat-card">
          <div className="stat-value">{avgQI}%</div>
          <div className="stat-label">Quality Index (QI)</div>
        </div>
      </div>

      {/* AI Analysis Panel */}
      {showAiPanel && (
        <div className="tc-ai-panel">
          <div className="tc-ai-panel-header">
            <h3>AI Analysis — {branch} / {team} ({filtered.length} testcases, all pages)</h3>
            <button className="tc-ai-panel-close" onClick={() => { setShowAiPanel(false); setAiAnalysis(null); }}>✕</button>
          </div>
          {loadingAi ? (
            <div className="tc-ai-loading">
              <div className="spinner" />
              <span>AI is analysing all {filtered.length} filtered testcases across all pages... This may take 30-60 seconds...</span>
            </div>
          ) : aiAnalysis ? (
            <div className="tc-ai-content">
              <AiMarkdown content={aiAnalysis} />
            </div>
          ) : null}
        </div>
      )}

      {/* Tag action panel */}
      {selectedOids.size > 0 && (
        <div className="tc-tag-action-panel">
          <span className="selected-count">{selectedOids.size} test case(s) selected</span>
          <input
            type="text"
            placeholder="Tag name(s), comma-separated"
            value={tagInput}
            onChange={e => setTagInput(e.target.value)}
          />
          <button className="tc-btn tc-btn-primary" disabled={tagActionLoading || !tagInput.trim()} onClick={() => handleTagAction('add')}>Add Tag</button>
          <button className="tc-btn tc-btn-danger" disabled={tagActionLoading || !tagInput.trim()} onClick={() => handleTagAction('delete')}>Delete Tag</button>
          <button className="tc-btn tc-btn-secondary" onClick={() => setSelectedOids(new Set())}>Clear Selection</button>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="tc-mgmt-loading">
          <div className="spinner" />
          <div>Loading test cases...</div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="tc-mgmt-empty">
          <h3>No test cases found</h3>
          <p>Click "Reload from TCMS" to fetch data, or adjust your filters.</p>
        </div>
      ) : (
        <>
          <div className="tc-mgmt-table-wrapper">
            <table className="tc-mgmt-table">
              <thead>
                <tr>
                  <th className="no-sort" style={{ width: 40 }}>
                    <input type="checkbox" checked={allPageSelected} onChange={toggleSelectAll} />
                  </th>
                  {activeColumns.map(col => (
                    <th
                      key={col.key}
                      className={col.sortable ? '' : 'no-sort'}
                      onClick={col.sortable ? () => handleSort(col.key) : undefined}
                    >
                      {col.label} {col.sortable && sortArrow(col.key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paginated.map(tc => (
                  <tr key={tc.oid || tc.name} className={selectedOids.has(tc.oid) ? 'selected-row' : ''}>
                    <td>
                      <input type="checkbox" checked={selectedOids.has(tc.oid)} onChange={() => toggleSelect(tc.oid)} />
                    </td>
                    {activeColumns.map(col => (
                      <td key={col.key}>{renderCell(tc, col.key)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="tc-mgmt-pagination">
            <span className="page-info">
              {pageSize === 'All' 
                ? `Showing all ${sorted.length} rows`
                : `Showing ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, sorted.length)} of ${sorted.length}`
              }
            </span>
            <div className="tc-page-size-picker">
              <label>Rows:</label>
              <select
                value={pageSize}
                onChange={e => { 
                  const newValue = e.target.value === 'All' ? 'All' : Number(e.target.value);
                  setPageSize(newValue); 
                  setPage(1); 
                }}
              >
                {PAGE_SIZE_OPTIONS.map(n => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </div>
            <div className="page-controls">
              <button disabled={page <= 1 || pageSize === 'All'} onClick={() => setPage(1)}>First</button>
              <button disabled={page <= 1 || pageSize === 'All'} onClick={() => setPage(p => p - 1)}>Prev</button>
              {pageSize !== 'All' && Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                let pageNum;
                if (totalPages <= 5) pageNum = i + 1;
                else if (page <= 3) pageNum = i + 1;
                else if (page >= totalPages - 2) pageNum = totalPages - 4 + i;
                else pageNum = page - 2 + i;
                return (
                  <button key={pageNum} className={page === pageNum ? 'active-page' : ''} onClick={() => setPage(pageNum)}>
                    {pageNum}
                  </button>
                );
              })}
              <button disabled={page >= totalPages || pageSize === 'All'} onClick={() => setPage(p => p + 1)}>Next</button>
              <button disabled={page >= totalPages || pageSize === 'All'} onClick={() => setPage(totalPages)}>Last</button>
            </div>
          </div>
        </>
      )}

      {/* Toast */}
      {toast && (
        <div className={`tc-toast toast-${toast.type}`}>{toast.msg}</div>
      )}

      {/* Create Run Plan Modal */}
      {showRunPlanModal && (
        <div className="tc-rp-modal-overlay" onClick={() => !creatingRp && setShowRunPlanModal(false)}>
          <div className="tc-rp-modal" onClick={e => e.stopPropagation()}>
            <div className="tc-rp-modal-header">
              <h3>Create Run Plan from Filtered Testcases</h3>
              <button className="tc-rp-modal-close" onClick={() => !creatingRp && setShowRunPlanModal(false)}>✕</button>
            </div>

            <div className="tc-rp-modal-body">
              <div className="tc-rp-form-row">
                <label>Run Plan Name</label>
                <input
                  type="text"
                  value={rpName}
                  onChange={e => setRpName(e.target.value)}
                  placeholder="e.g. CDP Regression Sprint 42"
                />
              </div>
              <div className="tc-rp-form-row">
                <label>Job Profile Prefix</label>
                <div className="tc-rp-prefix-row">
                  <input
                    type="text"
                    value={jpPrefix}
                    onChange={e => setJpPrefix(e.target.value)}
                    placeholder="e.g. cdp_regression_master"
                  />
                  <button
                    className="tc-btn tc-btn-resolve"
                    onClick={handleResolveJobProfiles}
                    disabled={resolving || !jpPrefix.trim()}
                  >
                    {resolving ? 'Resolving...' : 'Resolve'}
                  </button>
                </div>
              </div>

              <p className="tc-rp-info">
                {filtered.length} filtered testcase{filtered.length !== 1 ? 's' : ''} will be cross-referenced with JITA job profiles.
              </p>

              {resolvedData && (
                <div className="tc-rp-results">
                  <div className="tc-rp-summary">
                    <span className="tc-rp-summary-matched">
                      {resolvedData.total_matched_testcases} of {resolvedData.total_matched_testcases + resolvedData.total_unmatched_testcases} testcases covered by {resolvedData.matched.length} job profile{resolvedData.matched.length !== 1 ? 's' : ''}
                    </span>
                    {resolvedData.job_profiles_found > 0 && (
                      <span className="tc-rp-summary-found">
                        ({resolvedData.job_profiles_found} profiles found for prefix)
                      </span>
                    )}
                  </div>

                  {resolvedData.matched.length > 0 && (
                    <div className="tc-rp-matched-section">
                      <h4>Matched Job Profiles</h4>
                      <table className="tc-rp-matched-table">
                        <thead>
                          <tr>
                            <th>
                              <input
                                type="checkbox"
                                checked={resolvedData.matched.length > 0 && resolvedData.matched.every(m => selectedJpIds.has(m.job_profile_id))}
                                onChange={toggleAllJp}
                              />
                            </th>
                            <th>Job Profile Name</th>
                            <th>Testcases</th>
                          </tr>
                        </thead>
                        <tbody>
                          {resolvedData.matched.map(m => (
                            <tr key={m.job_profile_id} className={selectedJpIds.has(m.job_profile_id) ? 'selected-row' : ''}>
                              <td>
                                <input
                                  type="checkbox"
                                  checked={selectedJpIds.has(m.job_profile_id)}
                                  onChange={() => toggleJpSelect(m.job_profile_id)}
                                />
                              </td>
                              <td className="tc-rp-jp-name">{m.job_profile_name}</td>
                              <td>{m.testcase_count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {resolvedData.unmatched_testcases.length > 0 && (
                    <div className="tc-rp-unmatched">
                      <button
                        className="tc-rp-unmatched-toggle"
                        onClick={() => setShowUnmatched(v => !v)}
                      >
                        {showUnmatched ? '▾' : '▸'} Unavailable ({resolvedData.unmatched_testcases.length} testcase{resolvedData.unmatched_testcases.length !== 1 ? 's' : ''})
                      </button>
                      {showUnmatched && (
                        <ul className="tc-rp-unmatched-list">
                          {resolvedData.unmatched_testcases.map(name => (
                            <li key={name}>{name}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="tc-rp-modal-footer">
              <button
                className="tc-btn"
                onClick={() => setShowRunPlanModal(false)}
                disabled={creatingRp}
              >
                Cancel
              </button>
              <button
                className="tc-btn tc-btn-primary"
                onClick={handleCreateRunPlan}
                disabled={creatingRp || !resolvedData || !selectedJpIds.size || !rpName.trim()}
              >
                {creatingRp ? 'Creating...' : `Create Run Plan (${selectedJpIds.size} profiles)`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
