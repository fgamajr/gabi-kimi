/**
 * Updated Dashboard Component
 * 
 * This shows the MINIMAL changes needed to integrate with the backend.
 * Copy the changes to: frontend/src/pages/Dashboard.tsx
 * 
 * Key changes:
 * 1. Replace mock imports with hooks
 * 2. Use useDashboardData() instead of useState(mockData)
 * 3. Handle loading and error states
 */

import { useState } from 'react';
import {
  Files,
  Database,
  Search,
  Activity,
  LayoutDashboard,
  Settings,
  FileText,
  History,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';

// OLD: Import mock data
// import { mockStats, mockJobs, mockPipelineStages, formatNumber, formatFullNumber } from '@/lib/dashboard-data';

// NEW: Import hooks and formatters
import { useDashboardData } from '@/hooks/useDashboard';
import { formatNumber, formatFullNumber } from '@/lib/dashboard-data';

// Import components
import { PipelineOverview } from '@/components/dashboard/PipelineOverview';
import { MetricCard } from '@/components/dashboard/MetricCard';
import { ActivityFeed } from '@/components/dashboard/ActivityFeed';
import { SourcesTable } from '@/components/dashboard/SourcesTable';
import { SystemHealth } from '@/components/dashboard/SystemHealth';

// NEW: Import loading and error components
import { DashboardSkeleton } from '@/components/loading/DashboardSkeleton';
import { ApiErrorFallback } from '@/components/error/ApiErrorFallback';

// Sidebar navigation items
const navItems = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard, active: true },
  { id: 'jobs', label: 'Jobs & Logs', icon: History, active: false },
  { id: 'documents', label: 'Documents', icon: FileText, active: false },
  { id: 'settings', label: 'Settings', icon: Settings, active: false },
];

