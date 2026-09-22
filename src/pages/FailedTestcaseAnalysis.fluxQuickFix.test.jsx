import {
  FLUX_MAX_WAIT_MS,
  fluxAnalysisComplete,
  fluxCanCreateGerritCr,
  fluxCategoryLabel,
  fluxConfidencePercent,
  fluxFirstJiraKey,
  fluxHasGerritCr,
  fluxHasRootCause,
  fluxIsRunning,
  fluxLatestStageMessage,
  fluxNutestTargetBranch,
  fluxPipelineError,
  fluxShouldPoll,
  fluxTaskUrl,
  hydrateFluxJobsFromMap,
  serializeFluxJobsMap,
} from './FailedTestcaseAnalysis';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

describe('Flux Quick Fix helpers', () => {
  test('uses the first Jira key on a row', () => {
    expect(fluxFirstJiraKey({ jira_tickets: [' ENG-1 ', 'ENG-2'] })).toBe('ENG-1');
    expect(fluxFirstJiraKey({ jira_tickets: [] })).toBe('');
    expect(fluxFirstJiraKey({})).toBe('');
  });

  test('formats confidence as a percent', () => {
    expect(fluxConfidencePercent(0.82)).toBe(82);
    expect(fluxConfidencePercent(1)).toBe(100);
    expect(fluxConfidencePercent(82)).toBe(82);
    expect(fluxConfidencePercent(null)).toBeNull();
  });

  test('labels product vs genuine test bug', () => {
    expect(fluxCategoryLabel('product_issue')).toBe('Product-side Issue');
    expect(fluxCategoryLabel('test_bug')).toBe('Genuine Test Bug');
    expect(fluxCategoryLabel('environment_issue')).toBe('Environment Issue');
  });

  test('Create Gerrit CR is only for genuine test bugs with RCA and confidence', () => {
    expect(fluxCanCreateGerritCr({
      status: 'failed',
      failure_category: 'test_bug',
      root_cause: 'Assertion in foo',
      confidence: 0.82,
    })).toBe(true);
    expect(fluxCanCreateGerritCr({
      status: 'awaiting_review',
      failure_category: 'product_issue',
      root_cause: 'Product crash',
      confidence: 0.82,
    })).toBe(false);
    expect(fluxCanCreateGerritCr({
      status: 'analyzing',
      failure_category: 'test_bug',
    })).toBe(false);
  });

  test('maps analysis branch to nutest git branch', () => {
    expect(fluxNutestTargetBranch({}, '7.5')).toBe('ganges-7.5-stable');
    expect(fluxNutestTargetBranch({}, 'ganges-7.5-stable')).toBe('ganges-7.5-stable');
    expect(fluxNutestTargetBranch({ 'nutest-py3-tests_branch': 'ganges-7.5-stable' }, 'master')).toBe('ganges-7.5-stable');
    expect(fluxNutestTargetBranch({}, 'master')).toBe('master');
    expect(fluxNutestTargetBranch({}, '')).toBe('');
  });

  test('idle rows without a Flux job are not running', () => {
    expect(fluxShouldPoll('', {}, {})).toBe(false);
    expect(fluxIsRunning('', {}, {})).toBe(false);
    expect(fluxIsRunning(undefined, {}, {})).toBe(false);
    expect(fluxShouldPoll('starting', {}, { status: 'starting' })).toBe(true);
    expect(fluxIsRunning('starting', {}, { status: 'starting' })).toBe(true);
  });

  test('keeps polling until root_cause even if Flux reports failed', () => {
    const job = { record_id: 22, startedAt: Date.now() };
    expect(fluxShouldPoll('queued', {}, job)).toBe(true);
    expect(fluxShouldPoll('analyzing', {}, job)).toBe(true);
    expect(fluxShouldPoll('failed', { status: 'failed' }, job)).toBe(true);
    expect(fluxIsRunning('failed', { status: 'failed' }, job)).toBe(true);
  });

  test('stops polling and surfaces pipeline error events immediately', () => {
    const job = { record_id: 23, startedAt: Date.now() };
    const ticket = {
      status: 'failed',
      task_events: [{
        type: 'error',
        message: 'Pipeline failed: RuntimeError: git fetch failed (rc=128): fatal: couldn\'t find remote ref refs/heads/ganges-7.5.2-stable',
        timestamp: '2026-09-15T22:41:44.359236+00:00',
        stage: 'failed',
      }],
    };
    expect(fluxPipelineError(ticket)).toContain('git fetch failed');
    expect(fluxShouldPoll('failed', ticket, job)).toBe(false);
    expect(fluxIsRunning('failed', ticket, job)).toBe(false);
  });

  test('stops polling after RCA for product issues, or when gerrit CR exists', () => {
    const job = { record_id: 22, startedAt: Date.now() };
    expect(fluxShouldPoll('failed', {
      status: 'failed',
      root_cause: 'Product crash',
      failure_category: 'product_issue',
    }, job)).toBe(false);
    expect(fluxHasGerritCr({
      gerrit_url: 'https://nugerrit/c/1',
      gerrit_change_id: 'Iabc',
    })).toBe(true);
    expect(fluxShouldPoll('fixing', {
      gerrit_url: 'https://nugerrit/c/1',
      gerrit_change_id: 'Iabc',
    }, job)).toBe(false);
  });

  test('stops polling after RCA for human review; resumes poll only after Create CR', () => {
    const job = { record_id: 22, startedAt: Date.now() };
    const rca = {
      status: 'failed',
      root_cause: 'Bad assert',
      failure_category: 'test_bug',
      confidence: 0.9,
    };
    expect(fluxHasRootCause(rca)).toBe(true);
    expect(fluxAnalysisComplete(rca)).toBe(true);
    expect(fluxShouldPoll('failed', rca, job)).toBe(false);
    expect(fluxShouldPoll('fixing', rca, { ...job, resumeAttempted: true })).toBe(true);
  });

  test('builds Flux task URL from record_id', () => {
    expect(fluxTaskUrl(21)).toBe('http://10.61.4.219/task/21');
    expect(fluxTaskUrl(21, 'http://example/task/21')).toBe('http://example/task/21');
    expect(fluxTaskUrl(null)).toBe('');
  });

  test('serializes and hydrates flux jobs for results JSON', () => {
    const jobs = {
      tc1: {
        record_id: 21,
        status: 'queued',
        initiate_response: { record_id: 21, status: 'queued', jira_key: 'ENG-1' },
        ticket: { record_id: 21, root_cause: 'x', confidence: 0.92, failure_category: 'test_bug' },
        startedAt: 123,
      },
    };
    const serialized = serializeFluxJobsMap(jobs);
    expect(serialized.tc1.record_id).toBe(21);
    expect(serialized.tc1.initiate_response.jira_key).toBe('ENG-1');
    const hydrated = hydrateFluxJobsFromMap(serialized);
    expect(hydrated.tc1.record_id).toBe(21);
    expect(hydrated.tc1.ticket.failure_category).toBe('test_bug');
  });

  test('stops polling after 15 minutes without RCA', () => {
    const job = { record_id: 22, startedAt: Date.now() - FLUX_MAX_WAIT_MS - 1000 };
    expect(fluxShouldPoll('failed', { status: 'failed' }, job)).toBe(false);
  });

  test('latest stage message comes from the last task event', () => {
    expect(fluxLatestStageMessage({
      status: 'analyzing',
      task_events: [
        { message: 'Ingesting issue from Jira' },
        { message: 'Analyzing with Cursor agent' },
      ],
    })).toBe('Analyzing with Cursor agent');
    expect(fluxLatestStageMessage({ status: 'queued' })).toBe('queued');
  });
});
