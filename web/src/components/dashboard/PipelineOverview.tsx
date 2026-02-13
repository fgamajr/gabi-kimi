import {
    Database,
    FileSearch,
    Download,
    Search as SearchIcon,
    ArrowRight
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PipelineStage, formatNumber, formatRelativeTime } from '@/lib/api';

interface PipelineOverviewProps {
    stages: PipelineStage[];
}

const stageIcons = {
    harvest: Download,
    sync: Database,
    ingest: FileSearch,
    index: SearchIcon,
};

const stageColors = {
    harvest: 'text-harvest shadow-glow-harvest border-harvest/20',
    sync: 'text-sync shadow-glow-sync border-sync/20',
    ingest: 'text-ingest shadow-glow-ingest border-ingest/20',
    index: 'text-index shadow-glow-index border-index/20',
};

export function PipelineOverview({ stages }: PipelineOverviewProps) {
    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold">Pipeline Status</h2>
                    <p className="text-sm opacity-60">4-stage processing flow</p>
                </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                {stages.map((stage, index) => {
                    const Icon = stageIcons[stage.name];
                    const colorClass = stageColors[stage.name];
                    const percentage = stage.total > 0 ? (stage.count / stage.total) * 100 : 0;

                    return (
                        <div key={stage.name} className="relative">
                            {index < stages.length - 1 && (
                                <div className="hidden lg:flex absolute -right-2 top-1/2 -translate-y-1/2 z-10 opacity-20">
                                    <ArrowRight className="h-4 w-4" />
                                </div>
                            )}

                            <div className={cn(
                                "relative overflow-hidden rounded-xl border bg-card p-5 hover:shadow-lg transition-all duration-200",
                                colorClass.split(' ').pop() // apply border color
                            )}>
                                <div className="flex items-start justify-between mb-4">
                                    <div className="flex items-center gap-3">
                                        <div className={cn("flex items-center justify-center w-10 h-10 rounded-lg bg-background border", colorClass.split(' ')[0])}>
                                            <Icon className="h-5 w-5" />
                                        </div>
                                        <div>
                                            <h3 className="font-medium">{stage.label}</h3>
                                            <p className="text-[10px] opacity-60">{stage.description}</p>
                                        </div>
                                    </div>
                                    <div className={cn("w-2 h-2 rounded-full", stage.status === 'active' ? "bg-status-online pulse-online" : "bg-status-idle")} />
                                </div>

                                <div className="mb-4">
                                    <div className="metric-value text-2xl font-bold">{formatNumber(stage.count)}</div>
                                    <p className="text-[10px] opacity-40">of {formatNumber(stage.total)} docs</p>
                                </div>

                                <div className="space-y-1.5">
                                    <div className="flex justify-between text-[10px] font-medium uppercase tracking-wider">
                                        <span className="opacity-40">Sync</span>
                                        <span className={colorClass.split(' ')[0]}>{percentage.toFixed(1)}%</span>
                                    </div>
                                    <div className="h-1 bg-accent rounded-full overflow-hidden">
                                        <div
                                            className={cn("h-full transition-all duration-500", colorClass.split(' ')[0].replace('text-', 'bg-'))}
                                            style={{ width: `${percentage}%` }}
                                        />
                                    </div>
                                </div>

                                {stage.lastActivity && (
                                    <div className="mt-4 pt-3 border-t border-border/50 text-[10px] opacity-40">
                                        Last: {formatRelativeTime(stage.lastActivity)}
                                    </div>
                                )}
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
