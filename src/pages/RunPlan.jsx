import React, { useState, useEffect, useRef } from 'react';
import api from '../api';
import { API_BASE_URL } from '../config';
import { useTaskContext } from '../context/TaskContext';
import AiMarkdown from '../components/AiMarkdown';
import './RunPlan.css';

const API_BASE = `${API_BASE_URL}/mcp/regression/run-plan`;
const JITA_BASE = 'https://jita.eng.nutanix.com/api/v2';

const ADDITIONAL_TAG_OPTIONS = [
  'CDP_Regression_Qual',
  'CDP_Smart_Qual',
  'NESTED_QUALIFIED',
  'critical',
  'major',
  'minor',
  'unstable',
];

export default function RunPlan() {
  const { addTask, updateTask: updateTaskCtx } = useTaskContext();
  const [view, setView] = useState('list'); // 'list', 'create', 'edit', 'history', 'batch-update', 'calendar'
  const [runPlans, setRunPlans] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedRunPlan, setSelectedRunPlan] = useState(null);
  const [historyData, setHistoryData] = useState([]);

  // Calendar state
  const [calendarMonth, setCalendarMonth] = useState(new Date());
  const [calendarEvents, setCalendarEvents] = useState([]);
  const [calendarRunPlans, setCalendarRunPlans] = useState([]);
  const [selectedCalendarDate, setSelectedCalendarDate] = useState(null);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [scheduleForm, setScheduleForm] = useState({ runPlanId: '', time: '09:00' });

  // Create/Edit form state
  const [formData, setFormData] = useState({
    name: '',
    jobProfileSearchType: 'id', // 'id' or 'pattern'
    jobProfileIds: '',
    jobProfilePattern: '',
    scheduleDate: '',
    selectedJobProfiles: []
  });

  // Batch Update state
  const [batchUpdateData, setBatchUpdateData] = useState({
    // Component checkboxes
    updateNosCluster: false,
    updatePrismCentral: false,
    // NOS_CLUSTER fields
    nosCluster: {
      branch: '',
      updateType: '', // 'tag' or 'commit'
      buildType: '',
      tag: '',
      commitId: '',
      gbn: ''
    },
    // PRISM_CENTRAL fields
    prismCentral: {
      branch: '',
      updateType: '', // 'tag' or 'commit'
      buildType: '',
      tag: '',
      commitId: '',
      gbn: ''
    },
    // Common fields
    nutestBranch: '',
    patchUrl: '',
    frameworkPatchUrl: '',
    testerTagsAction: '', // 'add' or 'remove' or ''
    testerTagValue: '', // Tag value to add/remove
    // Additional tags (overwrites run_tests_with_additional_tags)
    updateAdditionalTags: false,
    additionalTags: []
  });

  const [availableTags, setAvailableTags] = useState([]);
  const [showAdditionalTagsDropdown, setShowAdditionalTagsDropdown] = useState(false);
  const additionalTagsRef = useRef(null);

  // AI Risk Score state
  const [riskScores, setRiskScores] = useState({});
  const [loadingRisk, setLoadingRisk] = useState({});
  const [showRiskPanel, setShowRiskPanel] = useState(null);

  // Job Profile search results
  const [jobProfileResults, setJobProfileResults] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    function handleClickOutside(e) {
      if (additionalTagsRef.current && !additionalTagsRef.current.contains(e.target)) {
        setShowAdditionalTagsDropdown(false);
      }
    }
    if (showAdditionalTagsDropdown) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showAdditionalTagsDropdown]);

  useEffect(() => {
    if (view === 'list') {
      fetchRunPlans();
    }
  }, [view]);

  const fetchRunPlans = async () => {
    setLoading(true);
    try {
      const response = await api.get(API_BASE);
      setRunPlans(response.data.run_plans || []);
    } catch (error) {
      console.error('Error fetching run plans:', error);
      alert('Failed to fetch run plans');
    } finally {
      setLoading(false);
    }
  };

  // ── Calendar helpers ──
  const fetchCalendarData = async () => {
    setLoading(true);
    try {
      const response = await api.get(`${API_BASE}/calendar`);
      setCalendarEvents(response.data.events || []);
      setCalendarRunPlans(response.data.run_plans || []);
    } catch (error) {
      console.error('Error fetching calendar data:', error);
      alert('Failed to load calendar data');
    } finally {
      setLoading(false);
    }
  };

  const handleOpenCalendar = () => {
    setCalendarMonth(new Date());
    setView('calendar');
    fetchCalendarData();
  };

  const getDaysInMonth = (date) => {
    const year = date.getFullYear();
    const month = date.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startPad = firstDay.getDay();
    const days = [];
    for (let i = 0; i < startPad; i++) days.push(null);
    for (let d = 1; d <= lastDay.getDate(); d++) {
      days.push(new Date(year, month, d));
    }
    return days;
  };

  const fmtDate = (d) => {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
  };

  const eventsForDate = (dateStr) => calendarEvents.filter((e) => e.date === dateStr);

  const handleCalendarDateClick = (dateObj) => {
    setSelectedCalendarDate(dateObj);
    setScheduleDialogOpen(false);
  };

  const handleOpenScheduleDialog = () => {
    setScheduleForm({ runPlanId: '', time: '09:00' });
    setScheduleDialogOpen(true);
  };

  const handleScheduleFromCalendar = async () => {
    if (!scheduleForm.runPlanId || !selectedCalendarDate) return;
    const dateStr = fmtDate(selectedCalendarDate);
    const scheduleDateTime = `${dateStr}T${scheduleForm.time}`;
    setLoading(true);
    try {
      await api.put(`${API_BASE}/${scheduleForm.runPlanId}/schedule`, {
        schedule_date: scheduleDateTime,
      });
      alert('Run plan scheduled successfully!');
      setScheduleDialogOpen(false);
      fetchCalendarData();
    } catch (error) {
      console.error('Error scheduling run plan:', error);
      alert(`Failed to schedule: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  // ── Kill all tasks in a history entry ──
  const handleKillTasks = async (historyEntryId, taskCount) => {
    if (!window.confirm(`Are you sure you want to kill all ${taskCount} task(s)? This will abort any running tests.`)) {
      return;
    }

    setLoading(true);
    const taskId = addTask({ label: `Kill ${taskCount} task(s)`, page: 'Run Plan' });
    try {
      const response = await api.post(`${API_BASE}/history/${historyEntryId}/kill`);
      const killedCount = response.data.total_killed || 0;
      const failedCount = response.data.total_failed || 0;
      if (failedCount > 0) {
        alert(`Kill completed with errors:\nKilled: ${killedCount}\nFailed: ${failedCount}`);
        updateTaskCtx(taskId, { status: 'error', detail: `${killedCount} killed, ${failedCount} failed` });
      } else {
        alert(`Successfully killed ${killedCount} task(s)`);
        updateTaskCtx(taskId, { status: 'success', detail: `Killed ${killedCount} task(s)` });
      }
      if (selectedRunPlan) {
        handleViewHistory(selectedRunPlan.id);
      }
    } catch (error) {
      console.error('Error killing tasks:', error);
      const errData = error.response?.data;
      if (errData?.code === 'CREDENTIALS_EXPIRED') {
        alert('Your session credentials have expired. Please log out and log back in.');
      } else {
        alert(`Failed to kill tasks: ${errData?.error || error.message}`);
      }
      updateTaskCtx(taskId, { status: 'error', detail: errData?.error || error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = () => {
    setFormData({
      name: '',
      jobProfileSearchType: 'id',
      jobProfileIds: '',
      jobProfilePattern: '',
      scheduleDate: '',
      selectedJobProfiles: []
    });
    setJobProfileResults([]);
    setView('create');
  };

  const handleEdit = async (runPlan) => {
    setSelectedRunPlan(runPlan);
    setFormData({
      name: runPlan.name,
      jobProfileSearchType: 'id',
      jobProfileIds: '',
      jobProfilePattern: '',
      scheduleDate: runPlan.schedule_date || '',
      selectedJobProfiles: []
    });
    
    // Fetch job profile details for the IDs in the run plan
    if (runPlan.job_profiles && runPlan.job_profiles.length > 0) {
      setLoading(true);
      try {
        const jobProfileIds = runPlan.job_profiles.filter(id => id && id.trim());
        if (jobProfileIds.length > 0) {
          const response = await api.post(`${API_BASE}/search-job-profiles`, {
            search_type: 'id',
            search_value: jobProfileIds.join(',')
          });
          const normalized = (response.data.job_profiles || []).map(normalizeJobProfile);
          setFormData(prev => ({
            ...prev,
            selectedJobProfiles: normalized
          }));
          setJobProfileResults(normalized);
        }
      } catch (error) {
        console.error('Error fetching job profiles:', error);
        alert('Failed to fetch job profile details');
      } finally {
        setLoading(false);
      }
    } else {
      setJobProfileResults([]);
    }
    
    setView('edit');
  };

  // Helper function to extract ID from $oid object or return string
  const extractId = (id) => {
    if (typeof id === 'string') return id;
    if (id && typeof id === 'object' && id.$oid) return id.$oid;
    if (id && typeof id === 'object' && id._id) return extractId(id._id);
    return String(id || '');
  };

  // Normalize job profile data (convert _id from object to string)
  const normalizeJobProfile = (jp) => {
    if (!jp) return jp;
    const normalized = { ...jp };
    if (normalized._id) {
      normalized._id = extractId(normalized._id);
    }
    return normalized;
  };

  const handleSearchJobProfiles = async () => {
    setSearching(true);
    try {
      const response = await api.post(`${API_BASE}/search-job-profiles`, {
        search_type: formData.jobProfileSearchType,
        search_value: formData.jobProfileSearchType === 'id' 
          ? formData.jobProfileIds 
          : formData.jobProfilePattern
      });
      // Normalize the job profiles to extract _id strings
      const normalized = (response.data.job_profiles || []).map(normalizeJobProfile);
      setJobProfileResults(normalized);
    } catch (error) {
      console.error('Error searching job profiles:', error);
      alert('Failed to search job profiles');
    } finally {
      setSearching(false);
    }
  };

  const handleAddJobProfile = (jobProfile) => {
    const normalized = normalizeJobProfile(jobProfile);
    const normalizedId = extractId(normalized._id);
    if (!formData.selectedJobProfiles.find(jp => extractId(jp._id) === normalizedId)) {
      setFormData({
        ...formData,
        selectedJobProfiles: [...formData.selectedJobProfiles, normalized]
      });
    }
  };

  const handleAddAllJobProfiles = () => {
    const newProfiles = jobProfileResults.filter(
      jp => !formData.selectedJobProfiles.find(selected => extractId(selected._id) === extractId(jp._id))
    ).map(normalizeJobProfile);
    setFormData({
      ...formData,
      selectedJobProfiles: [...formData.selectedJobProfiles, ...newProfiles]
    });
  };

  const handleRemoveJobProfile = (jobProfileId) => {
    const idToRemove = extractId(jobProfileId);
    setFormData({
      ...formData,
      selectedJobProfiles: formData.selectedJobProfiles.filter(jp => extractId(jp._id) !== idToRemove)
    });
  };

  const handleSaveRunPlan = async () => {
    // Validation
    if (!formData.name.trim()) {
      alert('Run Plan Name is required');
      return;
    }
    if (formData.selectedJobProfiles.length === 0) {
      alert('Please select at least one Job Profile');
      return;
    }

    setLoading(true);
    const verb = view === 'create' ? 'Create' : 'Update';
    const taskId = addTask({ label: `${verb} Run Plan: ${formData.name}`, page: 'Run Plan' });
    try {
      const payload = {
        name: formData.name,
        job_profiles: formData.selectedJobProfiles.map(jp => extractId(jp._id)),
        schedule_date: formData.scheduleDate || null
      };
      
      if (view === 'create') {
        const branch = formData.name.split('_').pop() || 'master';
        const timestamp = Date.now();
        payload.tag_name = `${branch}_${timestamp}`;
      }

      if (view === 'create') {
        await api.post(API_BASE, payload);
      } else {
        await api.put(`${API_BASE}/${selectedRunPlan.id}`, payload);
      }
      
      alert(`Run Plan ${view === 'create' ? 'created' : 'updated'} successfully`);
      updateTaskCtx(taskId, { status: 'success', detail: `${verb}d successfully` });
      setView('list');
      fetchRunPlans();
    } catch (error) {
      console.error('Error saving run plan:', error);
      alert(`Failed to ${view === 'create' ? 'create' : 'update'} run plan`);
      updateTaskCtx(taskId, { status: 'error', detail: error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleTriggerNow = async (runPlanId) => {
    if (!window.confirm('Are you sure you want to trigger this run plan now?')) {
      return;
    }

    setLoading(true);
    const taskId = addTask({ label: `Trigger Run Plan: ${runPlanId}`, page: 'Run Plan' });
    try {
      const response = await api.post(`${API_BASE}/${runPlanId}/trigger`);
      const count = response.data.task_ids?.length || 0;
      const triggeredBy = response.data.triggered_by || '';
      alert(`Triggered successfully by ${triggeredBy}! Created ${count} task(s)`);
      updateTaskCtx(taskId, { status: 'success', detail: `Created ${count} JITA task(s) as ${triggeredBy}` });
      fetchRunPlans();
    } catch (error) {
      console.error('Error triggering run plan:', error);
      const errData = error.response?.data;
      if (errData?.code === 'CREDENTIALS_EXPIRED') {
        alert('Your session credentials have expired. Please log out and log back in to trigger runs.');
      } else {
        alert(`Failed to trigger run plan: ${errData?.error || error.message}`);
      }
      updateTaskCtx(taskId, { status: 'error', detail: errData?.error || error.message });
    } finally {
      setLoading(false);
    }
  };

  const handleBatchUpdate = async (runPlan) => {
    setSelectedRunPlan(runPlan);
    setBatchUpdateData({
      updateNosCluster: false,
      updatePrismCentral: false,
      nosCluster: {
        branch: '',
        updateType: '',
        buildType: '',
        tag: '',
        commitId: '',
        gbn: ''
      },
      prismCentral: {
        branch: '',
        updateType: '',
        buildType: '',
        tag: '',
        commitId: '',
        gbn: ''
      },
      nutestBranch: '',
      patchUrl: '',
      frameworkPatchUrl: '',
      testerTagsAction: '',
      testerTagValue: '',
      updateAdditionalTags: false,
      additionalTags: []
    });
    setShowAdditionalTagsDropdown(false);
    setView('batch-update');
  };

  const handleExecuteBatchUpdate = async () => {
    if (!selectedRunPlan) return;

    if (!window.confirm(`Are you sure you want to batch update ${selectedRunPlan.job_profiles?.length || 0} job profile(s)?`)) {
      return;
    }

    setLoading(true);
    try {
      const payload = {
        components: []
      };
      
      // Add NOS_CLUSTER update if selected
      if (batchUpdateData.updateNosCluster) {
        const nosClusterData = {
          component: 'NOS_CLUSTER',
          branch: batchUpdateData.nosCluster.branch,
          update_type: batchUpdateData.nosCluster.updateType,
          build_type: batchUpdateData.nosCluster.buildType
        };
        
        if (batchUpdateData.nosCluster.updateType === 'tag' && batchUpdateData.nosCluster.tag) {
          nosClusterData.tag = batchUpdateData.nosCluster.tag;
        } else if (batchUpdateData.nosCluster.updateType === 'commit') {
          if (batchUpdateData.nosCluster.commitId) {
            nosClusterData.commit_id = batchUpdateData.nosCluster.commitId;
          }
          if (batchUpdateData.nosCluster.gbn) {
            nosClusterData.gbn = batchUpdateData.nosCluster.gbn;
          }
        }
        
        payload.components.push(nosClusterData);
      }
      
      // Add PRISM_CENTRAL update if selected
      if (batchUpdateData.updatePrismCentral) {
        const prismCentralData = {
          component: 'PRISM_CENTRAL',
          branch: batchUpdateData.prismCentral.branch,
          update_type: batchUpdateData.prismCentral.updateType,
          build_type: batchUpdateData.prismCentral.buildType
        };
        
        if (batchUpdateData.prismCentral.updateType === 'tag' && batchUpdateData.prismCentral.tag) {
          prismCentralData.tag = batchUpdateData.prismCentral.tag;
        } else if (batchUpdateData.prismCentral.updateType === 'commit') {
          if (batchUpdateData.prismCentral.commitId) {
            prismCentralData.commit_id = batchUpdateData.prismCentral.commitId;
          }
          if (batchUpdateData.prismCentral.gbn) {
            prismCentralData.gbn = batchUpdateData.prismCentral.gbn;
          }
        }
        
        payload.components.push(prismCentralData);
      }

      // Add common fields if provided
      if (batchUpdateData.nutestBranch) {
        payload.nutest_branch = batchUpdateData.nutestBranch;
      }
      if (batchUpdateData.patchUrl) {
        payload.patch_url = batchUpdateData.patchUrl;
      }
      if (batchUpdateData.frameworkPatchUrl) {
        payload.framework_patch_url = batchUpdateData.frameworkPatchUrl;
      }
      
      // Add tester_tags update if provided
      if (batchUpdateData.testerTagsAction && batchUpdateData.testerTagValue) {
        payload.tester_tags_action = batchUpdateData.testerTagsAction;
        payload.tester_tag_value = batchUpdateData.testerTagValue;
      }

      // Add run_tests_with_additional_tags overwrite if enabled
      if (batchUpdateData.updateAdditionalTags) {
        payload.run_tests_with_additional_tags = batchUpdateData.additionalTags;
      }

      const batchTaskId = addTask({ label: `Batch Update: ${selectedRunPlan.name}`, page: 'Run Plan' });
      const response = await api.post(
        `${API_BASE}/${selectedRunPlan.id}/batch-update`,
        payload
      );
      const updatedCount = response.data.updated_count || 0;
      const failedCount = response.data.failed_updates?.length || 0;
      
      if (failedCount > 0) {
        const failedIds = response.data.failed_updates.map(f => f.job_id).join(', ');
        alert(`Batch update completed with errors:\n✅ Updated: ${updatedCount}\n❌ Failed: ${failedCount}\n\nFailed IDs: ${failedIds}`);
        updateTaskCtx(batchTaskId, { status: 'error', detail: `${updatedCount} updated, ${failedCount} failed` });
      } else {
        alert(`✅ Batch update completed successfully! Updated ${updatedCount} job profile(s)`);
        updateTaskCtx(batchTaskId, { status: 'success', detail: `Updated ${updatedCount} job profile(s)` });
      }
      
      setView('list');
      fetchRunPlans();
    } catch (error) {
      console.error('Error executing batch update:', error);
      alert('Failed to execute batch update');
    } finally {
      setLoading(false);
    }
  };

  const toggleAdditionalTag = (tag) => {
    setBatchUpdateData(prev => {
      const tags = prev.additionalTags.includes(tag)
        ? prev.additionalTags.filter(t => t !== tag)
        : [...prev.additionalTags, tag];
      return { ...prev, additionalTags: tags };
    });
  };

  const handleViewHistory = async (runPlanId) => {
    setLoading(true);
    try {
      const response = await api.get(`${API_BASE}/${runPlanId}/history`);
      setHistoryData(response.data.history || []);
      setSelectedRunPlan(runPlans.find(rp => rp.id === runPlanId));
      setView('history');
    } catch (error) {
      console.error('Error fetching history:', error);
      alert('Failed to fetch history');
    } finally {
      setLoading(false);
    }
  };

  const handleClone = async (runPlanId) => {
    if (!window.confirm('Are you sure you want to clone this run plan? A new run plan will be created with a new unique tag name.')) {
      return;
    }

    setLoading(true);
    try {
      const response = await api.post(`${API_BASE}/${runPlanId}/clone`);
      if (response.data.success) {
        alert(`Run plan cloned successfully! New tag: ${response.data.run_plan.tag_name}`);
        fetchRunPlans();
      } else {
        alert(`Failed to clone run plan: ${response.data.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error cloning run plan:', error);
      alert(`Failed to clone run plan: ${error.response?.data?.error || error.message || 'Unknown error'}`);
    } finally {
      setLoading(false);
    }
  };


  const handleRetryTrigger = async (historyEntryId) => {
    setLoading(true);
    try {
      const response = await api.post(`${API_BASE}/history/${historyEntryId}/retry`);
      alert('Retry triggered successfully!');
      if (selectedRunPlan) {
        handleViewHistory(selectedRunPlan.id);
      }
    } catch (error) {
      console.error('Error retrying trigger:', error);
      alert('Failed to retry trigger');
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteHistory = async (historyEntryId) => {
    if (!window.confirm('Are you sure you want to delete this history entry?')) {
      return;
    }

    setLoading(true);
    try {
      await api.delete(`${API_BASE}/history/${historyEntryId}`);
      alert('History entry deleted');
      if (selectedRunPlan) {
        handleViewHistory(selectedRunPlan.id);
      }
    } catch (error) {
      console.error('Error deleting history:', error);
      alert('Failed to delete history entry');
    } finally {
      setLoading(false);
    }
  };

  const handleLastTriggeredClick = async (runPlanId, e) => {
    e.preventDefault();
    try {
      // Fetch history to get the latest entry's task IDs
      const response = await api.get(`${API_BASE}/${runPlanId}/history`);
      const history = response.data.history || [];
      
      // Filter to only successful runs (status === 'success' or 'Success' or 'completed' or 'Completed')
      const successfulRuns = history.filter(entry => {
        const status = entry.status?.toLowerCase() || '';
        return status === 'success' || status === 'completed' || status === 'succeeded';
      });
      
      if (successfulRuns.length > 0) {
        // Get the most recent successful entry (first one, as they're sorted by date descending)
        const latestSuccessfulEntry = successfulRuns[0];
        const taskIds = latestSuccessfulEntry.task_ids || [];
        
        if (taskIds.length > 0) {
          // Build JITA URL with all task IDs
          const jitaUrl = `https://jita.eng.nutanix.com/results?task_ids=${taskIds.join(',')}&active_tab=1&merge_tests=true`;
          window.open(jitaUrl, '_blank');
        } else {
          alert('No task IDs found for the last successfully triggered run');
        }
      } else {
        alert('No successful runs found for this run plan');
      }
    } catch (error) {
      console.error('Error fetching history:', error);
      alert('Failed to fetch history');
    }
  };

  const handleCreateTriageGenieJob = (historyEntry) => {
    // Store data in localStorage to pass to TriageGenie component
    const triageGenieData = {
      name: selectedRunPlan?.name || 'Run Plan Job',
      jita_task_ids: historyEntry.task_ids?.join(',') || '',
      fromRunPlan: true
    };
    localStorage.setItem('triageGeniePrefill', JSON.stringify(triageGenieData));
    
    // Dispatch event to navigate to Triage Genie
    window.dispatchEvent(new CustomEvent('navigateToTriageGenie', { detail: triageGenieData }));
    
    // Trigger navigation in App.jsx
    window.dispatchEvent(new CustomEvent('setActivePage', { detail: 'triage-genie' }));
  };

  const handleDeleteTag = async (runPlanId, tagName) => {
    if (!tagName) {
      alert('No tag name found in this run plan');
      return;
    }

    if (!window.confirm(`Are you sure you want to remove tag "${tagName}" from tester_tags of all job profiles in this run plan?`)) {
      return;
    }

    setLoading(true);
    try {
      const response = await api.post(`${API_BASE}/${runPlanId}/delete-tag`, {
        tag_name: tagName
      });
      alert(`Tag "${tagName}" removed from ${response.data.updated_count || 0} job profile(s)`);
      fetchRunPlans();
    } catch (error) {
      console.error('Error deleting tag:', error);
      alert('Failed to delete tag from job profiles');
    } finally {
      setLoading(false);
    }
  };

  const handleLoadRiskScore = async (plan) => {
    const planId = plan.id;
    setLoadingRisk(prev => ({ ...prev, [planId]: true }));
    try {
      const historyResp = await api.get(`${API_BASE}/${planId}/history`);
      const history = historyResp.data.history || [];

      const response = await api.post(
        `${API_BASE_URL}/mcp/regression/ai-analysis/run-plan-risk`,
        {
          name: plan.name,
          tag_name: plan.tag_name || '',
          job_profile_count: plan.job_profiles?.length || 0,
          history: history.slice(0, 10),
        },
        { timeout: 90000 }
      );

      if (response.data.success) {
        setRiskScores(prev => ({ ...prev, [planId]: response.data }));
      } else {
        alert(`Risk analysis failed: ${response.data.error || 'Unknown error'}`);
      }
    } catch (error) {
      console.error('Error loading risk score:', error);
      alert(`Failed to load risk score: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoadingRisk(prev => ({ ...prev, [planId]: false }));
    }
  };

  // Render List View
  if (view === 'list') {
    return (
      <div className="run-plan-container">
        <div className="run-plan-header">
          <h1>Run Plan - Regression Scheduling</h1>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button className="btn-calendar" onClick={handleOpenCalendar}>
              Calendar View
            </button>
            <button className="btn-primary" onClick={handleCreate}>
              + Create Run Plan
            </button>
          </div>
        </div>

        {loading ? (
          <div className="loading">Loading...</div>
        ) : (
          <table className="run-plan-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Tag Name</th>
                <th>Job Profiles</th>
                <th>Schedule Date</th>
                <th>Last Triggered</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {runPlans.length === 0 ? (
                <tr>
                  <td colSpan="6" className="empty-state">
                    No run plans found. Create one to get started.
                  </td>
                </tr>
              ) : (
                runPlans.map((plan) => (
                  <tr key={plan.id}>
                    <td>{plan.name}</td>
                    <td>{plan.tag_name}</td>
                    <td>{plan.job_profiles?.length || 0}</td>
                    <td>{plan.schedule_date || '-'}</td>
                    <td>
                      {plan.last_triggered ? (
                        <a
                          href="#"
                          onClick={(e) => handleLastTriggeredClick(plan.id, e)}
                          style={{ color: '#3498db', textDecoration: 'none', cursor: 'pointer' }}
                          onMouseEnter={(e) => e.target.style.textDecoration = 'underline'}
                          onMouseLeave={(e) => e.target.style.textDecoration = 'none'}
                        >
                          {plan.last_triggered}
                        </a>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button onClick={() => handleEdit(plan)}>Edit</button>
                        <button onClick={() => handleTriggerNow(plan.id)}>Trigger Now</button>
                        <button onClick={() => handleBatchUpdate(plan)}>Batch Update</button>
                        <button onClick={() => handleViewHistory(plan.id)}>History</button>
                        <button 
                          onClick={() => handleClone(plan.id)}
                          style={{ background: 'white', color: '#2c3e50', border: '1px solid #ddd' }}
                        >
                          Clone
                        </button>
                        <button
                          onClick={() => handleLoadRiskScore(plan)}
                          disabled={loadingRisk[plan.id]}
                          className="btn-risk-score"
                        >
                          {loadingRisk[plan.id] ? '...' : riskScores[plan.id] ? `Risk: ${riskScores[plan.id].risk_score}` : 'AI Risk'}
                        </button>
                      </div>
                      {riskScores[plan.id] && (
                        <div className="risk-score-badge-row">
                          <span
                            className={`risk-badge risk-${riskScores[plan.id].risk_level?.toLowerCase()}`}
                            onClick={() => setShowRiskPanel(showRiskPanel === plan.id ? null : plan.id)}
                            title="Click to see details"
                          >
                            {riskScores[plan.id].risk_level} ({riskScores[plan.id].risk_score}/100)
                          </span>
                        </div>
                      )}
                      {showRiskPanel === plan.id && riskScores[plan.id] && (
                        <div className="risk-detail-panel">
                          <div className="risk-detail-header">
                            <strong>AI Risk Analysis — {plan.name}</strong>
                            <button onClick={() => setShowRiskPanel(null)}>✕</button>
                          </div>
                          <div className="risk-detail-body">
                            <AiMarkdown content={riskScores[plan.id].analysis} />
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  // Render Create/Edit View
  if (view === 'create' || view === 'edit') {
    return (
      <div className="run-plan-container">
        <div className="run-plan-header">
          <h1>{view === 'create' ? 'Create' : 'Edit'} Run Plan</h1>
          <button onClick={() => setView('list')}>← Back to List</button>
        </div>

        <div className="run-plan-form">
          {/* Run Plan Name */}
          <div className="form-group">
            <label>
              Run Plan Name <span className="required">*</span>
            </label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="e.g., CDP_Regression_Upgrade_master"
            />
            <small>Examples: CDP_Regression_Upgrade_master, CDP_Regression_FullReg_master</small>
          </div>

          {/* Job Profile Selection */}
          <div className="form-group">
            <label>Job Profile Selection <span className="required">*</span></label>
            <div className="radio-group">
              <label>
                <input
                  type="radio"
                  value="id"
                  checked={formData.jobProfileSearchType === 'id'}
                  onChange={(e) => setFormData({ ...formData, jobProfileSearchType: e.target.value })}
                />
                Search by Job Profile ID (comma separated)
              </label>
              <label>
                <input
                  type="radio"
                  value="pattern"
                  checked={formData.jobProfileSearchType === 'pattern'}
                  onChange={(e) => setFormData({ ...formData, jobProfileSearchType: e.target.value })}
                />
                Search by Pattern Name
              </label>
            </div>

            {formData.jobProfileSearchType === 'id' ? (
              <div className="search-input-group">
                <input
                  type="text"
                  value={formData.jobProfileIds}
                  onChange={(e) => setFormData({ ...formData, jobProfileIds: e.target.value })}
                  placeholder="e.g., 688b25818e79ce48d7b881d4, 68e55d5d2bc0c47ea1a67f68"
                />
                <button onClick={handleSearchJobProfiles} disabled={searching || !formData.jobProfileIds.trim()}>
                  {searching ? 'Searching...' : 'Search'}
                </button>
              </div>
            ) : (
              <div className="search-input-group">
                <input
                  type="text"
                  value={formData.jobProfilePattern}
                  onChange={(e) => setFormData({ ...formData, jobProfilePattern: e.target.value })}
                  placeholder="e.g., sudharshan_test2*"
                />
                <button onClick={handleSearchJobProfiles} disabled={searching || !formData.jobProfilePattern.trim()}>
                  {searching ? 'Searching...' : 'Search'}
                </button>
              </div>
            )}

            {/* Search Results */}
            {jobProfileResults.length > 0 && (
              <div className="search-results">
                <div className="results-header">
                  <span>Found {jobProfileResults.length} job profile(s)</span>
                  <button onClick={handleAddAllJobProfiles}>Add All</button>
                </div>
                <table className="results-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Name</th>
                      <th>Description</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobProfileResults.map((jp) => {
                      const jpId = extractId(jp._id);
                      const isSelected = formData.selectedJobProfiles.find(selected => extractId(selected._id) === jpId);
                      return (
                        <tr key={jpId}>
                          <td>{jpId}</td>
                          <td>{jp.name}</td>
                          <td>{jp.description || '-'}</td>
                          <td>
                            <button
                              onClick={() => handleAddJobProfile(jp)}
                              disabled={!!isSelected}
                            >
                              {isSelected ? 'Added' : 'Add'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Selected Job Profiles */}
            {formData.selectedJobProfiles.length > 0 && (
              <div className="selected-profiles">
                <h4>Selected Job Profiles ({formData.selectedJobProfiles.length})</h4>
                <div className="selected-list">
                  {formData.selectedJobProfiles.map((jp) => {
                    const jpId = extractId(jp._id);
                    return (
                      <div key={jpId} className="selected-item">
                        <span>{jp.name || jpId}</span>
                        <button onClick={() => handleRemoveJobProfile(jpId)}>×</button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* Job Profiles List (Edit Mode) */}
          {view === 'edit' && formData.selectedJobProfiles.length > 0 && (
            <div className="form-group">
              <label>Current Job Profiles</label>
              <div className="job-profiles-list">
                <table className="results-table" style={{ width: '100%' }}>
                  <thead>
                    <tr>
                      <th>Job Profile ID</th>
                      <th>Name</th>
                      <th>Description</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {formData.selectedJobProfiles.map((jp) => {
                      const jpId = extractId(jp._id);
                      return (
                        <tr key={jpId}>
                          <td>{jpId}</td>
                          <td>{jp.name || '-'}</td>
                          <td>{jp.description || '-'}</td>
                          <td>
                            <button
                              onClick={() => handleRemoveJobProfile(jpId)}
                              style={{ background: '#e74c3c', color: 'white' }}
                            >
                              Remove
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Schedule Date */}
          <div className="form-group">
            <label>Schedule Date (Optional)</label>
            <input
              type="datetime-local"
              value={formData.scheduleDate}
              onChange={(e) => setFormData({ ...formData, scheduleDate: e.target.value })}
            />
          </div>

          <div className="form-actions">
            <button onClick={() => setView('list')}>Cancel</button>
            <button className="btn-primary" onClick={handleSaveRunPlan} disabled={loading}>
              {loading ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render Batch Update View
  if (view === 'batch-update') {
    return (
      <div className="run-plan-container">
        <div className="run-plan-header">
          <h1>Batch Update Job Profiles</h1>
          <button onClick={() => setView('list')}>← Back to List</button>
        </div>

        <div className="run-plan-form">
          {/* Component Selection Checkboxes */}
          <div className="form-group">
            <label>Select Components to Update</label>
            <div style={{ display: 'flex', gap: '20px', marginTop: '10px' }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={batchUpdateData.updateNosCluster}
                  onChange={(e) => setBatchUpdateData({ ...batchUpdateData, updateNosCluster: e.target.checked })}
                />
                <span style={{ fontWeight: 'bold' }}>NOS_CLUSTER</span>
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={batchUpdateData.updatePrismCentral}
                  onChange={(e) => setBatchUpdateData({ ...batchUpdateData, updatePrismCentral: e.target.checked })}
                />
                <span style={{ fontWeight: 'bold' }}>PRISM_CENTRAL</span>
              </label>
            </div>
            <small>Select one or both components to update independently</small>
          </div>

          {/* Side-by-side component fields */}
          <div style={{ display: 'flex', gap: '30px', marginTop: '20px' }}>
            {/* NOS_CLUSTER Fields */}
            {batchUpdateData.updateNosCluster && (
              <div style={{ flex: 1, border: '1px solid #ddd', padding: '20px', borderRadius: '8px', backgroundColor: '#f9f9f9' }}>
                <h3 style={{ marginTop: 0, marginBottom: '20px', color: '#2c3e50' }}>NOS_CLUSTER</h3>
                
                <div className="form-group">
                  <label>Branch</label>
                  <input
                    type="text"
                    value={batchUpdateData.nosCluster.branch}
                    onChange={(e) => setBatchUpdateData({ 
                      ...batchUpdateData, 
                      nosCluster: { ...batchUpdateData.nosCluster, branch: e.target.value }
                    })}
                    placeholder="e.g., ganges-7.3-stable"
                  />
                  <small>Optional: Enter branch name</small>
                </div>

                <div className="form-group">
                  <label>Update Type</label>
                  <div className="radio-group">
                    <label>
                      <input
                        type="radio"
                        value="tag"
                        checked={batchUpdateData.nosCluster.updateType === 'tag'}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          nosCluster: { ...batchUpdateData.nosCluster, updateType: e.target.value }
                        })}
                      />
                      By Tag
                    </label>
                    <label>
                      <input
                        type="radio"
                        value="commit"
                        checked={batchUpdateData.nosCluster.updateType === 'commit'}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          nosCluster: { ...batchUpdateData.nosCluster, updateType: e.target.value }
                        })}
                      />
                      By Commit
                    </label>
                  </div>
                </div>

                <div className="form-group">
                  <label>Build Type</label>
                  <select
                    value={batchUpdateData.nosCluster.buildType}
                    onChange={(e) => setBatchUpdateData({ 
                      ...batchUpdateData, 
                      nosCluster: { ...batchUpdateData.nosCluster, buildType: e.target.value }
                    })}
                  >
                    <option value="">-- Select Build Type (Optional) --</option>
                    <option value="release">release</option>
                    <option value="opt">opt</option>
                  </select>
                </div>

                {batchUpdateData.nosCluster.updateType === 'tag' && (
                  <div className="form-group">
                    <label>Tag</label>
                    <select
                      value={batchUpdateData.nosCluster.tag}
                      onChange={(e) => setBatchUpdateData({ 
                        ...batchUpdateData, 
                        nosCluster: { ...batchUpdateData.nosCluster, tag: e.target.value }
                      })}
                    >
                      <option value="">-- Select Tag (Optional) --</option>
                      <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                      <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                    </select>
                  </div>
                )}

                {batchUpdateData.nosCluster.updateType === 'commit' && (
                  <>
                    <div className="form-group">
                      <label>Commit ID</label>
                      <input
                        type="text"
                        value={batchUpdateData.nosCluster.commitId}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          nosCluster: { ...batchUpdateData.nosCluster, commitId: e.target.value }
                        })}
                        placeholder="e.g., cd8cd937b6288cf2c58a44a0bc1c58d85bf5c0bb"
                      />
                    </div>
                    <div className="form-group">
                      <label>GBN</label>
                      <input
                        type="text"
                        value={batchUpdateData.nosCluster.gbn}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          nosCluster: { ...batchUpdateData.nosCluster, gbn: e.target.value }
                        })}
                        placeholder="e.g., 1764602295"
                      />
                    </div>
                  </>
                )}
              </div>
            )}

            {/* PRISM_CENTRAL Fields */}
            {batchUpdateData.updatePrismCentral && (
              <div style={{ flex: 1, border: '1px solid #ddd', padding: '20px', borderRadius: '8px', backgroundColor: '#f9f9f9' }}>
                <h3 style={{ marginTop: 0, marginBottom: '20px', color: '#2c3e50' }}>PRISM_CENTRAL</h3>
                
                <div className="form-group">
                  <label>Branch</label>
                  <input
                    type="text"
                    value={batchUpdateData.prismCentral.branch}
                    onChange={(e) => setBatchUpdateData({ 
                      ...batchUpdateData, 
                      prismCentral: { ...batchUpdateData.prismCentral, branch: e.target.value }
                    })}
                    placeholder="e.g., master"
                  />
                  <small>Optional: Enter branch name</small>
                </div>

                <div className="form-group">
                  <label>Update Type</label>
                  <div className="radio-group">
                    <label>
                      <input
                        type="radio"
                        value="tag"
                        checked={batchUpdateData.prismCentral.updateType === 'tag'}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          prismCentral: { ...batchUpdateData.prismCentral, updateType: e.target.value }
                        })}
                      />
                      By Tag
                    </label>
                    <label>
                      <input
                        type="radio"
                        value="commit"
                        checked={batchUpdateData.prismCentral.updateType === 'commit'}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          prismCentral: { ...batchUpdateData.prismCentral, updateType: e.target.value }
                        })}
                      />
                      By Commit
                    </label>
                  </div>
                </div>

                <div className="form-group">
                  <label>Build Type</label>
                  <select
                    value={batchUpdateData.prismCentral.buildType}
                    onChange={(e) => setBatchUpdateData({ 
                      ...batchUpdateData, 
                      prismCentral: { ...batchUpdateData.prismCentral, buildType: e.target.value }
                    })}
                  >
                    <option value="">-- Select Build Type (Optional) --</option>
                    <option value="release">release</option>
                    <option value="opt">opt</option>
                  </select>
                </div>

                {batchUpdateData.prismCentral.updateType === 'tag' && (
                  <div className="form-group">
                    <label>Tag</label>
                    <select
                      value={batchUpdateData.prismCentral.tag}
                      onChange={(e) => setBatchUpdateData({ 
                        ...batchUpdateData, 
                        prismCentral: { ...batchUpdateData.prismCentral, tag: e.target.value }
                      })}
                    >
                      <option value="">-- Select Tag (Optional) --</option>
                      <option value="Latest Smoke Passed">Latest Smoke Passed</option>
                      <option value="Latest DIAL Passed">Latest DIAL Passed</option>
                    </select>
                  </div>
                )}

                {batchUpdateData.prismCentral.updateType === 'commit' && (
                  <>
                    <div className="form-group">
                      <label>Commit ID</label>
                      <input
                        type="text"
                        value={batchUpdateData.prismCentral.commitId}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          prismCentral: { ...batchUpdateData.prismCentral, commitId: e.target.value }
                        })}
                        placeholder="e.g., cd8cd937b6288cf2c58a44a0bc1c58d85bf5c0bb"
                      />
                    </div>
                    <div className="form-group">
                      <label>GBN</label>
                      <input
                        type="text"
                        value={batchUpdateData.prismCentral.gbn}
                        onChange={(e) => setBatchUpdateData({ 
                          ...batchUpdateData, 
                          prismCentral: { ...batchUpdateData.prismCentral, gbn: e.target.value }
                        })}
                        placeholder="e.g., 1764602295"
                      />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          {/* Common fields for both Tag and Commit */}
          <div className="form-group">
            <label>Nutest Branch Name</label>
            <input
              type="text"
              value={batchUpdateData.nutestBranch}
              onChange={(e) => setBatchUpdateData({ ...batchUpdateData, nutestBranch: e.target.value })}
              placeholder="e.g., ganges-7.5-stable"
            />
            <small>Optional: Update nutest branch for all job profiles</small>
          </div>
          <div className="form-group">
            <label>Patch URL</label>
            <input
              type="text"
              value={batchUpdateData.patchUrl}
              onChange={(e) => setBatchUpdateData({ ...batchUpdateData, patchUrl: e.target.value })}
              placeholder="e.g., https://nugerrit.ntnxdpro.com/changes/..."
            />
            <small>Optional: Test patch URL</small>
          </div>
          <div className="form-group">
            <label>Framework Patch URL</label>
            <input
              type="text"
              value={batchUpdateData.frameworkPatchUrl}
              onChange={(e) => setBatchUpdateData({ ...batchUpdateData, frameworkPatchUrl: e.target.value })}
              placeholder="e.g., https://nugerrit.ntnxdpro.com/changes/..."
            />
            <small>Optional: Framework patch URL</small>
          </div>

          {/* Tester Tags Management (Optional) */}
          <div className="form-group" style={{ marginTop: '30px', paddingTop: '20px', borderTop: '1px solid #ddd' }}>
            <label style={{ fontWeight: 'bold', fontSize: '16px' }}>Tester Tags Management (Optional)</label>
            <div className="form-group">
              <label>Action</label>
              <select
                value={batchUpdateData.testerTagsAction}
                onChange={(e) => setBatchUpdateData({ ...batchUpdateData, testerTagsAction: e.target.value })}
              >
                <option value="">-- Select Action --</option>
                <option value="add">Add Tag</option>
                <option value="remove">Remove Tag</option>
              </select>
              <small>Select to add or remove a tag from tester_tags</small>
            </div>
            {batchUpdateData.testerTagsAction && (
              <div className="form-group">
                <label>Tag Value</label>
                <input
                  type="text"
                  value={batchUpdateData.testerTagValue}
                  onChange={(e) => setBatchUpdateData({ ...batchUpdateData, testerTagValue: e.target.value })}
                  placeholder="e.g., minor, container__unlimited, v3.1"
                />
                <small>Enter the tag name to {batchUpdateData.testerTagsAction === 'add' ? 'add' : 'remove'}</small>
              </div>
            )}
          </div>

          {/* Additional Tags (run_tests_with_additional_tags) */}
          <div className="form-group" style={{ marginTop: '30px', paddingTop: '20px', borderTop: '1px solid #ddd' }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={batchUpdateData.updateAdditionalTags}
                onChange={(e) => setBatchUpdateData({
                  ...batchUpdateData,
                  updateAdditionalTags: e.target.checked,
                  additionalTags: e.target.checked ? batchUpdateData.additionalTags : []
                })}
              />
              <span style={{ fontWeight: 'bold', fontSize: '16px' }}>
                Update Additional Tags (run_tests_with_additional_tags)
              </span>
            </label>
            <small style={{ display: 'block', marginTop: '4px', color: '#888' }}>
              Enable to overwrite <code>run_tests_with_additional_tags</code> on all job profiles in this run plan.
            </small>

            {batchUpdateData.updateAdditionalTags && (
              <div style={{ marginTop: '12px' }}>
                <div className="additional-tags-picker" ref={additionalTagsRef}>
                  <button
                    type="button"
                    className="additional-tags-trigger"
                    onClick={() => setShowAdditionalTagsDropdown(v => !v)}
                  >
                    {batchUpdateData.additionalTags.length > 0
                      ? `${batchUpdateData.additionalTags.length} tag(s) selected`
                      : 'Disabled (empty list)'}
                    <span className="additional-tags-arrow">{showAdditionalTagsDropdown ? '▴' : '▾'}</span>
                  </button>

                  {showAdditionalTagsDropdown && (
                    <div className="additional-tags-dropdown">
                      <label className="additional-tags-option additional-tags-disable-all">
                        <input
                          type="checkbox"
                          checked={batchUpdateData.additionalTags.length === 0}
                          onChange={() => setBatchUpdateData({ ...batchUpdateData, additionalTags: [] })}
                        />
                        Disable All (empty list)
                      </label>
                      <div className="additional-tags-divider" />
                      {ADDITIONAL_TAG_OPTIONS.map(tag => (
                        <label key={tag} className="additional-tags-option">
                          <input
                            type="checkbox"
                            checked={batchUpdateData.additionalTags.includes(tag)}
                            onChange={() => toggleAdditionalTag(tag)}
                          />
                          {tag}
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                {batchUpdateData.additionalTags.length > 0 && (
                  <div className="additional-tags-selected">
                    {batchUpdateData.additionalTags.map(tag => (
                      <span key={tag} className="additional-tag-chip">
                        {tag}
                        <button
                          type="button"
                          onClick={() => toggleAdditionalTag(tag)}
                          className="additional-tag-remove"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                    <button
                      type="button"
                      className="additional-tags-clear"
                      onClick={() => setBatchUpdateData({ ...batchUpdateData, additionalTags: [] })}
                    >
                      Clear all
                    </button>
                  </div>
                )}

                <small style={{ color: '#e67e22', marginTop: '6px', display: 'block' }}>
                  This will <strong>overwrite</strong> existing additional tags on all selected job profiles.
                  {batchUpdateData.additionalTags.length === 0 && ' Leaving empty will clear all additional tags.'}
                </small>
              </div>
            )}
          </div>

          <div className="form-actions">
            <button onClick={() => setView('list')}>Cancel</button>
            <button className="btn-primary" onClick={handleExecuteBatchUpdate} disabled={loading}>
              {loading ? 'Updating...' : 'Execute Batch Update'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Render History View
  if (view === 'history') {
    return (
      <div className="run-plan-container">
        <div className="run-plan-header">
          <h1>Run Plan History - {selectedRunPlan?.name}</h1>
          <button onClick={() => setView('list')}>← Back to List</button>
        </div>

        {loading ? (
          <div className="loading">Loading...</div>
        ) : (
          <table className="run-plan-table">
            <thead>
              <tr>
                <th>Trigger Date/Time</th>
                <th>Task IDs</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {historyData.length === 0 ? (
                <tr>
                  <td colSpan="4" className="empty-state">No history found</td>
                </tr>
              ) : (
                historyData.map((entry) => (
                  <tr key={entry.id}>
                    <td>{entry.triggered_at}</td>
                    <td>
                      {entry.task_ids?.length > 0 ? (
                        <a
                          href={`https://jita.eng.nutanix.com/results?task_ids=${entry.task_ids.join(',')}&active_tab=1&merge_tests=true`}
                          target="_blank"
                          rel="noreferrer"
                          style={{ color: '#3498db', textDecoration: 'none', fontSize: '13px' }}
                          onMouseEnter={(e) => e.target.style.textDecoration = 'underline'}
                          onMouseLeave={(e) => e.target.style.textDecoration = 'none'}
                        >
                          {entry.task_ids.length} task{entry.task_ids.length > 1 ? 's' : ''} — View in JITA
                        </a>
                      ) : (
                        <span style={{ color: '#7f8c8d' }}>-</span>
                      )}
                    </td>
                    <td>
                      <span className={`status-badge ${entry.status?.toLowerCase()}`}>
                        {entry.status || 'Unknown'}
                      </span>
                    </td>
                    <td>
                      <div className="action-buttons">
                        <button onClick={() => handleRetryTrigger(entry.id)}>Retry</button>
                        <button onClick={() => handleDeleteHistory(entry.id)}>Delete</button>
                        {entry.task_ids?.length > 0 && (
                          <button
                            onClick={() => handleKillTasks(entry.id, entry.task_ids.length)}
                            style={{ background: '#e74c3c', color: 'white' }}
                          >
                            Kill All Tasks
                          </button>
                        )}
                        <button 
                          onClick={() => handleCreateTriageGenieJob(entry)}
                          style={{ background: '#27ae60', color: 'white' }}
                        >
                          Create New Job
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}
      </div>
    );
  }

  // Render Calendar View
  if (view === 'calendar') {
    const days = getDaysInMonth(calendarMonth);
    const monthLabel = calendarMonth.toLocaleString('default', { month: 'long', year: 'numeric' });
    const todayStr = fmtDate(new Date());
    const selectedDateStr = selectedCalendarDate ? fmtDate(selectedCalendarDate) : null;
    const selectedEvents = selectedDateStr ? eventsForDate(selectedDateStr) : [];

    return (
      <div className="run-plan-container">
        <div className="run-plan-header">
          <h1>Run Plan Calendar</h1>
          <button onClick={() => setView('list')}>← Back to List</button>
        </div>

        {loading ? (
          <div className="loading">Loading...</div>
        ) : (
          <div className="calendar-wrapper">
            {/* Month navigation */}
            <div className="calendar-nav">
              <button onClick={() => setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1, 1))}>◀ Prev</button>
              <h2>{monthLabel}</h2>
              <button onClick={() => setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 1))}>Next ▶</button>
            </div>

            {/* Calendar grid */}
            <div className="calendar-grid">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
                <div key={d} className="calendar-day-header">{d}</div>
              ))}
              {days.map((dayObj, idx) => {
                if (!dayObj) return <div key={`pad-${idx}`} className="calendar-cell empty" />;
                const ds = fmtDate(dayObj);
                const dayEvents = eventsForDate(ds);
                const triggered = dayEvents.filter((e) => e.type === 'triggered');
                const scheduled = dayEvents.filter((e) => e.type === 'scheduled');
                const isToday = ds === todayStr;
                const isSelected = ds === selectedDateStr;

                return (
                  <div
                    key={ds}
                    className={`calendar-cell${isToday ? ' today' : ''}${isSelected ? ' selected' : ''}${dayEvents.length ? ' has-events' : ''}`}
                    onClick={() => handleCalendarDateClick(dayObj)}
                  >
                    <span className="calendar-date-num">{dayObj.getDate()}</span>
                    {triggered.length > 0 && (
                      <span className="cal-badge triggered">{triggered.length} run{triggered.length > 1 ? 's' : ''}</span>
                    )}
                    {scheduled.length > 0 && (
                      <span className="cal-badge scheduled">{scheduled.length} sched</span>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Detail panel for selected date */}
            {selectedCalendarDate && (
              <div className="calendar-detail">
                <div className="calendar-detail-header">
                  <h3>{selectedCalendarDate.toDateString()}</h3>
                  <button className="btn-primary" onClick={handleOpenScheduleDialog}>
                    + Schedule a Run Plan
                  </button>
                </div>

                {/* Schedule dialog */}
                {scheduleDialogOpen && (
                  <div className="schedule-dialog">
                    <h4>Schedule Run Plan on {selectedCalendarDate.toDateString()}</h4>
                    <div className="form-group" style={{ marginBottom: 12 }}>
                      <label>Select Run Plan</label>
                      <select
                        value={scheduleForm.runPlanId}
                        onChange={(e) => setScheduleForm({ ...scheduleForm, runPlanId: e.target.value })}
                      >
                        <option value="">-- Pick a Run Plan --</option>
                        {calendarRunPlans.map((rp) => (
                          <option key={rp.id} value={rp.id}>{rp.name}</option>
                        ))}
                      </select>
                    </div>
                    <div className="form-group" style={{ marginBottom: 12 }}>
                      <label>Time</label>
                      <input
                        type="time"
                        value={scheduleForm.time}
                        onChange={(e) => setScheduleForm({ ...scheduleForm, time: e.target.value })}
                      />
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button className="btn-primary" onClick={handleScheduleFromCalendar} disabled={!scheduleForm.runPlanId || loading}>
                        {loading ? 'Scheduling...' : 'Schedule'}
                      </button>
                      <button onClick={() => setScheduleDialogOpen(false)}>Cancel</button>
                    </div>
                  </div>
                )}

                {/* Events list */}
                {selectedEvents.length === 0 && !scheduleDialogOpen && (
                  <p style={{ color: '#7f8c8d' }}>No events on this date.</p>
                )}

                {selectedEvents.filter(e => e.type === 'triggered').length > 0 && (
                  <div className="cal-event-section">
                    <h4 className="cal-section-title triggered-title">Triggered Runs</h4>
                    {selectedEvents.filter(e => e.type === 'triggered').map((ev, i) => (
                      <div key={`t-${i}`} className="cal-event-card triggered-card">
                        <div className="cal-event-name">{ev.run_plan_name}</div>
                        <div className="cal-event-meta">
                          <span>At: {ev.datetime}</span>
                          <span>By: {ev.triggered_by || 'N/A'}</span>
                          <span className={`status-badge ${ev.status?.toLowerCase()}`}>{ev.status}</span>
                        </div>
                        {ev.task_ids?.length > 0 && (
                          <div className="cal-event-tasks">
                            <a
                              href={`https://jita.eng.nutanix.com/results?task_ids=${ev.task_ids.join(',')}&active_tab=1&merge_tests=true`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {ev.task_ids.length} task{ev.task_ids.length > 1 ? 's' : ''} — View in JITA
                            </a>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}

                {selectedEvents.filter(e => e.type === 'scheduled').length > 0 && (
                  <div className="cal-event-section">
                    <h4 className="cal-section-title scheduled-title">Scheduled Runs</h4>
                    {selectedEvents.filter(e => e.type === 'scheduled').map((ev, i) => (
                      <div key={`s-${i}`} className="cal-event-card scheduled-card">
                        <div className="cal-event-name">{ev.run_plan_name}</div>
                        <div className="cal-event-meta">
                          <span>Scheduled for: {ev.datetime}</span>
                          <span>{ev.schedule_triggered ? 'Already triggered' : 'Pending'}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return null;
}
