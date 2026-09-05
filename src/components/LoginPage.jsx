import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useAuth } from '../context/AuthContext';
import { API_BASE_URL } from '../config';
import './LoginPage.css';

export default function LoginPage() {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [team, setTeam] = useState('');
  const [teams, setTeams] = useState([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [teamsLoading, setTeamsLoading] = useState(true);

  // Fetch available teams on mount
  useEffect(() => {
    const fetchTeams = async () => {
      try {
        const res = await axios.get(`${API_BASE_URL}/mcp/regression/teams`);
        const teamsList = res.data.teams || [];
        setTeams(teamsList);
        // Set default team if available
        if (res.data.default_team) {
          setTeam(res.data.default_team);
        } else if (teamsList.length > 0) {
          setTeam(teamsList[0].id);
        }
      } catch (err) {
        console.error('Failed to fetch teams:', err);
        setError('Failed to load teams. Please refresh the page.');
      } finally {
        setTeamsLoading(false);
      }
    };
    fetchTeams();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    
    if (!team) {
      setError('Please select a team');
      return;
    }
    
    setLoading(true);

    try {
      await login(username.trim(), password, team);
    } catch (err) {
      const msg =
        err.response?.data?.error || 'Login failed. Please check your credentials.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrapper">
      <div className="login-card">
        <div className="login-header">
          <h1>Regression Dashboard</h1>
          <p>Sign in with your Nutanix credentials</p>
        </div>
        <div className="login-body">
          {error && <div className="login-error">{error}</div>}
          <form onSubmit={handleSubmit}>
            <div className="login-field">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                type="text"
                placeholder="e.g. john.doe"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                required
                autoFocus
              />
            </div>
            <div className="login-field">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <div className="login-field">
              <label htmlFor="team">Team</label>
              <select
                id="team"
                value={team}
                onChange={(e) => setTeam(e.target.value)}
                required
                disabled={teamsLoading}
              >
                {teamsLoading ? (
                  <option value="">Loading teams...</option>
                ) : (
                  <>
                    <option value="">Select your team</option>
                    {teams.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name}
                      </option>
                    ))}
                  </>
                )}
              </select>
            </div>
            <button type="submit" className="login-btn" disabled={loading || teamsLoading}>
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>
          <div className="login-hint">
            Use your Nutanix LDAP / Active Directory credentials
          </div>
        </div>
      </div>
    </div>
  );
}
