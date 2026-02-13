import { LucideIcon } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MetricCardProps {
    title: string;
    value: string | number;
    subtitle?: string;
    icon: LucideIcon;
    variant?: 'default' | 'primary' | 'success' | 'warning' | 'error';
    trend?: {
        value: number;
        label: string;
        positive: boolean;
    };
}

export function MetricCard({
    title,
    value,
    subtitle,
    icon: Icon,
    variant = 'default',
    trend
}: MetricCardProps) {
    const variantStyles = {
        default: 'text-muted-foreground',
        primary: 'text-sync',
        success: 'text-status-online',
        warning: 'text-status-warning',
        error: 'text-status-error',
    };

    return (
        <div className="bg-card border rounded-xl p-5 hover:shadow-lg transition-all duration-200">
            <div className="flex justify-between items-start mb-4">
                <div className={cn("p-2 rounded-lg bg-background border", variantStyles[variant])}>
                    <Icon className="h-5 w-5" />
                </div>
                {trend && (
                    <span className={cn(
                        "text-xs font-medium px-2 py-1 rounded-full",
                        trend.positive ? "bg-status-online/10 text-status-online" : "bg-status-error/10 text-status-error"
                    )}>
                        {trend.positive ? '+' : '-'}{trend.value}%
                    </span>
                )}
            </div>
            <div>
                <p className="text-xs text-muted-foreground uppercase font-semibold tracking-wider mb-1">{title}</p>
                <h3 className="text-2xl font-bold metric-value tracking-tight">{value}</h3>
                {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
            </div>
        </div>
    );
}
