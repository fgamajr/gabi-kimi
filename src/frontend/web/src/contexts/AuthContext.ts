import { createContext } from "react";

interface AuthContextValue {
  user: import("@/types").User | null;
  role: import("@/types").UserRole;
  roles: import("@/types").UserRole[];
  isAdmin: boolean;
  isLoading: boolean;
  login: (accessKey: string) => Promise<void>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);
