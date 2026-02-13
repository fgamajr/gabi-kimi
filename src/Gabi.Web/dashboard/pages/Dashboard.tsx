import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Database, 
  FileText, 
  Activity,
  LogOut,
  LayoutDashboard,
  Settings,
  Menu,
  X
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '../hooks/useAuth';
import { useDashboardStats, usePipeline } from '../hooks/useApi';
import { api } from '../lib/api-client';

// Components
import { PipelineOverview } from '../components/PipelineOverview';
import { SourcesTable } from '../components/SourcesTable';
import { MetricCard } from '../components/MetricCard';
import { ActivityFeed } from '../components/ActivityFeed';
import { SystemHealth } from '../components/SystemHealth';

export function Dashboard() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useDashboardStats();
  const { data: pipeline, isLoading: pipelineLoading } = usePipeline();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleRefreshSource = async (sourceId: string) => {
    await api.refreshSource(sourceId);
    await refetchStats();
  };

  // Default pipeline stages when API returns empty
  const defaultPipeline = [
    {
      name: 'discovery' as const,
      label: 'Discovery',
      description: 'Find new documents',
      count: stats?.sources?.reduce((acc, s) => acc + s.document_count, 0) || 0,
      total: stats?.total_documents || 0,
      status: 'active' as const,
      availability: 'available' as const,
      message: null,
      lastActivity: new Date().toISOString(),
    },
    {
      name: 'ingest' as const,
      label: 'Ingest',
      description: 'Download documents',
      count: 0,
      total: 0,
      status: 'idle' as const,
      availability: 'coming_soon' as const,
      message: 'Coming in next release',
      lastActivity: null,
    },
    {
      name: 'processing' as const,
      label: 'Processing',
      description: 'Extract text and metadata',
      count: 0,
      total: 0,
      status: 'idle' as const,
      availability: 'coming_soon' as const,
      message: 'Coming in next release',
      lastActivity: null,
    },
    {
      name: 'embedding' as const,
      label: 'Embedding',
      description: 'Generate vector embeddings',
      count: 0,
      total: 0,
      status: 'idle' as const,
      availability: 'coming_soon' as const,
      message: 'Coming in next release',
      lastActivity: null,
    },
    {
      name: 'indexing' as const,
      label: 'Indexing',
      description: 'Index in Elasticsearch',
      count: 0,
      total: 0,
      status: 'idle' as const,
      availability: 'coming_soon' as const,
      message: 'Coming in next release',
      lastActivity: null,
    },
  ];

  const pipelineStages = pipelineLoading || !pipeline || pipeline.length === 0 
    ? defaultPipeline 
    : pipeline;

  return (
    <div className="min-h-screen bg-background flex">
      {/* Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-64 bg-card border-r transition-transform duration-300 lg:static",
          !sidebarOpen && "-translate-x-full lg:translate-x-0 lg:w-20"
        )}
      >
        <div className="h-full flex flex-col">
          {/* Logo */}
          <div className="h-16 flex items-center justify-between px-4 border-b">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
                <Database className="h-5 w-5 text-primary-foreground" />
              </div>
              {sidebarOpen && <span className="font-semibold">GABI</span>}
            </div>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="lg:hidden p-2 hover:bg-muted rounded-lg"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-1">
            <NavItem 
              icon={LayoutDashboard} 
              label="Dashboard" 
              active 
              collapsed={!sidebarOpen} 
            />
            <NavItem 
              icon={Database} 
              label="Sources" 
              collapsed={!sidebarOpen} 
            />
            <NavItem 
              icon={Activity} 
              label="Pipeline" 
              collapsed={!sidebarOpen} 
            />
            <NavItem 
              icon={Settings} 
              label="Settings" 
              collapsed={!sidebarOpen} 
            />
          </nav>

          {/* Logout */}
          <div className="p-4 border-t">
            <button
              onClick={handleLogout}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-muted-foreground",
                "hover:bg-muted hover:text-foreground transition-colors w-full"
              )}
            >
              <LogOut className="h-5 w-5" />
              {sidebarOpen && <span>Logout</span>}
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <header className="h-16 border-b bg-card flex items-center justify-between px-4 lg:px-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="p-2 hover:bg-muted rounded-lg lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <h1 className="text-lg font-semibold">Dashboard</h1>
          </div>

          <div className="flex items-center gap-4">
            <span className="text-sm text-muted-foreground hidden sm:block">
              {new Date().toLocaleDateString('pt-BR', {
                weekday: 'long',
                year: 'numeric',
                month: 'long',
                day: 'numeric',
              })}
            </span>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-4 lg:p-6 overflow-auto">
          <div className="max-w-7xl mx-auto space-y-6">
            {/* Metrics */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <MetricCard
                title="Total Sources"
                value={stats?.sources?.length || 0}
                description="Active data sources"
                icon={Database}
              />
              <MetricCard
                title="Documents"
                value={stats?.total_documents?.toLocaleString() || 0}
                description="Total indexed documents"
                icon={FileText}
              />
              <MetricCard
                title="Elasticsearch"
                value={stats?.elasticsearch_available ? 'Connected' : 'Disconnected'}
                description="Search engine status"
                icon={Activity}
                variant={stats?.elasticsearch_available ? 'success' : 'error'}
              />
              <MetricCard
                title="Pipeline"
                value={pipelineStages.filter(s => s.status === 'active').length}
                description="Active stages"
                icon={Activity}
                variant="success"
              />
            </div>

            {/* Pipeline Overview */}
            <section>
              <PipelineOverview stages={pipelineStages} />
            </section>

            {/* Grid layout for sources and sidebar */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Sources */}
              <div className="lg:col-span-2 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Sources</h2>
                  <button 
                    onClick={() => refetchStats()}
                    className="text-sm text-primary hover:underline"
                  >
                    Refresh
                  </button>
                </div>
                <SourcesTable
                  sources={stats?.sources || []}
                  isLoading={statsLoading}
                  onRefresh={handleRefreshSource}
                />
              </div>

              {/* Sidebar widgets */}
              <div className="space-y-6">
                <SystemHealth 
                  elasticsearchAvailable={stats?.elasticsearch_available || false} 
                />
                <ActivityFeed />
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

interface NavItemProps {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  active?: boolean;
  collapsed?: boolean;
}

function NavItem({ icon: Icon, label, active, collapsed }: NavItemProps) {
  return (
    <button
      className={cn(
        "flex items-center gap-3 px-3 py-2 rounded-lg w-full transition-colors",
        active 
          ? "bg-primary/10 text-primary" 
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      <Icon className="h-5 w-5 flex-shrink-0" />
      {!collapsed && <span>{label}</span>}
    </button>
  );
}
