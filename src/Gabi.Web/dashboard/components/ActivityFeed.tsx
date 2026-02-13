import { useEffect, useState } from 'react';
import { 
  CheckCircle2, 
  AlertCircle, 
  Clock, 
  RefreshCw,
  Download,
  Database,
  FileSearch,
  Brain,
  Search
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface Activity {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  message: string;
  stage?: string;
  timestamp: string;
}

interface ActivityFeedProps {
  activities?: Activity[];
  maxItems?: number;
}

const stageIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  discovery: Download,
  ingest: Database,
  processing: FileSearch,
  embedding: Brain,
  indexing: Search,
};

const typeStyles = {
  success: {
    icon: CheckCircle2,
    color: 'text-green-500',
    bg: 'bg-green-50',
  },
  error: {
    icon: AlertCircle,
    color: 'text-red-500',
    bg: 'bg-red-50',
  },
  warning: {
    icon: Clock,
    color: 'text-yellow-500',
    bg: 'bg-yellow-50',
  },
  info: {
    icon: RefreshCw,
    color: 'text-blue-500',
    bg: 'bg-blue-50',
  },
};

// Demo activities for when none are provided
const demoActivities: Activity[] = [
  {
    id: '1',
    type: 'success',
    message: 'Discovery completed for TCU source',
    stage: 'discovery',
    timestamp: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  },
  {
    id: '2',
    type: 'info',
    message: 'Started ingestion batch #1234',
    stage: 'ingest',
    timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
  },
  {
    id: '3',
    type: 'warning',
    message: 'Processing queue is backing up',
    stage: 'processing',
    timestamp: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
  },
  {
    id: '4',
    type: 'error',
    message: 'Failed to index document doc-123',
    stage: 'indexing',
    timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
  },
];

function formatTimeAgo(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffInSeconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  if (diffInSeconds < 60) return 'just now';
  if (diffInSeconds < 3600) return `${Math.floor(diffInSeconds / 60)}m ago`;
  if (diffInSeconds < 86400) return `${Math.floor(diffInSeconds / 3600)}h ago`;
  return `${Math.floor(diffInSeconds / 86400)}d ago`;
}

export function ActivityFeed({ activities, maxItems = 10 }: ActivityFeedProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const displayActivities = activities || demoActivities;
  const limitedActivities = displayActivities.slice(0, maxItems);

  if (!mounted) {
    return (
      <div className="space-y-4">
        <h3 className="font-semibold">Recent Activity</h3>
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

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold">Recent Activity</h3>
        <button className="text-xs text-primary hover:underline">
          View all
        </button>
      </div>

      <div className="space-y-2">
        {limitedActivities.map((activity) => {
          const styles = typeStyles[activity.type];
          const TypeIcon = styles.icon;
          const StageIcon = activity.stage ? stageIcons[activity.stage] : null;

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
                <p className="text-sm text-foreground">{activity.message}</p>
                <div className="flex items-center gap-2 mt-1">
                  {StageIcon && (
                    <div className="flex items-center gap-1 text-xs text-muted-foreground">
                      <StageIcon className="h-3 w-3" />
                      <span className="capitalize">{activity.stage}</span>
                    </div>
                  )}
                  <span className="text-xs text-muted-foreground">
                    {formatTimeAgo(activity.timestamp)}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
