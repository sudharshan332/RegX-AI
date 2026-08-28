import React, { useState, useEffect, useCallback } from 'react';
import RegressionHome from './RegressionHome';
import RunPlan from './pages/RunPlan';
import Handover from './pages/Handover';
import TestcaseManagement from './pages/TestcaseManagement';
import TriageGenie from './pages/TriageGenie';
import RunReport from './pages/RunReport';
import DynamicJobProfile from './pages/DynamicJobProfile';
import FailedTestcaseAnalysis from './pages/FailedTestcaseAnalysis';
import CursorAI from './pages/CursorAI';
import { TaskProvider } from './context/TaskContext';
import { AuthProvider, useAuth } from './context/AuthContext';
import TaskStatusIcon from './components/TaskStatusIcon';
import LoginPage from './components/LoginPage';
import { resolveDisplayName } from './utils/authUser';
import './App.css';

const PAGE_COMPONENTS = {
  home: RegressionHome,
  'run-plan': RunPlan,
  handover: Handover,
  testcase: TestcaseManagement,
  'triage-genie': TriageGenie,
  'failed-analysis': FailedTestcaseAnalysis,
  'run-report': RunReport,
  'job-profile': DynamicJobProfile,
  'cursor-ai': CursorAI,
};

function Dashboard() {
  const { user, logout } = useAuth();
  const [activePage, setActivePage] = useState('home');
  const [visitedPages, setVisitedPages] = useState(() => ['home']);
  const [menuVisible, setMenuVisible] = useState(true);

  const navigateToPage = useCallback((pageId) => {
    const id = PAGE_COMPONENTS[pageId] ? pageId : 'home';
    setActivePage(id);
    setVisitedPages((prev) => (prev.includes(id) ? prev : [...prev, id]));
  }, []);

  useEffect(() => {
    const handleSetActivePage = (event) => {
      navigateToPage(event.detail);
    };
    window.addEventListener('setActivePage', handleSetActivePage);
    return () => {
      window.removeEventListener('setActivePage', handleSetActivePage);
    };
  }, [navigateToPage]);

  const menuItems = [
    { id: 'home', label: 'Home', icon: '🏠', description: 'Regression Overview' },
    { id: 'run-plan', label: 'Run Plan', icon: '📅', description: 'Regression Scheduling' },
    { id: 'handover', label: 'Handover', icon: '📤', description: 'New Testcase Onboarding' },
    { id: 'testcase', label: 'Testcase Management', icon: '📋', description: 'Testcase Management' },
    { id: 'triage-genie', label: 'Triage Genie', icon: '🤖', description: 'Automated Failure Triage' },
    { id: 'failed-analysis', label: 'Failed Testcase Analysis', icon: '🔍', description: 'AI-Powered Failure Analysis' },
    { id: 'run-report', label: 'Run Report', icon: '📊', description: 'QI Analysis' },
    { id: 'job-profile', label: 'Manage Job Profile', icon: '⚙️', description: 'Create, clone, delete & release-migrate JPs' },
    { id: 'cursor-ai', label: 'Cursor AI', icon: '✨', description: 'Interactive AI Chat' },
  ];

  const displayName = resolveDisplayName(user);
  const openSidebarSettings = () => {
    navigateToPage('cursor-ai');
    setTimeout(() => {
      window.dispatchEvent(new CustomEvent('openCursorAiSettings'));
    }, 0);
  };

  return (
    <TaskProvider>
      <div className="app-container">
        <nav className={`sidebar ${menuVisible ? '' : 'collapsed'}`}>
          <div className="sidebar-header">
            <h2>Regression Dashboard</h2>
            <button
              className="menu-toggle-btn"
              onClick={() => setMenuVisible(!menuVisible)}
              title={menuVisible ? 'Hide Menu' : 'Show Menu'}
            >
              {menuVisible ? '◀' : '▶'}
            </button>
          </div>
          <ul className="menu-list">
            {menuItems.map((item) => (
              <li
                key={item.id}
                className={`menu-item ${activePage === item.id ? 'active' : ''}`}
                onClick={() => navigateToPage(item.id)}
              >
                <span className="menu-icon">{item.icon}</span>
                <div className="menu-content">
                  <span className="menu-label">{item.label}</span>
                  <span className="menu-description">{item.description}</span>
                </div>
              </li>
            ))}
          </ul>
          <div className="sidebar-user-info">
            <div className="sidebar-user-meta">
              <span
                className="sidebar-user-name"
                title={user?.email || user?.username || displayName}
              >
                {displayName}
              </span>
              <button
                className="sidebar-settings-btn"
                onClick={openSidebarSettings}
                title="Open Cursor AI settings"
                aria-label="Open Cursor AI settings"
              >
                ⚙
              </button>
            </div>
            <button className="sidebar-logout-btn" onClick={logout} title="Sign out">
              Logout
            </button>
          </div>
        </nav>

        {!menuVisible && (
          <button
            className="floating-menu-toggle"
            onClick={() => setMenuVisible(true)}
            title="Show Menu"
          >
            ☰
          </button>
        )}

        <main className={`main-content ${menuVisible ? '' : 'expanded'}`}>
          {visitedPages.map((id) => {
            const PageComponent = PAGE_COMPONENTS[id];
            if (!PageComponent) return null;
            const isActive = activePage === id;
            return (
              <div
                key={id}
                className={`page-pane${isActive ? ' is-active' : ''}`}
                hidden={!isActive}
                aria-hidden={!isActive}
              >
                <PageComponent />
              </div>
            );
          })}
        </main>

        <TaskStatusIcon />
      </div>
    </TaskProvider>
  );
}

function AppGate() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="login-wrapper" style={{ color: 'rgba(255,255,255,0.6)', fontSize: 16 }}>
        Loading...
      </div>
    );
  }

  return isAuthenticated ? <Dashboard /> : <LoginPage />;
}

function App() {
  return (
    <AuthProvider>
      <AppGate />
    </AuthProvider>
  );
}

export default App;
