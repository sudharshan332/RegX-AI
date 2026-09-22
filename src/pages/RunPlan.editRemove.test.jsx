import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import RunPlan from './RunPlan';
import { TaskProvider } from '../context/TaskContext';
import api from '../api';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn(), put: jest.fn(), delete: jest.fn() },
}));

jest.mock('../components/AiMarkdown', () => ({
  __esModule: true,
  default: () => null,
}));

const PLAN = {
  id: 'rp-triggered',
  name: 'CDP_Regression_Upgrade',
  branch: '7.5.2',
  job_profiles: ['jp-keep', 'jp-drop'],
  last_triggered: '2026-08-28T08:02:52.331554',
  service_account: '',
  is_dummy: false,
};

const JP_KEEP = { _id: { $oid: 'jp-keep' }, name: 'Keep_JP', description: 'keep' };
const JP_DROP = { _id: { $oid: 'jp-drop' }, name: 'Drop_JP', description: 'drop' };

function renderRunPlan() {
  return render(
    <TaskProvider>
      <RunPlan />
    </TaskProvider>
  );
}

describe('Edit Run Plan Remove job profile', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    api.put.mockReset();
    window.alert = jest.fn();
    window.confirm = jest.fn(() => true);
    api.get.mockResolvedValue({ data: { run_plans: [PLAN] } });
    api.post.mockImplementation((url) => {
      if (String(url).includes('search-job-profiles')) {
        return Promise.resolve({ data: { job_profiles: [JP_KEEP, JP_DROP] } });
      }
      return Promise.resolve({ data: {} });
    });
    api.put.mockResolvedValue({ data: { success: true } });
  });

  test('Remove drops the row and Save PUTs the remaining job profiles', async () => {
    renderRunPlan();
    await screen.findByText('CDP_Regression_Upgrade');
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit' })[0]);

    await screen.findByText('Edit Run Plan');
    await screen.findAllByText('Drop_JP');

    const currentSection = screen.getByText('Current Job Profiles').closest('.form-group');
    const removeButtons = within(currentSection).getAllByRole('button', { name: 'Remove' });
    fireEvent.click(removeButtons[1]);

    expect(within(currentSection).queryByText('Drop_JP')).not.toBeInTheDocument();
    expect(within(currentSection).getByText('Keep_JP')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(api.put).toHaveBeenCalled());
    const [url, payload] = api.put.mock.calls[0];
    expect(url).toContain('/rp-triggered');
    expect(payload.job_profiles).toEqual(['jp-keep']);
  });
});
