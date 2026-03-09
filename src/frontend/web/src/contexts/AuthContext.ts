import { createContext } from "react";

interface AuthContextValue {
  user: import("@/types").User | null;
  role: import("@/types").UserRole;
  roles: import("@/types").UserRole[];
  isAdmin: boolean;
  isLoading: boolean;
  login: (accessKey: string) => Promise<void>;
  loginWithPassword: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
