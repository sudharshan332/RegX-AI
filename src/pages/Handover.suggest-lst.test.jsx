import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import Handover from './Handover';
import api from '../api';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

const authState = {
  user: { email: 'alice@nutanix.com', username: 'alice', name: 'Alice' },
};

jest.mock('../context/AuthContext', () => ({
  useAuth: () => authState,
}));

const FAILED_PRODUCT_BUG_TEST =
  'cdp.zookeeper.zk_preupgrade_checks.test_preupgradechecks.TestPreUpgradeChecks.test_preupgrade_checks';

describe('Handover LST suggestion for Product Bug tests', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.alert = jest.fn();
    api.get.mockResolvedValue({ data: { results: [] } });
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/jita-analysis')) {
        return Promise.resolve({
          data: {
            all_tests_passed: false,
            total_executions: 5,
            total_passed: 0,
            history_window: 5,
            branch: 'master',
            test_cases: [
              {
                test_name: FAILED_PRODUCT_BUG_TEST,
                status: 'failed',
                passed_count: 0,
                total_count: 5,
                jira_tickets: ['ENG-912212'],
                bug_type: 'Product Bug',
                eligibility_reason: 'product_bug_gap',
              },
            ],
          },
        });
      }
      if (path.includes('/validate-jira-ticket')) {
        return Promise.resolve({
          data: { valid: true, ticket: 'ENG-912212', issuetype: 'Bug', bug_type: 'Product Bug' },
        });
      }
      if (path.includes('/suggest-lst-file')) {
        return Promise.resolve({
          data: {
            suggested_lst_file: 'test_sets/milestones/7.3.0.98/zookeeper.lst',
            candidates: [{ lst_file: 'test_sets/milestones/7.3.0.98/zookeeper.lst', count: 1 }],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  async function fetchFailedProductBugTest() {
    render(<Handover />);
    fireEvent.change(screen.getByPlaceholderText(/JITA URL/i), {
      target: { value: FAILED_PRODUCT_BUG_TEST },
    });
    fireEvent.change(screen.getByPlaceholderText('master'), { target: { value: 'master' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fetch' }));
    await waitFor(() => expect(screen.getByText(/Selected Test Cases for Handover/i)).toBeInTheDocument());
  }

  test('Product Bug tests skip Check Override and show Ready for CR', async () => {
    await fetchFailedProductBugTest();
    await waitFor(() => expect(screen.getByText(/Ready for CR/i)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'Check Override' })).not.toBeInTheDocument();
    expect(screen.queryByText(/Override \(Only with Product Bugs\)/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Refresh Suggestion' }));
    await waitFor(() =>
      expect(api.post.mock.calls.some(([url, body]) =>
        String(url).includes('/suggest-lst-file')
        && body.test_names.includes(FAILED_PRODUCT_BUG_TEST)
        && body.branch === 'master'
      )).toBe(true)
    );
    expect(window.alert).not.toHaveBeenCalledWith(expect.stringMatching(/passed testcase/i));
    expect(api.post.mock.calls.some(([url]) => String(url).includes('/validate-jira-ticket'))).toBe(true);
  });

  test('editing a ticket after Product Bug validation hides Ready for CR', async () => {
    await fetchFailedProductBugTest();
    await waitFor(() => expect(screen.getByText(/Ready for CR/i)).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText(/Jira ticket/i), { target: { value: 'ENG-000000' } });
    expect(screen.queryByText(/Ready for CR/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check Override' })).not.toBeInTheDocument();
  });
});
