import {
  CheckCircle2,
  AlertCircle,
  XCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface SystemComponent {
  name: string;
  status: 'healthy' | 'degraded' | 'down';
  latency?: number;
  lastCheck: string;
}

interface SystemHealthProps {
  elasticsearchAvailable: boolean;
  components?: SystemComponent[];
}

const defaultComponents: SystemComponent[] = [
  {
    name: 'API Server',
    status: 'healthy',
    latency: 45,
    lastCheck: new Date().toISOString(),
  },
  {
    name: 'Database',
    status: 'healthy',
    latency: 12,
    lastCheck: new Date().toISOString(),
  },
  {
    name: 'Pipeline Worker',
    status: 'healthy',
    lastCheck: new Date().toISOString(),
  },
];

const statusConfig = {
  healthy: {
    icon: CheckCircle2,
    color: 'text-green-500',
    bg: 'bg-green-50',
    label: 'Healthy',
  },
  degraded: {
    icon: AlertCircle,
    color: 'text-yellow-500',
    bg: 'bg-yellow-50',
    label: 'Degraded',
  },
  down: {
    icon: XCircle,
    color: 'text-red-500',
    bg: 'bg-red-50',
    label: 'Down',
  },
};

export function SystemHealth({
  elasticsearchAvailable,
  components = defaultComponents
}: SystemHealthProps) {
  const allComponents: SystemComponent[] = [
    ...components,
    {
      name: 'Elasticsearch',
      status: elasticsearchAvailable ? 'healthy' : 'down',
      lastCheck: new Date().toISOString(),
    },
  ];

  const healthyCount = allComponents.filter(c => c.status === 'healthy').length;
  const overallHealth = healthyCount === allComponents.length ? 'healthy' :
    allComponents.some(c => c.status === 'down') ? 'degraded' : 'healthy';

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold">System Health</h3>
          <p className="text-xs text-muted-foreground">
            {healthyCount} of {allComponents.length} services operational
          </p>
        </div>
        <OverallStatusBadge status={overallHealth} />
      </div>

      <div className="grid grid-cols-2 gap-3">
        {allComponents.map((component) => {
          const config = statusConfig[component.status];
          const StatusIcon = config.icon;

          return (
            <div
              key={component.name}
              className={cn(
                "flex items-center gap-3 p-3 rounded-lg border",
                "transition-colors hover:bg-muted/30"
              )}
            >
              <div
                className={cn(
                  "flex items-center justify-center w-9 h-9 rounded-lg",
                  config.bg
                )}
              >
                <StatusIcon className={cn("h-5 w-5", config.color)} />
              </div>

              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">{component.name}</p>
                <div className="flex items-center gap-2">
                  <span className={cn("text-xs", config.color)}>
                    {config.label}
                  </span>
                  {component.latency && (
                    <span className="text-xs text-muted-foreground">
                      {component.latency}ms
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function OverallStatusBadge({ status }: { status: 'healthy' | 'degraded' | 'down' }) {
  const config = statusConfig[status];

  return (
    <span
      className={cn(
        "text-xs font-medium px-2.5 py-1 rounded-full",
        status === 'healthy' && "bg-green-100 text-green-700",
        status === 'degraded' && "bg-yellow-100 text-yellow-700",
        status === 'down' && "bg-red-100 text-red-700"
      )}
    >
      {config.label}
    </span>
  );
}
