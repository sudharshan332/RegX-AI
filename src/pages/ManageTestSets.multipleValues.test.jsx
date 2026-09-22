import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import ManageTestSets from './ManageTestSets';
import api from '../api';

jest.mock('../api', () => ({
  __esModule: true,
  default: { post: jest.fn() },
}));

const rowForKey = (key) => screen.getByText(key).closest('div').parentElement;

describe('ManageTestSets existing args with Multiple Values', () => {
  beforeEach(() => {
    api.post.mockReset();
    api.post.mockImplementation((url, body) => {
      if (String(url).includes('/dynamic-jp/search')) {
        return Promise.resolve({
          data: {
            test_sets: [
              { _id: 'ts1', name: 'TS_One' },
              { _id: 'ts2', name: 'TS_Two' },
            ],
          },
        });
      }
      if (String(url).includes('/dynamic-jp/update')) {
        return Promise.resolve({ data: { results: { ts: { success: true } } } });
      }
      if (String(url).includes('/dynamic-jp/fetch-testset')) {
        const id = body?.testset_id;
        if (id === 'ts1') {
          return Promise.resolve({
            data: {
              test_set: {
                _id: 'ts1',
                name: 'TS_One',
                args_map: { retries: 1, cluster: 'A' },
                agave_options: { timeout: 10 },
              },
            },
          });
        }
        return Promise.resolve({
          data: {
            test_set: {
              _id: 'ts2',
              name: 'TS_Two',
              args_map: { retries: 1, cluster: 'B' },
              agave_options: { timeout: 10 },
            },
          },
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  const searchAndSelectBoth = async () => {
    render(<ManageTestSets embedded />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'TS_' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText('TS_One');
    fireEvent.click(screen.getByText('TS_One'));
    fireEvent.click(screen.getByText('TS_Two'));
    await screen.findByText('cluster');
  };

  test('shows differing values comma-separated and allows overwrite', async () => {
    await searchAndSelectBoth();

    expect(screen.getByText(/overwrites it on every selected test set/i)).toBeInTheDocument();

    const conflictRow = rowForKey('cluster');
    const conflictCheckbox = within(conflictRow).getByRole('checkbox');
    const conflictInput = within(conflictRow).getByDisplayValue('A, B');
    expect(conflictCheckbox).toBeEnabled();
    expect(conflictInput).toBeDisabled();

    fireEvent.click(conflictCheckbox);
    expect(conflictCheckbox).toBeChecked();
    const editInput = within(conflictRow).getByRole('textbox');
    expect(editInput).toBeEnabled();
    expect(editInput).toHaveValue('');
    expect(editInput).toHaveAttribute('placeholder', 'A, B');
    fireEvent.change(editInput, { target: { value: 'C' } });
    expect(editInput).toHaveValue('C');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply Changes' })).toBeEnabled();
    });
  });

  test('apply overwrites the differing key on each selected test set', async () => {
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    await searchAndSelectBoth();
    const conflictRow = rowForKey('cluster');
    fireEvent.click(within(conflictRow).getByRole('checkbox'));
    fireEvent.change(within(conflictRow).getByRole('textbox'), { target: { value: 'C' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await waitFor(() => {
      const updateCalls = api.post.mock.calls.filter(([url]) => String(url).includes('/dynamic-jp/update'));
      expect(updateCalls).toHaveLength(2);
      const clusters = updateCalls.map(([, body]) => body.updates.ts_updates.args_map.cluster);
      expect(clusters).toEqual(['C', 'C']);
    });
    confirmSpy.mockRestore();
  });

  test('still allows editing args that share one value', async () => {
    await searchAndSelectBoth();

    const sharedRow = rowForKey('retries');
    const sharedCheckbox = within(sharedRow).getByRole('checkbox');
    expect(sharedCheckbox).toBeEnabled();
    fireEvent.click(sharedCheckbox);
    const sharedInput = within(sharedRow).getByRole('textbox');
    expect(sharedInput).toBeEnabled();
    fireEvent.change(sharedInput, { target: { value: '5' } });
    expect(sharedInput).toHaveValue('5');
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Apply Changes' })).toBeEnabled();
    });
  });
});
