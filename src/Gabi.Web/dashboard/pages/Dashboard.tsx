
import {
  RefreshCw,
  Database,
  Zap,
  Activity,
  FileText,
  Layers,
  Cpu,
  Server,
} from 'lucide-react';
import { useDashboardStats, usePipeline } from '../hooks/useApi';
import { api } from '../lib/api-client';

// Components
import { MetricCard } from '../components/MetricCard';
import { PipelineOverview } from '../components/PipelineOverview';
import { SourcesTable } from '../components/SourcesTable';
import { SystemHealth } from '../components/SystemHealth';
import { ActivityFeed } from '../components/ActivityFeed';

export function Dashboard() {
  const { data: stats, isLoading: statsLoading, refetch: refetchStats } = useDashboardStats();
  const { data: pipeline } = usePipeline();

  const handleRefreshSource = async (sourceId: string) => {
    await api.refreshSource(sourceId);
    await refetchStats();
  };

  const handleSeedSources = async () => {
    try {
      await api.seedSources();
      await refetchStats();
      window.location.reload();
    } catch (error) {
      console.error('Failed to seed sources:', error);
    }
  };

  // 8 Cards Data Logic
  const syncStatus = stats?.sync_status;
  const throughput = stats?.throughput;
  const rag = stats?.rag_stats;

  // Formatting helpers
  const fmt = (n?: number) => n?.toLocaleString() || "0";

  return (
    <div className="space-y-6">
      {/* 8-Card Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Row 1 */}
        <MetricCard
          title="Sync Status"
          value={fmt(syncStatus?.synced_count)}
          description="Documents synced"
          icon={RefreshCw}
          footer={
            <div className="flex justify-between text-xs">
              <span>Pending: {fmt(syncStatus?.processing_count)}</span>
              <span>Total: {fmt(syncStatus?.total_count)}</span>
            </div>
          }
        />
        <MetricCard
          title="Elasticsearch"
          value={stats?.elasticsearch_available ? "Available" : "Unavailable"}
          description="Cluster status"
          icon={Database}
          variant={stats?.elasticsearch_available ? 'success' : 'error'}
        />
        <MetricCard
          title="Throughput"
          value={throughput?.docs_per_min !== undefined ? throughput.docs_per_min.toFixed(1) : "0"}
          description="Docs per minute"
          icon={Zap}
          footer={throughput?.eta_minutes ? `ETA: ~${throughput.eta_minutes} min` : "No active jobs"}
        />
        <MetricCard
          title="System Health"
          value="OK"
          description="Overall uptime"
          icon={Activity}
          variant="success"
        />

        {/* Row 2 */}
        <MetricCard
          title="Total Documents"
          value={fmt(stats?.total_documents)}
          description="Total discovered"
          icon={FileText}
        />
        <MetricCard
          title="RAG Indexed"
          value={fmt(rag?.indexed_count)}
          description={`${rag?.indexed_percentage || 0}% coverage`}
          icon={Layers}
          progress={{
            value: rag?.indexed_percentage || 0,
            label: `${fmt(rag?.vector_chunks_count)} chunks`
          }}
          footer={`${rag?.index_size_mb || 0} MB storage`}
        />
        <MetricCard
          title="Processing Rate"
          value={String(syncStatus?.processing_count || 0)}
          description="Active jobs"
          icon={Cpu}
          variant={(syncStatus?.processing_count || 0) > 0 ? "warning" : "default"}
        />
        <MetricCard
          title="Active Sources"
          value={String(stats?.sources?.filter(s => s.enabled).length || 0)}
          description={`of ${stats?.sources?.length || 0} total`}
          icon={Server}
        />
      </div>

      {/* Layout Split: Pipeline + Feed vs Sources */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <section className="bg-card rounded-xl border p-5">
            <h2 className="text-lg font-semibold mb-4">Pipeline Overview</h2>
            <PipelineOverview stages={pipeline || []} />
          </section>

          <section className="bg-card rounded-xl border p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Sources</h2>
              <button onClick={() => refetchStats()} className="text-sm text-primary hover:underline">
                Refresh
              </button>
            </div>
            <SourcesTable
              sources={stats?.sources || []}
              isLoading={statsLoading}
              onRefresh={handleRefreshSource}
              onSeed={handleSeedSources}
            />
          </section>
        </div>

        <div className="space-y-6">
          <ActivityFeed />
          <SystemHealth elasticsearchAvailable={stats?.elasticsearch_available || false} />
        </div>
      </div>
    </div>
  );
}
