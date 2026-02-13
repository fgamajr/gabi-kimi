
import { useState, useEffect } from 'react';
import {
    Search,
    Zap,
    Layers,
    Calendar,
    Database
} from 'lucide-react';
import { useSafra, useSources } from '../hooks/useApi';
import { cn } from '@/lib/utils';
import { MetricCard } from '../components/MetricCard';

export function SafraDetails() {
    const [selectedSource, setSelectedSource] = useState<string>('');

    const { data: sources, isLoading: sourcesLoading } = useSources();
    const { data: safra, isLoading: safraLoading } = useSafra(selectedSource || undefined);

    // Auto-select first source if none selected
    useEffect(() => {
        if (!selectedSource && sources && sources.length > 0) {
            setSelectedSource(sources[0].id);
        }
    }, [sources, selectedSource]);

    return (
        <div className="space-y-6">
            <div className="flex items-center gap-4 mb-6">
                <h1 className="text-2xl font-bold">Detalhamento por Safra</h1>
            </div>

            {/* Filters */}
            <div className="bg-card p-4 rounded-xl border flex items-center gap-4">
                <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">Source:</span>
                    <select
                        value={selectedSource}
                        onChange={(e) => setSelectedSource(e.target.value)}
                        className="h-9 w-[200px] rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        disabled={sourcesLoading}
                    >
                        <option value="" disabled>Select a source</option>
                        {sources?.map(s => (
                            <option key={s.id} value={s.id}>{s.description || s.id}</option>
                        ))}
                    </select>
                </div>
            </div>

            {selectedSource ? (
                <>
                    {/* Metrics */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <MetricCard
                            title="Throughput"
                            value={safra?.throughput_docs_min?.toFixed(1) || "0"}
                            description="Docs/min processed"
                            icon={Zap}
                        />
                        <MetricCard
                            title="RAG Coverage"
                            value={`${safra?.rag_percentage?.toFixed(1) || "0"}%`}
                            description="Total documents indexed"
                            icon={Layers}
                            progress={{ value: safra?.rag_percentage || 0 }}
                        />
                        <MetricCard
                            title="Years Tracked"
                            value={safra?.years?.length || 0}
                            description="Active safras"
                            icon={Calendar}
                        />
                    </div>

                    {/* Detailed Table */}
                    <div className="bg-card rounded-xl border overflow-hidden">
                        <div className="p-4 border-b">
                            <h3 className="font-semibold">Yearly Breakdown</h3>
                        </div>
                        <div className="relative w-full overflow-auto">
                            <table className="w-full caption-bottom text-sm">
                                <thead className="[&_tr]:border-b">
                                    <tr className="border-b transition-colors hover:bg-muted/50 data-[state=selected]:bg-muted">
                                        <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Year</th>
                                        <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Sync Status</th>
                                        <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Indexed</th>
                                        <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">RAG Ready</th>
                                        <th className="h-12 px-4 text-left align-middle font-medium text-muted-foreground">Progress</th>
                                    </tr>
                                </thead>
                                <tbody className="[&_tr:last-child]:border-0">
                                    {safraLoading ? (
                                        <tr><td colSpan={5} className="p-4 text-center">Loading...</td></tr>
                                    ) : safra?.years?.length === 0 ? (
                                        <tr><td colSpan={5} className="p-4 text-center text-muted-foreground">No data found for this source.</td></tr>
                                    ) : (
                                        safra?.years.map((year) => (
                                            <tr key={year.year} className="border-b transition-colors hover:bg-muted/50">
                                                <td className="p-4 align-middle font-medium">{year.year}</td>
                                                <td className="p-4 align-middle">
                                                    <div className="flex items-center gap-2">
                                                        <span className={cn("h-2 w-2 rounded-full",
                                                            year.status === 'completed' ? 'bg-green-500' :
                                                                year.status === 'active' ? 'bg-blue-500' : 'bg-gray-300'
                                                        )} />
                                                        <span className="capitalize">{year.status}</span>
                                                        <span className="text-xs text-muted-foreground">({year.sync_count}/{year.sync_total})</span>
                                                    </div>
                                                </td>
                                                <td className="p-4 align-middle">{year.index_count.toLocaleString()}</td>
                                                <td className="p-4 align-middle">{year.rag_count.toLocaleString()}</td>
                                                <td className="p-4 align-middle w-[200px]">
                                                    <div className="h-2 w-full rounded-full bg-secondary">
                                                        <div
                                                            className="h-full rounded-full bg-primary transition-all"
                                                            style={{ width: `${(year.sync_count / Math.max(year.sync_total, 1)) * 100}%` }}
                                                        />
                                                    </div>
                                                </td>
                                            </tr>
                                        ))
                                    )}
                                </tbody>
                            </table>
                        </div>
                        <div className="p-4 border-t bg-muted/20 text-xs text-muted-foreground flex justify-between">
                            <span>Total Throughput: {safra?.throughput_docs_min.toFixed(1)} docs/min</span>
                            <span>RAG Efficiency: {safra?.rag_percentage.toFixed(1)}%</span>
                        </div>
                    </div>
                </>
            ) : (
                <div className="flex flex-col items-center justify-center h-[400px] border rounded-xl bg-card border-dashed">
                    <Search className="h-10 w-10 text-muted-foreground mb-4" />
                    <h3 className="text-lg font-medium">Select a source</h3>
                    <p className="text-sm text-muted-foreground">Choose a source above to view details</p>
                </div>
            )}
        </div>
    );
}
