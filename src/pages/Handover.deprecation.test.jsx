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

async function searchDeprecation(testName = 'pkg.Test.test_foo') {
  fireEvent.click(screen.getByRole('tab', { name: 'Deprecation' }));
  fireEvent.change(screen.getByPlaceholderText(/Test name/i), { target: { value: testName } });
  fireEvent.click(screen.getByRole('button', { name: 'Search' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Validate LST' })).toBeInTheDocument());
}

describe('Deprecation multi LST selection', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.alert = jest.fn();
    api.get.mockResolvedValue({ data: { results: [] } });
    api.post.mockImplementation((url) => {
      const path = String(url);
      if (path.includes('/deprecation-search')) {
        return Promise.resolve({
          data: {
            results: [],
            count: 0,
            queries: ['pkg.Test.test_foo'],
            sourcegraph_first_repo: [{ path: 'auto-filled.lst' }],
            sourcegraph_other_repos: [],
          },
        });
      }
      if (path.includes('/suggest-lst-file')) {
        return Promise.resolve({
          data: {
            suggested_lst_file: 'test_sets/foo.lst',
            candidates: [
              { lst_file: 'test_sets/foo.lst', count: 1 },
              { lst_file: 'test_sets/bar.lst', count: 1 },
            ],
          },
        });
      }
      if (path.includes('/deprecate-lst-cr')) {
        return Promise.resolve({ data: { success: true, message: 'CR created', cr_url: 'https://gerrit.example/1' } });
      }
      if (path.includes('/deprecation-record')) {
        return Promise.resolve({ data: { success: true, message: 'Deprecation saved.' } });
      }
      if (path.includes('/check-lst-testcases')) {
        return Promise.resolve({ data: { present: ['pkg.Test.test_foo'], not_present: [], test_names: ['pkg.Test.test_foo'] } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  test('search does not auto-fill an LST path and Validate stays disabled', async () => {
    render(<Handover />);
    await searchDeprecation();

    expect(screen.getByPlaceholderText(/Optional typed path/i)).toHaveValue('');
    expect(screen.queryByText('auto-filled.lst')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Validate LST' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Create Gerrit CR' })).toBeDisabled();
    expect(api.post.mock.calls.some(([url]) => String(url).includes('/deprecation-search'))).toBe(true);
  });

  test('typed LST path does not count until Add LST', async () => {
    render(<Handover />);
    await searchDeprecation();
    fireEvent.change(screen.getByPlaceholderText('master'), { target: { value: 'master' } });
    fireEvent.change(screen.getByPlaceholderText(/Optional typed path/i), {
      target: { value: 'typed.lst' },
    });
    expect(screen.getByRole('button', { name: 'Validate LST' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Add LST' }));
    expect(screen.getByRole('button', { name: 'Validate LST' })).toBeEnabled();
    expect(screen.getByText('typed.lst')).toBeInTheDocument();
  });

  test('clicking two candidates selects both and Create CR sends lst_files', async () => {
    render(<Handover />);
    await searchDeprecation();
    fireEvent.change(screen.getByPlaceholderText('master'), { target: { value: 'master' } });

    await waitFor(() => expect(screen.getByRole('button', { name: /test_sets\/foo\.lst/ })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Validate LST' })).toBeDisabled();
    expect(screen.getByText(/Click to select suggested LST files/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /test_sets\/foo\.lst/ }));
    fireEvent.click(screen.getByRole('button', { name: /test_sets\/bar\.lst/ }));

    expect(screen.getByRole('button', { name: 'Validate LST' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Create Gerrit CR' })).toBeEnabled();

    fireEvent.click(screen.getByRole('button', { name: 'Create Gerrit CR' }));
    await waitFor(() => {
      expect(api.post.mock.calls.some(([url]) => String(url).includes('/deprecate-lst-cr'))).toBe(true);
    });
    const crCall = api.post.mock.calls.find(([url]) => String(url).includes('/deprecate-lst-cr'));
    expect(crCall[1].lst_files).toEqual(['test_sets/foo.lst', 'test_sets/bar.lst']);
    expect(crCall[1].lst_file).toBe('test_sets/foo.lst');
    expect(crCall[1].branch).toBe('master');
    expect(crCall[1].test_names).toEqual(['pkg.Test.test_foo']);

    const recordCall = api.post.mock.calls.find(([url]) => String(url).includes('/deprecation-record'));
    expect(recordCall[1].lst_files).toEqual(['test_sets/foo.lst', 'test_sets/bar.lst']);
  });
});
