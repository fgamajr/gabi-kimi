import { useContext, useState, useCallback, useEffect, type ReactNode } from "react";
import type { User, UserRole } from "@/types";
import {
  clearAccessSession,
  createAccessSession,
  getSessionStatus,
  ApiAuthError,
  type SessionStatus,
} from "@/lib/auth";
import {
  loginWithPassword as apiLoginWithPassword,
  registerUser,
} from "@/lib/authApi";
import { AuthContext } from "@/contexts/AuthContext";
import { clearCachedValue, readCachedValue, writeCachedValue } from "@/lib/clientCache";

const SESSION_CACHE_KEY = "session-status";
const SESSION_CACHE_TTL_MS = 5 * 60 * 1000;

function normalizeRoles(input: string[] | undefined): UserRole[] {
  const normalized = new Set<UserRole>();
  for (const value of input || []) {
    const role = value === "admin" ? "admin" : value === "user" ? "user" : null;
    if (role) normalized.add(role);
  }
  return normalized.size > 0 ? Array.from(normalized) : ["user"];
}

function buildUserFromSession(session: SessionStatus): User | null {
  if (!session.authenticated) return null;
  const label = session.principal?.label?.trim() || "Acesso GABI";
  const source = session.principal?.source?.trim() || "session";
  const roles = normalizeRoles(session.principal?.roles);
  const role: UserRole = roles.includes("admin") ? "admin" : "user";
  const now = new Date().toISOString();
  return {
    id: session.principal?.user_id?.trim() || `${source}:${label}`.toLowerCase().replace(/\s+/g, "-"),
    userId: session.principal?.user_id?.trim() || undefined,
    name: label,
    email: session.principal?.email?.trim() || `${source}@gabi.local`,
    role,
    roles,
    createdAt: now,
    lastLoginAt: now,
    status: session.principal?.status === "suspended" ? "suspended" : "active",
    sessionSource: source,
    isServiceAccount: source === "bearer" || source === "session",
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(() => buildUserFromSession(readCachedValue<SessionStatus>(SESSION_CACHE_KEY) ?? { authenticated: false }));
  const [isLoading, setIsLoading] = useState(() => !readCachedValue<SessionStatus>(SESSION_CACHE_KEY));

  const refreshSession = useCallback(async () => {
    try {
      const session = await getSessionStatus();
      writeCachedValue(SESSION_CACHE_KEY, session, SESSION_CACHE_TTL_MS);
      setUser(buildUserFromSession(session));
    } catch (error) {
      if (error instanceof ApiAuthError) {
        clearCachedValue(SESSION_CACHE_KEY);
        setUser(null);
        return;
      }
      throw error;
    }
  }, []);

  useEffect(() => {
    refreshSession()
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));

    const handleAuthChange = () => {
      refreshSession().catch(() => setUser(null));
    };
    window.addEventListener("gabi-auth-changed", handleAuthChange);
    return () => window.removeEventListener("gabi-auth-changed", handleAuthChange);
  }, [refreshSession]);

  const login = useCallback(async (accessKey: string) => {
    const session = await createAccessSession(accessKey);
    writeCachedValue(SESSION_CACHE_KEY, session, SESSION_CACHE_TTL_MS);
    setUser(buildUserFromSession(session));
  }, []);

  const loginWithPassword = useCallback(async (email: string, password: string) => {
    const session = await apiLoginWithPassword(email, password);
    writeCachedValue(SESSION_CACHE_KEY, session, SESSION_CACHE_TTL_MS);
    setUser(buildUserFromSession(session));
  }, []);

  const register = useCallback(async (email: string, password: string, displayName: string) => {
    const session = await registerUser({ email, password, display_name: displayName });
    writeCachedValue(SESSION_CACHE_KEY, session, SESSION_CACHE_TTL_MS);
    setUser(buildUserFromSession(session));
  }, []);

  const logout = useCallback(() => {
    clearAccessSession().catch(() => undefined);
    clearCachedValue(SESSION_CACHE_KEY);
    setUser(null);
  }, []);

  const role: UserRole = user?.role ?? "visitor";
  const roles: UserRole[] = user?.roles ?? [];
  const isAdmin = roles.includes("admin");

  return (
    <AuthContext.Provider value={{ user, role, roles, isAdmin, isLoading, login, loginWithPassword, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
