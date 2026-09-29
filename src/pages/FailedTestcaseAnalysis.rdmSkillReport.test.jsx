import { textOrEmpty, triageModalAnalysisText, rdmMcpHealthBanners, rdmRecommendedActionLabel } from './FailedTestcaseAnalysis';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

describe('textOrEmpty / triageModalAnalysisText', () => {
  test('returns strings and numbers, ignores nested analysis objects', () => {
    expect(textOrEmpty('Foundation imaging failed')).toBe('Foundation imaging failed');
    expect(textOrEmpty(12)).toBe('12');
    expect(textOrEmpty({
      classification: 'Infra Issue',
      confidence: 'High',
      failing_code: {},
      related_components: [],
      root_cause: 'nested',
      suggested_fix: 'fix',
    })).toBe('');
    expect(textOrEmpty(['ENG-1'])).toBe('');
  });

  test('prefers string root_cause over nested analysis object for View report', () => {
    const modal = {
      kind: 'rdm_skill',
      analysis: {
        classification: 'Infra Issue',
        confidence: 'High',
        failing_code: {},
        related_components: [],
        root_cause: 'should not render as child',
        suggested_fix: 'fix',
      },
      root_cause: 'Pool exhaustion on nested AHV',
      ai_summary: 'summary',
    };
    expect(triageModalAnalysisText(modal)).toBe('Pool exhaustion on nested AHV');
  });

  test('uses string analysis for first-level AI', () => {
    expect(triageModalAnalysisText({
      kind: 'first_level',
      analysis: 'Exception matches ENG-12345',
    })).toBe('Exception matches ENG-12345');
  });
});

describe('rdmMcpHealthBanners / rdmRecommendedActionLabel', () => {
  test('returns glean and sourcegraph banners when MCP is down', () => {
    const banners = rdmMcpHealthBanners({
      glean: { ok: false, status: 'unavailable' },
      sourcegraph: 'unavailable',
    });
    expect(banners.map(b => b.key)).toEqual(['glean', 'sourcegraph']);
    expect(banners[0].title).toBe('Glean MCP unavailable');
    expect(banners[1].title).toBe('Sourcegraph MCP unavailable');
  });

  test('returns no banners when MCP is healthy', () => {
    expect(rdmMcpHealthBanners({
      glean: { ok: true, status: 'ok' },
      sourcegraph: 'ok',
    })).toEqual([]);
  });

  test('labels ticket decisions for the RDM skill card', () => {
    expect(rdmRecommendedActionLabel({
      recommended_action: 'link_existing',
      jira_ticket: 'DIAL-23079',
    })).toBe('Link DIAL-23079');
    expect(rdmRecommendedActionLabel({
      recommended_action: 'create_jira',
      suggested_jira_project: 'DIAL',
    })).toBe('Create DIAL ticket');
    expect(rdmRecommendedActionLabel({ recommended_action: 'rerun' })).toBe('Rerun');
  });
});
