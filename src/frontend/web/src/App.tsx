import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { useEffect } from "react";
import { AuthProvider } from "@/hooks/useAuth";
import { ThemeProvider } from "@/hooks/useTheme";
import AppShell from "@/components/layout/AppShell";
import { I18nProvider } from "@/components/providers/I18nProvider";
import { RouteMetadata } from "@/components/RouteMetadata";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import { getAnalyticsViewQueryFn } from "@/hooks/useAnalytics";

import HomePage from "@/pages/HomePage";
const SearchPage = lazy(() => import("@/pages/SearchPage"));
const DocumentPage = lazy(() => import("@/pages/DocumentPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const FavoritosPage = lazy(() => import("@/pages/FavoritosPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const RegisterPage = lazy(() => import("@/pages/RegisterPage"));
const ForgotPasswordPage = lazy(() => import("@/pages/ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("@/pages/ResetPasswordPage"));
const ProfilePage = lazy(() => import("@/pages/ProfilePage"));
const UserSettingsPage = lazy(() => import("@/pages/UserSettingsPage"));
const AdminUsersPage = lazy(() => import("@/pages/AdminUsersPage"));
const AdminUploadPage = lazy(() => import("@/pages/AdminUploadPage"));
const AdminJobsPage = lazy(() => import("@/pages/AdminJobsPage"));
const PipelinePage = lazy(() => import("@/pages/PipelinePage"));
const NotFound = lazy(() => import("./pages/NotFound"));

const queryClient = new QueryClient();

const AppWarmup = () => {
  const client = useQueryClient();

  useEffect(() => {
    const view = typeof window !== "undefined" ? window : undefined;
    const scheduler =
      view && "requestIdleCallback" in view
        ? view.requestIdleCallback.bind(view)
        : (callback: IdleRequestCallback) => globalThis.setTimeout(() => callback({ didTimeout: false, timeRemaining: () => 0 } as IdleDeadline), 180);

    const handle = scheduler(() => {
      client.prefetchQuery({ queryKey: ["analytics"], queryFn: getAnalyticsViewQueryFn, staleTime: 3 * 60_000 }).catch(() => undefined);
    });

    return () => {
      if (view && "cancelIdleCallback" in view) {
        view.cancelIdleCallback(handle as number);
      } else {
        globalThis.clearTimeout(handle as number);
      }
    };
  }, [client]);

  return null;
};

const RouteFallback = () => (
  <div className="min-h-screen bg-background px-4 py-8">
    <div className="mx-auto max-w-5xl space-y-4 animate-pulse">
      <div className="h-12 rounded-2xl border border-border bg-card" />
      <div className="grid gap-4 md:grid-cols-3">
        <div className="h-28 rounded-2xl border border-border bg-card" />
        <div className="h-28 rounded-2xl border border-border bg-card" />
        <div className="h-28 rounded-2xl border border-border bg-card" />
      </div>
      <div className="h-72 rounded-[28px] border border-border bg-card" />
    </div>
  </div>
);

const App = () => (
  <QueryClientProvider client={queryClient}>
    <AppWarmup />
    <I18nProvider>
      <ThemeProvider>
      <AuthProvider>
        <TooltipProvider>
          <Toaster />
          <Sonner />
          <BrowserRouter>
            <RouteMetadata />
            <Suspense fallback={<RouteFallback />}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/cadastro" element={<RegisterPage />} />
                <Route path="/register" element={<RegisterPage />} />
                <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                <Route path="/reset-password" element={<ResetPasswordPage />} />
                <Route element={<AppShell />}>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/busca" element={<SearchPage />} />
                  <Route path="/search" element={<SearchPage />} />
                  <Route path="/documento/:id" element={<DocumentPage />} />
                  <Route path="/document/:id" element={<DocumentPage />} />
                  <Route path="/doc/:id" element={<DocumentPage />} />
                  <Route path="/analytics" element={<AnalyticsPage />} />
                  <Route path="/chat" element={<ChatPage />} />
                  <Route path="/perfil" element={<ProtectedRoute requiredRole="user"><ProfilePage /></ProtectedRoute>} />
                  <Route path="/configuracoes" element={<ProtectedRoute requiredRole="user"><UserSettingsPage /></ProtectedRoute>} />
                  <Route path="/favoritos" element={<FavoritosPage />} />
                  <Route path="/admin/users" element={<ProtectedRoute requiredRole="admin"><AdminUsersPage /></ProtectedRoute>} />
                  <Route path="/admin/upload" element={<ProtectedRoute requiredRole="admin"><AdminUploadPage /></ProtectedRoute>} />
                  <Route path="/admin/jobs" element={<ProtectedRoute requiredRole="admin"><AdminJobsPage /></ProtectedRoute>} />
                  <Route path="/pipeline" element={<ProtectedRoute requiredRole="admin"><PipelinePage /></ProtectedRoute>} />
                </Route>
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </TooltipProvider>
      </AuthProvider>
      </ThemeProvider>
    </I18nProvider>
  </QueryClientProvider>
);

export default App;
