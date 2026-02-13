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
  variant?: 'default' | 'success' | 'warning' | 'error';
  className?: string;
}

const variantStyles = {
  default: {
    bg: 'bg-card',
    iconBg: 'bg-primary/10',
    iconColor: 'text-primary',
  },
  success: {
    bg: 'bg-card',
    iconBg: 'bg-green-100',
    iconColor: 'text-green-600',
  },
  warning: {
    bg: 'bg-card',
    iconBg: 'bg-yellow-100',
    iconColor: 'text-yellow-600',
  },
  error: {
    bg: 'bg-card',
    iconBg: 'bg-red-100',
    iconColor: 'text-red-600',
  },
};

export function MetricCard({
  title,
  value,
  description,
  icon: Icon,
  trend,
  variant = 'default',
  className,
}: MetricCardProps) {
  const styles = variantStyles[variant];
  const isPositiveTrend = trend && trend.value >= 0;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border p-5",
        "transition-all duration-200 hover:shadow-lg",
        styles.bg,
        className
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <h3 className="mt-2 text-2xl font-bold tracking-tight">{value}</h3>
          
          {description && (
            <p className="mt-1 text-xs text-muted-foreground">{description}</p>
          )}

          {trend && (
            <div className="mt-3 flex items-center gap-1.5">
              {isPositiveTrend ? (
                <TrendingUp className="h-3.5 w-3.5 text-green-500" />
              ) : (
                <TrendingDown className="h-3.5 w-3.5 text-red-500" />
              )}
              <span
                className={cn(
                  "text-xs font-medium",
                  isPositiveTrend ? "text-green-600" : "text-red-600"
                )}
              >
                {isPositiveTrend ? '+' : ''}{trend.value}%
              </span>
              <span className="text-xs text-muted-foreground">{trend.label}</span>
            </div>
          )}
        </div>

        <div
          className={cn(
            "flex items-center justify-center w-12 h-12 rounded-xl",
            styles.iconBg
          )}
        >
          <Icon className={cn("h-6 w-6", styles.iconColor)} />
        </div>
      </div>
    </div>
  );
}
