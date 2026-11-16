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

const PASSED_TEST = 'cdp.stargate.vdisk.test_vdisk.TestVdisk.test_basic';

describe('Handover save payload', () => {
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
            all_tests_passed: true,
            total_executions: 5,
            total_passed: 5,
            history_window: 5,
            branch: 'master',
            test_cases: [
              {
                test_name: PASSED_TEST,
                status: 'succeeded',
                passed_count: 5,
                total_count: 5,
                jira_tickets: [],
              },
            ],
          },
        });
      }
      if (path.includes('/suggest-lst-file')) {
        return Promise.resolve({ data: { suggested_lst_file: '', candidates: [] } });
      }
      if (path.includes('/validate-lst')) {
        return Promise.resolve({
          data: { branch_valid: true, file_valid: true, resolved_branch: 'master' },
        });
      }
      if (path.includes('/handover-record')) {
        return Promise.resolve({ data: { success: true, message: 'Handover saved.' } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  test('Save sends the commit note and test owner', async () => {
    render(<Handover />);
    fireEvent.change(screen.getByPlaceholderText(/JITA URL/i), { target: { value: PASSED_TEST } });
    fireEvent.change(screen.getByPlaceholderText('master'), { target: { value: 'master' } });
    fireEvent.click(screen.getByRole('button', { name: 'Fetch' }));
    await waitFor(() => expect(screen.getByText(/Ready for CR/i)).toBeInTheDocument());

    fireEvent.change(screen.getByPlaceholderText(/test_sets\/milestones/i), {
      target: { value: 'test_sets/milestones/master/foo.lst' },
    });
    fireEvent.change(screen.getByPlaceholderText('ENG-123, ENG-456'), { target: { value: 'ENG-1' } });
    fireEvent.change(screen.getByPlaceholderText('CR subject'), { target: { value: 'note from user' } });
    fireEvent.change(screen.getByPlaceholderText('firstname.lastname'), { target: { value: 'qa.owner' } });

    fireEvent.click(screen.getByRole('button', { name: 'Validate LST' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.post.mock.calls.some(([url]) => String(url).includes('/handover-record'))).toBe(true);
    });
    const saveCall = api.post.mock.calls.find(([url]) => String(url).includes('/handover-record'));
    expect(saveCall[1].test_owner).toBe('qa.owner');
    expect(saveCall[1].cr_subject).toBe('note from user');
    expect(saveCall[1].commit_message.startsWith('note from user\n')).toBe(true);
    expect(saveCall[1].cr_description).not.toContain('note from user');
    expect(saveCall[1].lst_files).toContain('test_sets/milestones/master/foo.lst');
    expect(screen.getByRole('button', { name: 'Take handover' })).toBeEnabled();
  });
});
