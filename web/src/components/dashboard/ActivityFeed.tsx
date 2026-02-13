import { SyncJob, formatRelativeTime } from '@/lib/api';
import { cn } from '@/lib/utils';
import { History } from 'lucide-react';

interface ActivityFeedProps {
    jobs: SyncJob[];
}

export function ActivityFeed({ jobs }: ActivityFeedProps) {
    const getStatusColor = (status: string) => {
        switch (status) {
            case 'synced': return 'bg-status-online';
            case 'in_progress': return 'bg-status-warning';
            case 'failed': return 'bg-status-error';
            default: return 'bg-status-idle';
        }
    };

    return (
        <div className="bg-card border rounded-xl overflow-hidden h-full flex flex-col">
            <div className="px-5 py-4 border-b border-border/50 flex items-center gap-2">
                <History className="h-4 w-4 text-muted-foreground" />
                <h3 className="font-semibold">Recent Activity</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
                <div className="space-y-6">
                    {jobs.length === 0 && <p className="text-sm text-muted-foreground text-center py-10">No recent activity</p>}
                    {jobs.map((job, i) => (
                        <div key={i} className="flex gap-4 relative">
                            {i < jobs.length - 1 && (
                                <div className="absolute left-[7px] top-4 w-0.5 h-full bg-border/30" />
                            )}
                            <div className={cn("w-3.5 h-3.5 rounded-full mt-1.5 z-10 border-4 border-card", getStatusColor(job.status))} />
                            <div className="space-y-1">
                                <p className="text-sm font-medium leading-none">
                                    {job.sourceId} <span className="text-xs opacity-60">({job.year})</span>
                                </p>
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] uppercase font-bold tracking-wider opacity-40">{job.status}</span>
                                    <span className="text-[10px] opacity-40">•</span>
                                    <span className="text-[10px] opacity-40">{formatRelativeTime(job.updatedAt)}</span>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
