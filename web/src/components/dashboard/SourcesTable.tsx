import { Source, formatNumber } from '@/lib/api';
import { cn } from '@/lib/utils';
import { Database, ShieldCheck, ShieldAlert } from 'lucide-react';

interface SourcesTableProps {
    sources: Source[];
}

export function SourcesTable({ sources }: SourcesTableProps) {
    return (
        <div className="bg-card border rounded-xl overflow-hidden h-full flex flex-col">
            <div className="px-5 py-4 border-b border-border/50 flex items-center justify-between bg-card/50">
                <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-muted-foreground" />
                    <h3 className="font-semibold">Data Sources</h3>
                </div>
                <span className="text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 bg-accent/50 rounded border border-border/50 text-muted-foreground">
                    {sources.length} total
                </span>
            </div>
            <div className="flex-1 overflow-x-auto">
                <table className="w-full text-left text-sm border-collapse">
                    <thead className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground bg-accent/20 border-b border-border/50">
                        <tr>
                            <th className="px-6 py-4">Source</th>
                            <th className="px-6 py-4">Type / Provider</th>
                            <th className="px-6 py-4">Documents</th>
                            <th className="px-6 py-4 text-right">Status</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border/30">
                        {sources.map((source) => (
                            <tr key={source.id} className="hover:bg-accent/10 transition-colors group">
                                <td className="px-6 py-4">
                                    <div className="font-semibold group-hover:text-sync transition-colors">{source.name}</div>
                                    <div className="text-[10px] opacity-40 font-mono tracking-tight">{source.id}</div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="text-xs font-semibold">{source.sourceType || source.strategy}</div>
                                    <div className="text-[10px] opacity-40 uppercase tracking-wider mt-0.5">{source.provider}</div>
                                </td>
                                <td className="px-6 py-4">
                                    <div className="font-mono text-xs tabular-nums text-foreground/80">
                                        {formatNumber(source.documentCount)}
                                    </div>
                                </td>
                                <td className="px-6 py-4 text-right">
                                    <div className="inline-flex items-center gap-2 px-2 py-1 rounded-md bg-background border border-border/50">
                                        {source.enabled ? (
                                            <>
                                                <span className="text-[9px] font-bold text-status-online tracking-widest">ACTIVE</span>
                                                <ShieldCheck className="h-3 w-3 text-status-online" />
                                            </>
                                        ) : (
                                            <>
                                                <span className="text-[9px] font-bold text-muted-foreground tracking-widest">OFF</span>
                                                <ShieldAlert className="h-3 w-3 text-muted-foreground" />
                                            </>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
