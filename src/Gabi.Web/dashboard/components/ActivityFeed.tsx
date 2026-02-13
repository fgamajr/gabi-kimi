
import { useEffect, useState } from 'react';
import {
  CheckCircle2,
  AlertCircle,
  Clock,
  RefreshCw
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useJobs } from '../hooks/useApi';

interface Activity {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  message: string;
  stage?: string;
  timestamp: string;
}

interface ActivityFeedProps {
  maxItems?: number;
}

const typeStyles = {
  success: {
    icon: CheckCircle2,
    color: 'text-green-500',
    bg: 'bg-green-50 dark:bg-green-900/20',
  },
  error: {
    icon: AlertCircle,
    color: 'text-red-500',
    bg: 'bg-red-50 dark:bg-red-900/20',
  },
  warning: {
    icon: Clock,
    color: 'text-yellow-500',
    bg: 'bg-yellow-50 dark:bg-yellow-900/20',
  },
  info: {
    icon: RefreshCw,
    color: 'text-blue-500',
    bg: 'bg-blue-50 dark:bg-blue-900/20',
  },
};

function formatTimeAgo(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffInSeconds < 60) return 'just now';
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  return `${Math.floor(diffInSeconds / 86400)}d ago`;
}

function mapJobStatusToType(status: string): Activity['type'] {
  switch (status.toLowerCase()) {
    case 'synced':
    case 'completed':
      return 'success';
    case 'failed':
      return 'error';
    case 'processing':
    case 'inprogress':
    case 'running':
      return 'info';
    case 'pending':
      return 'warning';
    default:
      return 'info';
  }
}

export function ActivityFeed({ maxItems = 10 }: ActivityFeedProps) {
  const { data: jobsResponse, isLoading } = useJobs();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || isLoading) {
    return (
      <div className="space-y-4 rounded-xl border bg-card p-5">
        <h3 className="font-semibold text-lg">Recent Activity</h3>
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex items-start gap-3 p-3 rounded-lg bg-muted/50 animate-pulse">
              <div className="w-8 h-8 rounded-full bg-muted" />
              <div className="flex-1 space-y-2">
                <div className="h-4 w-3/4 bg-muted rounded" />
                <div className="h-3 w-1/2 bg-muted rounded" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Transform jobs to activities
  const activities: Activity[] = (jobsResponse?.jobs || []).map(job => ({
    id: job.id,
    type: mapJobStatusToType(job.status),
    message: `${job.type.replace(/_/g, ' ')} ${job.status.toLowerCase()}`,
    stage: 'ingest', // simplified for now
    timestamp: job.updatedAt
  }));

  const limitedActivities = activities.slice(0, maxItems);

  return (
    <div className="space-y-4 rounded-xl border bg-card p-5">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-lg">Recent Activity</h3>
        <button className="text-xs text-primary hover:underline">
          View all
        </button>
      </div>

      <div className="space-y-2">
        {limitedActivities.length === 0 ? (
          <p className="text-sm text-muted-foreground p-4 text-center">No recent activity</p>
        ) : (
          limitedActivities.map((activity) => {
            const styles = typeStyles[activity.type];
            const TypeIcon = styles.icon;
            // const StageIcon = activity.stage ? stageIcons[activity.stage] : null;

            return (
              <div
                key={activity.id}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-lg",
                  "transition-colors hover:bg-muted/50"
                )}
              >
                <div
                  className={cn(
                    "flex items-center justify-center w-8 h-8 rounded-full flex-shrink-0",
                    styles.bg
                  )}
                >
                  <TypeIcon className={cn("h-4 w-4", styles.color)} />
                </div>

                <div className="flex-1 min-w-0">
                  <p className="text-sm text-foreground font-medium capitalize">{activity.message}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-muted-foreground">
                      {formatTimeAgo(activity.timestamp)}
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
