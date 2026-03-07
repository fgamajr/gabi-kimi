import { Suspense, lazy } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AppShell } from "./components/AppShell";

const HomePage = lazy(() => import("./pages/HomePage"));
const SearchPage = lazy(() => import("./pages/SearchPage"));
const DocumentPage = lazy(() => import("./pages/DocumentPage"));
const NotFound = lazy(() => import("./pages/NotFound"));

const queryClient = new QueryClient();

const RouteFallback = () => (
  <div className="min-h-screen bg-background px-4 py-8">
    <div className="mx-auto max-w-4xl space-y-3 animate-pulse">
      <div className="h-12 rounded-2xl bg-card border border-border" />
      <div className="grid gap-3 md:grid-cols-3">
        <div className="h-28 rounded-2xl bg-card border border-border" />
        <div className="h-28 rounded-2xl bg-card border border-border" />
        <div className="h-28 rounded-2xl bg-card border border-border" />
      </div>
      <div className="h-64 rounded-2xl bg-card border border-border" />
    </div>
  </div>
);

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<HomePage />} />
              <Route path="/search" element={<SearchPage />} />
              <Route path="/document/:id" element={<DocumentPage />} />
              <Route path="/doc/:id" element={<DocumentPage />} />
            </Route>
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
