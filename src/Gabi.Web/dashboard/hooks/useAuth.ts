import { useState, useEffect, useCallback } from 'react';
import { api } from '../lib/api-client';

interface AuthState {
  isAuthenticated: boolean;
  token: string | null;
  role: string | null;
  isLoading: boolean;
  error: string | null;
}

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(payload);
  } catch {
    return null;
  }
}

export function useAuth() {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    token: null,
    role: null,
    isLoading: true,
    error: null,
  });

  useEffect(() => {
    const token = api.getToken();
    if (token) {
      const payload = decodeJwtPayload(token);
      const role = (payload?.role as string) ?? (payload?.['http://schemas.microsoft.com/ws/2008/06/identity/claims/role'] as string) ?? null;
      setState({
        isAuthenticated: true,
        token,
        role,
        isLoading: false,
        error: null,
      });
    } else {
      setState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setState(prev => ({ ...prev, isLoading: true, error: null }));

    try {
      const response = await api.login(username, password);

      if (response.success && response.token) {
        api.setToken(response.token);
        setState({
          isAuthenticated: true,
          token: response.token,
          role: response.role,
          isLoading: false,
          error: null,
        });
        return true;
      } else {
        setState(prev => ({
          ...prev,
          isLoading: false,
          error: response.error || 'Login failed',
        }));
        return false;
      }
    } catch (err) {
      setState(prev => ({
        ...prev,
        isLoading: false,
        error: err instanceof Error ? err.message : 'Unknown error',
      }));
      return false;
    }
  }, []);

  const logout = useCallback(() => {
    api.setToken(null);
    setState({
      isAuthenticated: false,
      token: null,
      role: null,
      isLoading: false,
      error: null,
    });
  }, []);

  return {
    ...state,
    login,
    logout,
  };
}
