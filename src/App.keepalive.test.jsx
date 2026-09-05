/**
 * Monkey tests for lazy keep-alive page navigation in App.jsx.
 * Stub pages track mount counts + local input state across random hops.
 */
import React, { useEffect, useState } from 'react';
import { render, screen, within, fireEvent, act } from '@testing-library/react';

const PAGE_IDS = [
  'home',
  'run-plan',
  'handover',
  'testcase',
  'triage-genie',
  'failed-analysis',
  'run-report',
  'job-profile',
  'cursor-ai',
];

const MENU_LABELS = {
  home: 'Home',
  'run-plan': 'Run Plan',
  handover: 'Handover',
  testcase: 'Testcase Management',
  'triage-genie': 'Triage Genie',
  'failed-analysis': 'Failed Testcase Analysis',
  'run-report': 'Run Report',
  'job-profile': 'Manage Job Profile',
  'cursor-ai': 'Cursor AI',
};

const mockMountCounts = Object.fromEntries(PAGE_IDS.map((id) => [id, 0]));

function mockMakeStubPage(pageId) {
  return function StubPage() {
    const [draft, setDraft] = useState('');
    useEffect(() => {
      mockMountCounts[pageId] += 1;
    }, []);
    return (
      <div data-testid={`page-${pageId}`}>
        <span data-testid={`mount-count-${pageId}`}>{mockMountCounts[pageId]}</span>
        <input
          data-testid={`draft-${pageId}`}
          aria-label={`${pageId}-draft`}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </div>
    );
  };
}

jest.mock('./RegressionHome', () => ({ __esModule: true, default: mockMakeStubPage('home') }));
jest.mock('./pages/RunPlan', () => ({ __esModule: true, default: mockMakeStubPage('run-plan') }));
jest.mock('./pages/Handover', () => ({ __esModule: true, default: mockMakeStubPage('handover') }));
jest.mock('./pages/TestcaseManagement', () => ({
  __esModule: true,
  default: mockMakeStubPage('testcase'),
}));
jest.mock('./pages/TriageGenie', () => ({
  __esModule: true,
  default: mockMakeStubPage('triage-genie'),
}));
jest.mock('./pages/RunReport', () => ({ __esModule: true, default: mockMakeStubPage('run-report') }));
jest.mock('./pages/DynamicJobProfile', () => ({
  __esModule: true,
  default: mockMakeStubPage('job-profile'),
}));
jest.mock('./pages/FailedTestcaseAnalysis', () => ({
  __esModule: true,
  default: mockMakeStubPage('failed-analysis'),
}));
jest.mock('./pages/CursorAI', () => ({ __esModule: true, default: mockMakeStubPage('cursor-ai') }));
jest.mock('./components/TaskStatusIcon', () => () => null);
jest.mock('./components/LoginPage', () => () => <div>login</div>);

jest.mock('./context/AuthContext', () => ({
  AuthProvider: ({ children }) => children,
  useAuth: () => ({
    user: { username: 'tester', displayName: 'Tester', email: 't@example.com' },
    token: 'test-token',
    loading: false,
    isAuthenticated: true,
    login: jest.fn(),
    logout: jest.fn(),
  }),
}));

import App from './App';

function clickMenu(pageId) {
  const label = MENU_LABELS[pageId];
  const labels = screen.getAllByText(label);
  const menuLabel = labels.find((el) => el.classList.contains('menu-label'));
  expect(menuLabel).toBeTruthy();
  const item = menuLabel.closest('.menu-item');
  expect(item).toBeTruthy();
  fireEvent.click(item);
}

function visiblePane(pageId) {
  const pane = screen.getByTestId(`page-${pageId}`).closest('.page-pane');
  expect(pane).toBeTruthy();
  return pane;
}

function assertOnlyActiveVisible(activeId) {
  PAGE_IDS.forEach((id) => {
    const pageEl = screen.queryByTestId(`page-${id}`);
    if (!pageEl) {
      expect(id).not.toBe(activeId);
      return;
    }
    const pane = pageEl.closest('.page-pane');
    if (id === activeId) {
      expect(pane).toHaveClass('is-active');
      expect(pane).not.toHaveAttribute('hidden');
      expect(pane).toHaveAttribute('aria-hidden', 'false');
    } else {
      expect(pane).not.toHaveClass('is-active');
      expect(pane).toHaveAttribute('hidden');
      expect(pane).toHaveAttribute('aria-hidden', 'true');
    }
  });
}

