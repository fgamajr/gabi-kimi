import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import type { UserRole } from "@/types";

const ROLE_LEVEL: Record<UserRole, number> = { visitor: 0, user: 1, admin: 2 };

interface Props {
  requiredRole: UserRole;
  children: React.ReactNode;
}

export default function ProtectedRoute({ requiredRole, children }: Props) {
  const { user, role, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[100dvh]">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(location.pathname)}`} replace />;
  }

  if (ROLE_LEVEL[role] < ROLE_LEVEL[requiredRole]) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
