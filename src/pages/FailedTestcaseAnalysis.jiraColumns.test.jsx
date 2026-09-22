import {
  categorizeJiraBugType,
  collectResultJiraTickets,
  jiraBugTypesForResult,
  jiraStatusesForResult,
  resultMatchesJiraBugTypes,
  resultMatchesJiraStatuses,
  JIRA_BUG_TYPE_OPTIONS,
} from './FailedTestcaseAnalysis';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

describe('Failed Testcase Analysis Jira columns', () => {
  const details = {
    'ENG-1': { status: 'Open', issue_type: 'Test', bug_type: 'Test Bug' },
    'ENG-2': { status: 'Closed', issue_type: 'Bug', bug_type: 'Product Bug' },
    'ENG-3': { status: 'In Progress', issue_type: 'Task', bug_type: null },
  };

  test('categorizes Jira issue types into test vs product bug', () => {
    expect(categorizeJiraBugType('Test')).toBe('Test Bug');
    expect(categorizeJiraBugType('Test Bug')).toBe('Test Bug');
    expect(categorizeJiraBugType('Bug')).toBe('Product Bug');
    expect(categorizeJiraBugType('Product Bug')).toBe('Product Bug');
  });

  test('joins types and statuses for multiple tagged tickets with commas', () => {
    const result = { jira_tickets: ['ENG-1', 'ENG-2'] };
    expect(jiraBugTypesForResult(result, details)).toEqual(['Test Bug', 'Product Bug']);
    expect(jiraStatusesForResult(result, details)).toEqual(['Open', 'Closed']);
    expect(collectResultJiraTickets(result)).toEqual(['ENG-1', 'ENG-2']);
  });

  test('bug type filter matches if any tagged ticket has the selected type', () => {
    const row = { jira_tickets: ['ENG-1', 'ENG-2'] };
    expect(resultMatchesJiraBugTypes(row, details, ['Test Bug'])).toBe(true);
    expect(resultMatchesJiraBugTypes(row, details, ['Environment'])).toBe(false);
    expect(resultMatchesJiraBugTypes(row, details, JIRA_BUG_TYPE_OPTIONS)).toBe(true);
    expect(resultMatchesJiraBugTypes({ jira_tickets: [] }, details, ['No Ticket'])).toBe(true);
  });

  test('status filter matches if any tagged ticket has the selected status', () => {
    const row = { jira_tickets: ['ENG-1', 'ENG-2'] };
    expect(resultMatchesJiraStatuses(row, details, ['Closed'])).toBe(true);
    expect(resultMatchesJiraStatuses(row, details, ['Resolved'])).toBe(false);
    expect(resultMatchesJiraStatuses({ jira_tickets: [] }, details, ['No Ticket'])).toBe(true);
  });

  test('uncategorized issue types count as Other', () => {
    expect(jiraBugTypesForResult({ jira_tickets: ['ENG-3'] }, details)).toEqual(['Other']);
  });
});
