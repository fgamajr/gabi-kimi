import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAdminAnalyticsStatus,
  getAdminRoles,
  getAdminUsers,
  issueAdminUserToken,
  refreshAdminAnalyticsCache,
  revokeAdminToken,
  updateAdminUserRoles,
  upsertAdminUser,
  type AdminAnalyticsRefreshResult,
  type AdminAnalyticsStatus,
  type AdminTokenIssueRequest,
  type AdminUserRolesRequest,
  type AdminUserUpsertRequest,
} from "@/lib/api";

export function useAdminRoles() {
  return useQuery({
    queryKey: ["admin", "roles"],
    queryFn: getAdminRoles,
  });
}

export function useAdminUsers() {
  return useQuery({
    queryKey: ["admin", "users"],
    queryFn: getAdminUsers,
  });
}

export function useAdminAnalyticsStatus() {
  return useQuery<AdminAnalyticsStatus>({
    queryKey: ["admin", "analytics-status"],
    queryFn: getAdminAnalyticsStatus,
    refetchOnWindowFocus: false,
  });
}

export function useUpsertAdminUser() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AdminUserUpsertRequest) => upsertAdminUser(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }).catch(() => undefined);
    },
  });
}

export function useUpdateAdminUserRoles() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: AdminUserRolesRequest }) =>
      updateAdminUserRoles(userId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }).catch(() => undefined);
    },
  });
}

export function useIssueAdminToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ userId, payload }: { userId: string; payload: AdminTokenIssueRequest }) =>
      issueAdminUserToken(userId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }).catch(() => undefined);
    },
  });
}

export function useRevokeAdminToken() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (tokenId: string) => revokeAdminToken(tokenId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] }).catch(() => undefined);
    },
  });
}

export function useRefreshAdminAnalyticsCache() {
  const queryClient = useQueryClient();
  return useMutation<AdminAnalyticsRefreshResult>({
    mutationFn: () => refreshAdminAnalyticsCache(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "analytics-status"] }).catch(() => undefined);
    },
  });
}
