import { 
  Download, 
  Database, 
  FileSearch, 
  Brain,
  Search as SearchIcon,
  ArrowRight 
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { PipelineStage } from '../types/api';

interface PipelineOverviewProps {
  stages: PipelineStage[];
}

const stageIcons = {
  discovery: Download,
  ingest: Database,
  processing: FileSearch,
  embedding: Brain,
  indexing: SearchIcon,
};

const stageColors = {
  discovery: {
    bg: 'bg-blue-100',
    text: 'text-blue-600',
    border: 'border-blue-200',
    progress: 'bg-blue-500',
  },
  ingest: {
    bg: 'bg-gray-100',
    text: 'text-gray-500',
    border: 'border-gray-200',
    progress: 'bg-gray-400',
  },
  processing: {
    bg: 'bg-gray-100',
    text: 'text-gray-500',
    border: 'border-gray-200',
    progress: 'bg-gray-400',
  },
  embedding: {
    bg: 'bg-gray-100',
    text: 'text-gray-500',
    border: 'border-gray-200',
    progress: 'bg-gray-400',
  },
  indexing: {
    bg: 'bg-gray-100',
    text: 'text-gray-500',
    border: 'border-gray-200',
    progress: 'bg-gray-400',
  },
};

export function PipelineOverview({ stages }: PipelineOverviewProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Pipeline Status</h2>
          <p className="text-sm text-muted-foreground">Document processing pipeline</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-4">
        {stages.map((stage, index) => {
          const Icon = stageIcons[stage.name];
          const colors = stageColors[stage.name];
          const isAvailable = stage.availability === 'available';
          const percentage = stage.total > 0 ? (stage.count / stage.total) * 100 : 0;
          
          return (
            <div key={stage.name} className="relative">
              {index < stages.length - 1 && (
                <div className="hidden xl:flex absolute -right-2 top-1/2 -translate-y-1/2 z-10">
                  <ArrowRight className="h-4 w-4 text-muted-foreground/40" />
                </div>
              )}
              
              <div 
                className={cn(
                  "relative overflow-hidden rounded-xl border bg-card p-5",
                  "transition-all duration-200",
                  isAvailable ? "hover:shadow-lg" : "opacity-75",
                  colors.border
                )}
              >
                {/* Badge for coming_soon */}
                {!isAvailable && (
                  <div className="absolute top-2 right-2">
                    <span className="text-[10px] bg-gray-100 text-gray-500 px-2 py-0.5 rounded-full">
                      Soon
                    </span>
                  </div>
                )}
                
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "flex items-center justify-center w-10 h-10 rounded-lg",
                      colors.bg
                    )}>
                      <Icon className={cn("h-5 w-5", colors.text)} />
                    </div>
                    <div>
                      <h3 className="font-medium text-foreground">{stage.label}</h3>
                      <p className="text-xs text-muted-foreground">{stage.description}</p>
                    </div>
                  </div>
                  
                  <div className={cn(
                    "w-2 h-2 rounded-full",
                    stage.status === 'active' && "bg-green-500 animate-pulse",
                    stage.status === 'idle' && "bg-gray-400",
                    stage.status === 'error' && "bg-red-500"
                  )} />
                </div>
                
                <div className="mb-4">
                  <div className="metric-value text-2xl text-foreground">
                    {stage.count.toLocaleString()}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    of {stage.total.toLocaleString()} documents
                  </p>
                </div>
                
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Progress</span>
                    <span className={cn("font-medium", colors.text)}>
                      {percentage.toFixed(1)}%
                    </span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div 
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        colors.progress,
                        !isAvailable && "opacity-50"
                      )}
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
                
                {stage.message && (
                  <div className="mt-3 pt-3 border-t border-border/50">
                    <p className="text-xs text-muted-foreground">{stage.message}</p>
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
