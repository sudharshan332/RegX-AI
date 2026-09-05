import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import { API_BASE_URL } from '../config';
import { normalizeAuthUser } from '../utils/authUser';

const AuthContext = createContext(null);

const TOKEN_KEY = 'regx_auth_token';
const AUTH_API = `${API_BASE_URL}/mcp/regression/auth`;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [loading, setLoading] = useState(true);

  const clearAuth = useCallback(() => {
    setUser(null);
    setToken(null);
    localStorage.removeItem(TOKEN_KEY);
  }, []);

  // Validate existing token on mount
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    axios
      .get(`${AUTH_API}/me`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      .then((res) => {
        // JWT payload uses sub/name; normalize so UI always has username/displayName/name
        setUser(normalizeAuthUser(res.data.user));
      })
      .catch(() => {
        clearAuth();
      })
      .finally(() => {
        setLoading(false);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const login = useCallback(async (username, password, team) => {
    const res = await axios.post(`${AUTH_API}/login`, { username, password, team });
    const { token: newToken, user: newUser } = res.data;
    // LDAP login returns displayName/username (not name/sub) — normalize before state
    const normalized = normalizeAuthUser(newUser);
    // Add team to normalized user
    normalized.team = team;
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
    setUser(normalized);
    return normalized;
  }, []);

  const logout = useCallback(() => {
    clearAuth();
  }, [clearAuth]);

  const value = {
    user,
    token,
    loading,
    isAuthenticated: !!user && !!token,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