export default function Dashboard() {
  // OLD: Use mock state
  // const [stats] = useState(mockStats);
  // const [jobs] = useState(mockJobs);
  // const [pipeline] = useState(mockPipelineStages);
  // const [lastUpdate] = useState(new Date().toISOString());

  // NEW: Use real data from API
  const {
    stats,
    frontendPipeline,
    frontendJobs,
    elasticsearchAvailable,
    isLoading,
    isError,
    isRefreshing,
    refetch,
    lastUpdate,
  } = useDashboardData();

  // State for UI interactions
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  // NEW: Handle refresh using API
  const handleRefresh = () => {
    refetch();
  };

  // NEW: Loading state
  if (isLoading) {
    return (
      <div className="min-h-screen flex bg-background">
        {/* Sidebar skeleton */}
        <aside className="fixed left-0 top-0 h-screen w-60 bg-sidebar border-r" />
        {/* Main content skeleton */}
        <main className="flex-1 min-h-screen ml-60">
          <DashboardSkeleton />
        </main>
      </div>
    );
  }

  // NEW: Error state
  if (isError || !stats) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <ApiErrorFallback
          error={new Error('Failed to load dashboard data')}
          reset={refetch}
          title="Dashboard Unavailable"
        />
      </div>
    );
  }

  // Calculate metrics from real data
  const activeSources = stats.active_sources || 0;
  const totalDocs = stats.total_documents || 0;
  const indexedDocs = stats.total_elastic_docs || 0;
  const totalChunks = stats.total_chunks || 0;

  return (
    <div className="min-h-screen flex bg-background">
      {/* Sidebar (unchanged) */}
      <aside
        className={cn(
          'fixed left-0 top-0 h-screen bg-sidebar text-sidebar-foreground',
          'border-r border-sidebar-border flex flex-col z-50',
          'transition-all duration-300 ease-out',
          sidebarCollapsed ? 'w-16' : 'w-60'
        )}
      >
        {/* Logo */}
        <div
          className={cn(
            'flex items-center h-16 px-4 border-b border-sidebar-border',
            sidebarCollapsed ? 'justify-center' : 'justify-between'
          )}
        >
          {!sidebarCollapsed && (
            <div className="flex items-center gap-2">
              <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-sidebar-primary">
                <Database className="h-4 w-4 text-sidebar-primary-foreground" />
              </div>
              <div>
                <h1 className="font-bold text-sidebar-foreground">GABI</h1>
                <p className="text-[10px] text-sidebar-foreground/60 -mt-0.5">WORLD</p>
              </div>
            </div>
          )}
          {sidebarCollapsed && (
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-sidebar-primary">
              <Database className="h-4 w-4 text-sidebar-primary-foreground" />
            </div>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg',
                  'text-sm font-medium transition-colors',
                  item.active
                    ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                    : 'text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent/50',
                  sidebarCollapsed && 'justify-center px-2'
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {!sidebarCollapsed && <span>{item.label}</span>}
              </button>
            );
          })}
        </nav>

        {/* Connection status */}
        <div
          className={cn(
            'p-4 border-t border-sidebar-border',
            sidebarCollapsed && 'flex justify-center'
          )}
        >
          <div
            className={cn(
              'flex items-center gap-2',
              sidebarCollapsed && 'flex-col'
            )}
          >
            <span
              className={cn(
                'w-2 h-2 rounded-full',
                elasticsearchAvailable
                  ? 'bg-status-online pulse-online'
                  : 'bg-status-error'
              )}
            />
            {!sidebarCollapsed && (
              <span className="text-xs text-sidebar-foreground/60">
                {elasticsearchAvailable ? 'Live Connection' : 'Connection Lost'}
              </span>
            )}
          </div>
        </div>

        {/* Collapse toggle */}
        <button
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-card border shadow-sm flex items-center justify-center hover:bg-accent transition-colors"
        >
          {sidebarCollapsed ? (
            <ChevronRight className="h-3 w-3 text-muted-foreground" />
          ) : (
            <ChevronLeft className="h-3 w-3 text-muted-foreground" />
          )}
        </button>
      </aside>

      {/* Main content */}
      <main
        className={cn(
          'flex-1 min-h-screen transition-all duration-300 ease-out',
          sidebarCollapsed ? 'ml-16' : 'ml-60'
        )}
      >
        {/* Header */}
        <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-sm border-b">
          <div className="flex items-center justify-between px-6 h-16">
            <div>
              <h1 className="text-xl font-semibold text-foreground">Dashboard</h1>
              <p className="text-sm text-muted-foreground">
                Monitor your document processing pipeline
              </p>
            </div>
            <SystemHealth
              elasticsearch={elasticsearchAvailable}
              lastUpdate={lastUpdate}
              isRefreshing={isRefreshing}
              onRefresh={handleRefresh}
            />
          </div>
        </header>

        {/* Dashboard content */}
        <div className="p-6 space-y-6">
          {/* Metrics row - UPDATED with real data */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="fade-in stagger-1">
              <MetricCard
                title="Total Documents"
                value={formatNumber(totalDocs)}
                subtitle={formatFullNumber(totalDocs) + ' total'}
                icon={Files}
                variant="primary"
                trend={{ value: 12, label: 'this month', positive: true }}
              />
            </div>
            <div className="fade-in stagger-2">
              <MetricCard
                title="Indexed Documents"
                value={formatNumber(indexedDocs)}
                subtitle="in Elasticsearch"
                icon={Search}
                variant="success"
              />
            </div>
            <div className="fade-in stagger-3">
              <MetricCard
                title="Active Sources"
                value={activeSources}
                subtitle={`of ${stats.sources.length} configured`}
                icon={Database}
                variant="default"
              />
            </div>
            <div className="fade-in stagger-4">
              <MetricCard
                title="Total Chunks"
                value={formatNumber(totalChunks)}
                subtitle={`${stats.documents_last_24h} new (24h)`}
                icon={Activity}
                variant="default"
              />
            </div>
          </div>

          {/* Pipeline overview - UPDATED with real data */}
          <div className="fade-in" style={{ animationDelay: '0.25s' }}>
            <PipelineOverview stages={frontendPipeline} />
          </div>

          {/* Bottom section: Activity + Sources - UPDATED with real data */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-1 fade-in" style={{ animationDelay: '0.3s' }}>
              <ActivityFeed jobs={frontendJobs} />
            </div>
            <div className="lg:col-span-2 fade-in" style={{ animationDelay: '0.35s' }}>
              <SourcesTable sources={stats.sources} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
