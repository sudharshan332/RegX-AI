import React, { useState, useEffect } from 'react';
import RegressionHome from './RegressionHome';
import RunPlan from './pages/RunPlan';
import Handover from './pages/Handover';
import TestcaseManagement from './pages/TestcaseManagement';
import TriageGenie from './pages/TriageGenie';
import RunReport from './pages/RunReport';
import DynamicJobProfile from './pages/DynamicJobProfile';
import ManageJobProfile from './pages/ManageJobProfile';
import FailedTestcaseAnalysis from './pages/FailedTestcaseAnalysis';
import './App.css';

function App() {
  const [activePage, setActivePage] = useState('home');
  const [menuVisible, setMenuVisible] = useState(true);

  // Listen for navigation events from Run Plan
  useEffect(() => {
    const handleSetActivePage = (event) => {
      setActivePage(event.detail);
    };
    
    window.addEventListener('setActivePage', handleSetActivePage);
    
    return () => {
      window.removeEventListener('setActivePage', handleSetActivePage);
    };
  }, []);

  // Listen for navigation events from Run Plan
  useEffect(() => {
    const handleSetActivePage = (event) => {
      setActivePage(event.detail);
    };
    
    window.addEventListener('setActivePage', handleSetActivePage);
    
    return () => {
      window.removeEventListener('setActivePage', handleSetActivePage);
    };
  }, []);

  const menuItems = [
    { id: 'home', label: 'Home', icon: '🏠', description: 'Regression Overview' },
    { id: 'run-plan', label: 'Run Plan', icon: '📅', description: 'Regression Scheduling' },
    { id: 'handover', label: 'Handover', icon: '📤', description: 'New Testcase Onboarding' },
    { id: 'testcase', label: 'Testcase Management', icon: '📋', description: 'Testcase Management' },
    { id: 'triage-genie', label: 'Triage Genie', icon: '🤖', description: 'Automated Failure Triage' },
    { id: 'failed-analysis', label: 'Failed Testcase Analysis', icon: '🔍', description: 'AI-Powered Failure Analysis' },
    { id: 'run-report', label: 'Run Report', icon: '📊', description: 'QI Analysis' },
    { id: 'job-profile', label: 'Dynamic Job Profile', icon: '⚙️', description: 'Job Profile Creation' },
    { id: 'manage-jp', label: 'Manage JP / TS', icon: '🗑️', description: 'Search & Delete JP/TS' },
  ];

  const renderPage = () => {
    switch (activePage) {
      case 'home':
        return <RegressionHome />;
      case 'run-plan':
        return <RunPlan />;
      case 'handover':
        return <Handover />;
      case 'testcase':
        return <TestcaseManagement />;
      case 'triage-genie':
        return <TriageGenie />;
      case 'failed-analysis':
        return <FailedTestcaseAnalysis />;
      case 'run-report':
        return <RunReport />;
      case 'job-profile':
        return <DynamicJobProfile />;
      case 'manage-jp':
        return <ManageJobProfile />;
      default:
        return <RegressionHome />;
    }
  };

  return (
    <div className="app-container">
      {/* Navigation Sidebar */}
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
              onClick={() => setActivePage(item.id)}
            >
              <span className="menu-icon">{item.icon}</span>
              <div className="menu-content">
                <span className="menu-label">{item.label}</span>
                <span className="menu-description">{item.description}</span>
              </div>
            </li>
          ))}
        </ul>
      </nav>

      {/* Floating Toggle Button (when menu is hidden) */}
      {!menuVisible && (
        <button
          className="floating-menu-toggle"
          onClick={() => setMenuVisible(true)}
          title="Show Menu"
        >
          ☰
        </button>
      )}

      {/* Main Content Area */}
      <main className={`main-content ${menuVisible ? '' : 'expanded'}`}>
        {renderPage()}
      </main>
    </div>
  );
}

export default App;
