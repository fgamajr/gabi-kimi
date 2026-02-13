import { LucideIcon, TrendingUp, TrendingDown } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MetricCardProps {
  title: string;
  value: string | number;
  description?: string;
  icon: LucideIcon;
  trend?: {
    value: number;
    label: string;
  };
  footer?: React.ReactNode;
  progress?: {
    value: number;
    label?: string;
    variant?: 'default' | 'success' | 'warning' | 'error';
  };
  variant?: 'default' | 'success' | 'warning' | 'error';
  className?: string;
}

const variantStyles = {
  default: {
    bg: 'bg-card',
    iconBg: 'bg-primary/10',
    iconColor: 'text-primary',
    progress: 'bg-primary',
  },
  success: {
    bg: 'bg-card',
    iconBg: 'bg-green-100 dark:bg-green-900/30',
    iconColor: 'text-green-600 dark:text-green-400',
    progress: 'bg-green-600',
  },
  warning: {
    bg: 'bg-card',
    iconBg: 'bg-yellow-100 dark:bg-yellow-900/30',
    iconColor: 'text-yellow-600 dark:text-yellow-400',
    progress: 'bg-yellow-600',
  },
  error: {
    bg: 'bg-card',
    iconBg: 'bg-red-100 dark:bg-red-900/30',
    iconColor: 'text-red-600 dark:text-red-400',
    progress: 'bg-red-600',
  },
};

export function MetricCard({
  title,
  value,
  description,
  icon: Icon,
  trend,
  footer,
  progress,
  variant = 'default',
  className,
}: MetricCardProps) {
  const styles = variantStyles[variant];
  const isPositiveTrend = trend && trend.value >= 0;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border p-5 bg-card",
        "transition-all duration-200 hover:shadow-md",
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <div className="mt-2 flex items-baseline gap-2">
            <h3 className="text-2xl font-bold tracking-tight">{value}</h3>
            {trend && (
              <span
                className={cn(
                  "flex items-center text-xs font-medium",
                  isPositiveTrend ? "text-green-600 dark:text-green-400" : "text-red-600 dark:text-red-400"
                )}
              >
                {isPositiveTrend ? (
                  <TrendingUp className="mr-1 h-3 w-3" />
                ) : (
                  <TrendingDown className="mr-1 h-3 w-3" />
                )}
                {Math.abs(trend.value)}%
              </span>
            )}
          </div>

          {description && (
            <p className="mt-1 text-xs text-muted-foreground">{description}</p>
          )}

          {progress && (
            <div className="mt-3 space-y-1">
              <div className="h-1.5 w-full rounded-full bg-secondary">
                <div
                  className={cn("h-full rounded-full transition-all", styles.progress)}
                  style={{ width: `${Math.min(100, Math.max(0, progress.value))}%` }}
                />
              </div>
              {progress.label && (
                <p className="text-xs text-muted-foreground text-right">{progress.label}</p>
              )}
            </div>
          )}

          {footer && (
            <div className="mt-3 pt-3 border-t text-xs text-muted-foreground">
              {footer}
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex items-center justify-center w-10 h-10 rounded-lg ml-4",
            styles.iconBg
          )}
        >
          <Icon className={cn("h-5 w-5", styles.iconColor)} />
        </div>
      </div>
    </div>
  );
}
