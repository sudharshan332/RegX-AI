import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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

const HANDOVER_ROW = {
  test_name: 'cdp.foo.test_handover',
  handover_date: '2026-09-21T12:56:53.207178',
  lst_file: 'regression_cdp.lst',
  lst_files: ['regression_cdp.lst'],
  branch: 'master',
  handover_tickets: ['ENG-123'],
  tickets: [],
  bug_tickets: ['ENG-999'],
  bug_type: 'Product Bug',
  reviewers: ['swapnil.wankhede@nutanix.com'],
  by_whom: 'alice@nutanix.com',
  notes: 'Handover CR requested via RegX.',
  cr_status: 'creating',
  cr_subject: 'Testcase Handover',
  cr_description: 'Reviewers : swapnil',
  can_delete: true,
};

const DEPRECATION_ROW = {
  test_name: 'cdp.bar.test_deprecation',
  deprecation_date: '2026-09-21T18:27:50.347996',
  lst_file: 'regression_cdp_robo.lst',
  branch: 'master',
  jira_tickets: ['ENT-124312'],
  reviewers: ['swapnil.wankhede@nutanix.com'],
  by_whom: 'unknown',
  notes: 'Deprecation CR requested via RegX.',
  cr_status: 'pending_manual',
  commit_message: 'Deprecated 1 test(s)',
  can_delete: false,
};

describe('Handover Records tab', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.alert = jest.fn();
    window.confirm = jest.fn(() => true);
    authState.user = { email: 'alice@nutanix.com', username: 'alice', name: 'Alice' };
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/handover-records')) {
        return Promise.resolve({ data: { results: [HANDOVER_ROW], count: 1 } });
      }
      if (path.includes('/deprecation-records')) {
        return Promise.resolve({ data: { results: [DEPRECATION_ROW], count: 1 } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  test('header has Handover, Deprecation, and Records tabs', () => {
    render(<Handover />);
    expect(screen.getByRole('tab', { name: 'Handover' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Deprecation' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Records' })).toBeInTheDocument();
  });

  test('deprecation tab has search and CR fields but no records table', () => {
    render(<Handover />);
    fireEvent.click(screen.getByRole('tab', { name: 'Deprecation' }));
    expect(screen.getByText(/Saved rows live under the Records tab/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Test name/i)).toBeInTheDocument();
    expect(screen.queryByText(/Found .*handover record/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('columnheader', { name: /By whom/i })).not.toBeInTheDocument();
  });

  test('records tab lists handover and deprecation fields and extra details', async () => {
    render(<Handover />);
    fireEvent.click(screen.getByRole('tab', { name: 'Records' }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    expect(api.post.mock.calls.some(([url]) => String(url).includes('/handover-records'))).toBe(true);
    expect(api.post.mock.calls.some(([url]) => String(url).includes('/deprecation-records'))).toBe(true);

    expect(await screen.findByText('cdp.foo.test_handover')).toBeInTheDocument();
    expect(screen.getByText('cdp.bar.test_deprecation')).toBeInTheDocument();
    expect(screen.getByText('regression_cdp.lst')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Tickets' })).toBeInTheDocument();
    expect(screen.queryByText(/Handover \/ Jira tickets/i)).not.toBeInTheDocument();
    expect(screen.getByText('ENG-123')).toBeInTheDocument();
    expect(screen.getByText('ENT-124312')).toBeInTheDocument();
    expect(screen.getByText('ENG-999')).toBeInTheDocument();
    expect(screen.getByText('Product Bug')).toBeInTheDocument();
    expect(screen.getAllByText('swapnil wankhede').length).toBeGreaterThan(0);
    expect(screen.getByText('creating')).toBeInTheDocument();
    expect(screen.getByText('pending_manual')).toBeInTheDocument();

    screen.getAllByRole('button', { name: 'Details' }).forEach((btn) => fireEvent.click(btn));
    expect(screen.getByText('Handover CR requested via RegX.')).toBeInTheDocument();
    expect(screen.getByText('Deprecation CR requested via RegX.')).toBeInTheDocument();
    expect(screen.getByText('Testcase Handover')).toBeInTheDocument();
    expect(screen.getByText('Deprecated 1 test(s)')).toBeInTheDocument();
  });

  test('non-owner does not see Edit or Delete', async () => {
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/handover-records')) {
        return Promise.resolve({ data: { results: [{ ...HANDOVER_ROW, can_delete: false }], count: 1 } });
      }
      if (path.includes('/deprecation-records')) {
        return Promise.resolve({ data: { results: [DEPRECATION_ROW], count: 1 } });
      }
      return Promise.resolve({ data: {} });
    });
    render(<Handover />);
    fireEvent.click(screen.getByRole('tab', { name: 'Records' }));
    await screen.findByText('cdp.foo.test_handover');
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Details' }).length).toBeGreaterThan(0);
  });

  test('edit mode deletes only rows the user can_delete', async () => {
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/handover-records')) {
        return Promise.resolve({ data: { results: [HANDOVER_ROW], count: 1 } });
      }
      if (path.includes('/deprecation-records')) {
        return Promise.resolve({ data: { results: [DEPRECATION_ROW], count: 1 } });
      }
      if (path.includes('/handover-record-delete')) {
        return Promise.resolve({ data: { success: true } });
      }
      return Promise.resolve({ data: {} });
    });
    render(<Handover />);
    fireEvent.click(screen.getByRole('tab', { name: 'Records' }));
    await screen.findByText('cdp.foo.test_handover');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const ownerRow = screen.getByText('cdp.foo.test_handover').closest('tr');
    const otherRow = screen.getByText('cdp.bar.test_deprecation').closest('tr');
    expect(within(ownerRow).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(within(otherRow).queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument();
    fireEvent.click(within(ownerRow).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByText('cdp.foo.test_handover')).not.toBeInTheDocument());
    expect(screen.getByText('cdp.bar.test_deprecation')).toBeInTheDocument();
    expect(api.post.mock.calls.some(([url]) => String(url).includes('/handover-record-delete'))).toBe(true);
  });

  test('admin can_delete on unknown rows shows Delete', async () => {
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/handover-records')) {
        return Promise.resolve({ data: { results: [{ ...HANDOVER_ROW, can_delete: true }], count: 1 } });
      }
      if (path.includes('/deprecation-records')) {
        return Promise.resolve({ data: { results: [{ ...DEPRECATION_ROW, can_delete: true }], count: 1 } });
      }
      return Promise.resolve({ data: {} });
    });
    render(<Handover />);
    fireEvent.click(screen.getByRole('tab', { name: 'Records' }));
    await screen.findByText('cdp.bar.test_deprecation');
    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    const row = screen.getByText('cdp.bar.test_deprecation').closest('tr');
    expect(within(row).getByRole('button', { name: 'Delete' })).toBeInTheDocument();
  });
});