beforeEach(() => {
  PAGE_IDS.forEach((id) => {
    mockMountCounts[id] = 0;
  });
});

describe('App keep-alive page state (monkey)', () => {
  test('seeds home mounted once and visible', () => {
    render(<App />);
    expect(screen.getByTestId('page-home')).toBeInTheDocument();
    expect(mockMountCounts.home).toBe(1);
    assertOnlyActiveVisible('home');
    PAGE_IDS.filter((id) => id !== 'home').forEach((id) => {
      expect(screen.queryByTestId(`page-${id}`)).not.toBeInTheDocument();
    });
  });

  test('each page mounts once and draft survives leave/return', () => {
    render(<App />);

    for (const pageId of PAGE_IDS) {
      clickMenu(pageId);
      assertOnlyActiveVisible(pageId);

      const input = screen.getByTestId(`draft-${pageId}`);
      const marker = `KEEP-${pageId}-v1`;
      fireEvent.change(input, { target: { value: marker } });
      expect(input).toHaveValue(marker);

      const away = pageId === 'home' ? 'run-plan' : 'home';
      clickMenu(away);
      assertOnlyActiveVisible(away);
      clickMenu(pageId);
      assertOnlyActiveVisible(pageId);

      expect(screen.getByTestId(`draft-${pageId}`)).toHaveValue(marker);
      expect(mockMountCounts[pageId]).toBe(1);
    }

    PAGE_IDS.forEach((id) => {
      expect(mockMountCounts[id]).toBe(1);
      expect(screen.getByTestId(`page-${id}`)).toBeInTheDocument();
    });
  });

  test('random monkey hops preserve all drafts and never remount', async () => {
    render(<App />);

    const drafts = {};
    for (const pageId of PAGE_IDS) {
      clickMenu(pageId);
      const marker = `MONKEY-${pageId}-${Math.floor(Math.random() * 1e6)}`;
      drafts[pageId] = marker;
      fireEvent.change(screen.getByTestId(`draft-${pageId}`), {
        target: { value: marker },
      });
    }

    const path = [];
    for (let i = 0; i < 80; i += 1) {
      const next = PAGE_IDS[Math.floor(Math.random() * PAGE_IDS.length)];
      path.push(next);
      if (i % 7 === 0) {
        await act(async () => {
          window.dispatchEvent(new CustomEvent('setActivePage', { detail: next }));
        });
      } else {
        clickMenu(next);
      }
      assertOnlyActiveVisible(next);
    }

    for (const pageId of PAGE_IDS) {
      expect(mockMountCounts[pageId]).toBe(1);
      clickMenu(pageId);
      expect(screen.getByTestId(`draft-${pageId}`)).toHaveValue(drafts[pageId]);
    }

    // eslint-disable-next-line no-console
    console.log('monkey path sample:', path.slice(0, 20).join(' -> '), '...');
  });

  test('settings button keeps cursor-ai alive without remount', () => {
    render(<App />);

    clickMenu('cursor-ai');
    fireEvent.change(screen.getByTestId('draft-cursor-ai'), {
      target: { value: 'settings-draft' },
    });
    expect(mockMountCounts['cursor-ai']).toBe(1);

    clickMenu('handover');
    fireEvent.click(screen.getByLabelText('Open Cursor AI settings'));

    assertOnlyActiveVisible('cursor-ai');
    expect(screen.getByTestId('draft-cursor-ai')).toHaveValue('settings-draft');
    expect(mockMountCounts['cursor-ai']).toBe(1);
  });

  test('unknown setActivePage detail falls back to home without remounting home', async () => {
    render(<App />);
    clickMenu('handover');
    expect(mockMountCounts.home).toBe(1);

    await act(async () => {
      window.dispatchEvent(new CustomEvent('setActivePage', { detail: 'not-a-real-page' }));
    });

    assertOnlyActiveVisible('home');
    expect(mockMountCounts.home).toBe(1);
    expect(within(visiblePane('home')).getByTestId('draft-home')).toBeInTheDocument();
  });

  test('inactive panes are not focusable via hidden attribute', () => {
    render(<App />);
    clickMenu('handover');
    clickMenu('run-plan');

    const handoverPane = screen.getByTestId('page-handover').closest('.page-pane');
    const runPlanPane = screen.getByTestId('page-run-plan').closest('.page-pane');
    expect(handoverPane).toHaveAttribute('hidden');
    expect(runPlanPane).not.toHaveAttribute('hidden');
  });
});
