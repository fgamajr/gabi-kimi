import { useState, useEffect } from 'react';
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
    TrendingUp,
    CloudLightning
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { api, StatsResponse, JobsResponse, PipelineStage, formatNumber } from '@/lib/api';
import { MetricCard } from './components/dashboard/MetricCard';
import { PipelineOverview } from './components/dashboard/PipelineOverview';
import { ActivityFeed } from './components/dashboard/ActivityFeed';
import { SourcesTable } from './components/dashboard/SourcesTable';

const navItems = [
    { id: 'overview', label: 'Overview', icon: LayoutDashboard, active: true },
    { id: 'jobs', label: 'Jobs & Logs', icon: History, active: false },
    { id: 'documents', label: 'Documents', icon: FileText, active: false },
    { id: 'settings', label: 'Settings', icon: Settings, active: false },
];

export default function App() {
    const [stats, setStats] = useState<StatsResponse | null>(null);
    const [jobsData, setJobsData] = useState<JobsResponse | null>(null);
    const [pipeline, setPipeline] = useState<PipelineStage[]>([]);
    const [isHealthy, setIsHealthy] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
    const [lastUpdate, setLastUpdate] = useState(new Date());

    const fetchData = async () => {
        setIsRefreshing(true);
        try {
            const [s, j, p, h] = await Promise.all([
                api.getStats(),
                api.getJobs(),
                api.getPipeline(),
                api.getHealth()
            ]);
            setStats(s);
            setJobsData(j);
            setPipeline(p);
            setIsHealthy(h);
            setLastUpdate(new Date());
        } catch (error) {
            console.error('Failed to fetch dashboard data', error);
            setIsHealthy(false);
        } finally {
            setIsRefreshing(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 30000);
        return () => clearInterval(interval);
    }, []);

    if (!stats || !jobsData) return <div className="flex items-center justify-center h-screen bg-background text-foreground font-medium animate-pulse">Initializing GABI Monitoring...</div>;

    return (
        <div className="min-h-screen flex bg-background text-foreground selection:bg-sync/30 antialiased">
            {/* Sidebar */}
            <aside className={cn(
                "fixed left-0 top-0 h-screen bg-sidebar text-sidebar-foreground",
                "border-r border-sidebar-border flex flex-col z-50 transition-all duration-300 ease-in-out",
                sidebarCollapsed ? "w-16" : "w-60"
            )}>
                <div className={cn("flex items-center h-16 px-4 border-b border-sidebar-border", sidebarCollapsed ? "justify-center" : "justify-between")}>
                    {!sidebarCollapsed && (
                        <div className="flex items-center gap-2">
                            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-sync shadow-glow-sync">
                                <Database className="h-4 w-4 text-white" />
                            </div>
                            <div>
                                <h1 className="font-bold tracking-tight">GABI</h1>
                                <p className="text-[9px] opacity-40 font-bold -mt-1 tracking-widest uppercase">World</p>
                            </div>
                        </div>
                    )}
                    {sidebarCollapsed && <Database className="h-5 w-5 text-sync shadow-glow-sync" />}
                </div>

                <nav className="flex-1 p-3 space-y-1">
                    {navItems.map((item) => {
                        const Icon = item.icon;
                        return (
                            <button key={item.id} className={cn(
                                "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group",
                                item.active ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-sm" : "opacity-60 hover:opacity-100 hover:bg-sidebar-accent/30",
                                sidebarCollapsed && "justify-center px-2"
                            )}>
                                <Icon className={cn("h-4 w-4 shrink-0 transition-transform", !item.active && "group-hover:scale-110")} />
                                {!sidebarCollapsed && <span>{item.label}</span>}
                            </button>
                        );
                    })}
                </nav>

                <div className={cn("p-4 border-t border-sidebar-border", sidebarCollapsed && "flex justify-center")}>
                    <div className={cn("flex items-center gap-2.5", sidebarCollapsed && "flex-col")}>
                        <span className={cn("w-2 h-2 rounded-full", isHealthy ? "bg-status-online pulse-online" : "bg-status-error animate-pulse")} />
                        {!sidebarCollapsed && (
                            <div className="flex flex-col">
                                <span className="text-[10px] font-bold uppercase tracking-wider opacity-60">System API</span>
                                <span className="text-[9px] opacity-40 leading-none">{isHealthy ? 'Operational' : 'Disconnected'}</span>
                            </div>
                        )}
                    </div>
                </div>

                <button
                    onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
                    className="absolute -right-3 top-20 w-6 h-6 rounded-full bg-card border border-sidebar-border shadow-md flex items-center justify-center hover:bg-accent transition-all z-[60] group"
                >
                    {sidebarCollapsed ? <ChevronRight className="h-3 w-3 group-hover:translate-x-0.5 transition-transform" /> : <ChevronLeft className="h-3 w-3 group-hover:-translate-x-0.5 transition-transform" />}
                </button>
            </aside>

            {/* Main content */}
            <main className={cn("flex-1 transition-all duration-300 ease-in-out", sidebarCollapsed ? "ml-16" : "ml-60")}>
                <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-md border-b px-8 h-16 flex items-center justify-between">
                    <div className="flex flex-col">
                        <h1 className="text-xl font-bold tracking-tight">System Dashboard</h1>
                        <div className="flex items-center gap-2 opacity-40 text-[10px] font-medium uppercase tracking-widest">
                            <TrendingUp className="h-3 w-3" />
                            <span>Live pipeline monitoring</span>
                        </div>
                    </div>
                    <div className="flex items-center gap-6">
                        <div className="flex items-center gap-2.5 px-3 py-1.5 rounded-full bg-accent/30 border border-border/50">
                            <CloudLightning className={cn("h-3.5 w-3.5", stats.elasticsearchAvailable ? "text-status-online" : "text-status-error")} />
                            <span className="text-[11px] font-semibold opacity-80 uppercase tracking-tight">ES: {stats.elasticsearchAvailable ? 'CONNECTED' : 'OFFLINE'}</span>
                        </div>
                        <div className="h-4 w-px bg-border/50" />
                        <div className="flex items-center gap-3">
                            <span className="text-[10px] font-medium opacity-40 uppercase tracking-wider">Refreshed {lastUpdate.toLocaleTimeString()}</span>
                            <button
                                onClick={fetchData}
                                disabled={isRefreshing}
                                className="w-10 h-10 flex items-center justify-center hover:bg-accent border border-border/50 rounded-xl transition-all disabled:opacity-50 group active:scale-95"
                            >
                                <Activity className={cn("h-4 w-4 text-muted-foreground group-hover:text-sync transition-colors", isRefreshing && "animate-spin")} />
                            </button>
                        </div>
                    </div>
                </header>

                <div className="p-8 space-y-8 max-w-[1600px] mx-auto">
                    {/* Metrics row */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
                        <MetricCard
                            title="Total Documents"
                            value={formatNumber(stats.totalDocuments)}
                            subtitle={`${stats.totalDocuments.toLocaleString('pt-BR')} total record chunks`}
                            icon={Files}
                            variant="primary"
                        />
                        <MetricCard
                            title="Indexed Documents"
                            value={formatNumber(jobsData.totalElasticDocs)}
                            subtitle="in Elasticsearch storage"
                            icon={Search}
                            variant="success"
                        />
                        <MetricCard
                            title="Active Sources"
                            value={stats.sources.filter(s => s.enabled).length}
                            subtitle={`of ${stats.sources.length} sources active`}
                            icon={Database}
                            variant="default"
                            trend={{ value: 4, label: 'new', positive: true }}
                        />
                        <MetricCard
                            title="Pipeline Stage"
                            value="Ingest"
                            subtitle="current active phase"
                            icon={Activity}
                            variant="warning"
                        />
                    </div>

                    {/* Pipeline overview */}
                    <div className="pt-2">
                        <PipelineOverview stages={pipeline} />
                    </div>

                    {/* Bottom section: Activity + Sources */}
                    <div className="grid grid-cols-1 xl:grid-cols-3 gap-8 pb-10">
                        <div className="xl:col-span-1 h-[500px]">
                            <ActivityFeed jobs={jobsData.syncJobs} />
                        </div>
                        <div className="xl:col-span-2">
                            <SourcesTable sources={stats.sources} />
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
}
