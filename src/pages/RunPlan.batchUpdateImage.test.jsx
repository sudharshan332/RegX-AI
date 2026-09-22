import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import RunPlan from './RunPlan';
import { TaskProvider } from '../context/TaskContext';
import api from '../api';

jest.mock('../api', () => ({
  __esModule: true,
  default: { get: jest.fn(), post: jest.fn() },
}));

jest.mock('../components/AiMarkdown', () => ({
  __esModule: true,
  default: () => null,
}));

const PLAN = {
  id: 'rp-1',
  name: 'CDP_Regression_Test',
  branch: '7.6',
  job_profiles: ['jp-1'],
};

function renderRunPlan() {
  return render(
    <TaskProvider>
      <RunPlan />
    </TaskProvider>
  );
}

describe('Run Plan Batch Update Image Branch', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    window.alert = jest.fn();
    window.confirm = jest.fn(() => true);
    api.get.mockResolvedValue({ data: { run_plans: [PLAN] } });
    api.post.mockResolvedValue({ data: { updated_count: 1, failed_updates: [] } });
  });

  const openBatchUpdate = async () => {
    renderRunPlan();
    await screen.findByText('CDP_Regression_Test');
    fireEvent.click(screen.getAllByRole('button', { name: 'Batch Update' })[0]);
    expect(screen.getByText('Batch Update Job Profiles')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Image Branch'));
    return screen.getByRole('heading', { name: 'Image Branch' }).closest('div');
  };

  test('shows branch, build type, and By Tag dropdown', async () => {
    const panel = await openBatchUpdate();

    expect(within(panel).getByPlaceholderText('e.g., ganges-7.6.0.6-stable')).toBeInTheDocument();
    expect(within(panel).getByText('Image Build Type')).toBeInTheDocument();
    expect(within(panel).getByLabelText('By Tag')).toBeInTheDocument();
    expect(within(panel).getByLabelText('By Commit')).toBeInTheDocument();

    fireEvent.click(within(panel).getByLabelText('By Tag'));
    const tagSelect = within(panel).getByDisplayValue('-- Select Tag (Optional) --');
    expect(within(tagSelect).getByText('Latest Smoke Passed')).toBeInTheDocument();
    expect(within(tagSelect).getByText('Latest Build Passed')).toBeInTheDocument();
  });

  test('By Commit shows Image Commit and Image GBN and posts IMAGE payload', async () => {
    const panel = await openBatchUpdate();

    fireEvent.change(within(panel).getByPlaceholderText('e.g., ganges-7.6.0.6-stable'), {
      target: { value: 'ganges-7.6.0.6-stable' },
    });
    fireEvent.change(within(panel).getByDisplayValue('-- Select Build Type (Optional) --'), {
      target: { value: 'release' },
    });
    fireEvent.click(within(panel).getByLabelText('By Commit'));
    fireEvent.change(within(panel).getByPlaceholderText(/fd96efb85c11ac75f282d51dce06e04a279bad2d/), {
      target: { value: '  abc123  ' },
    });
    fireEvent.change(within(panel).getByPlaceholderText('e.g., 1786602592'), {
      target: { value: '1786602592' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Execute Batch Update' }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [, payload] = api.post.mock.calls[0];
    expect(payload.components).toEqual([
      {
        component: 'IMAGE',
        branch: 'ganges-7.6.0.6-stable',
        update_type: 'commit',
        build_type: 'release',
        commit_id: 'abc123',
        gbn: '1786602592',
      },
    ]);
  });

  test('By Tag posts image_build_selection tag', async () => {
    const panel = await openBatchUpdate();

    fireEvent.change(within(panel).getByPlaceholderText('e.g., ganges-7.6.0.6-stable'), {
      target: { value: 'ganges-7.5.2-stable' },
    });
    fireEvent.click(within(panel).getByLabelText('By Tag'));
    fireEvent.change(within(panel).getByDisplayValue('-- Select Tag (Optional) --'), {
      target: { value: 'By Latest Smoke Passed' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Execute Batch Update' }));

    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [, payload] = api.post.mock.calls[0];
    expect(payload.components).toEqual([
      {
        component: 'IMAGE',
        branch: 'ganges-7.5.2-stable',
        update_type: 'tag',
        build_type: '',
        tag: 'By Latest Smoke Passed',
      },
    ]);
  });
});
