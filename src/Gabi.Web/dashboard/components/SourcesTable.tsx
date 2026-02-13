import { useState } from 'react';
import { Database, Globe, FileText, ExternalLink, RefreshCw } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Source } from '../types/api';
import { LinkDetailsModal } from './LinkDetailsModal';

interface SourcesTableProps {
  sources: Source[];
  isLoading: boolean;
  onRefresh: (sourceId: string) => Promise<void>;
}

const sourceTypeIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  web: Globe,
  database: Database,
  file: FileText,
  default: Database,
};

export function SourcesTable({ sources, isLoading, onRefresh }: SourcesTableProps) {
  const [selectedSource, setSelectedSource] = useState<string | null>(null);
  const [refreshingSource, setRefreshingSource] = useState<string | null>(null);

  const handleRefresh = async (sourceId: string) => {
    setRefreshingSource(sourceId);
    try {
      await onRefresh(sourceId);
    } finally {
      setRefreshingSource(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-48">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (sources.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Database className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No sources configured</p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {sources.map((source) => {
            const Icon = sourceTypeIcons[source.source_type] || sourceTypeIcons.default;
            
            return (
              <div
                key={source.id}
                className={cn(
                  "group relative rounded-xl border bg-card p-5",
                  "transition-all duration-200 hover:shadow-lg hover:border-primary/50"
                )}
              >
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className={cn(
                      "flex items-center justify-center w-10 h-10 rounded-lg",
                      source.enabled ? "bg-primary/10" : "bg-muted"
                    )}>
                      <Icon className={cn(
                        "h-5 w-5",
                        source.enabled ? "text-primary" : "text-muted-foreground"
                      )} />
                    </div>
                    <div>
                      <h3 className="font-medium text-foreground">{source.id}</h3>
                      <p className="text-xs text-muted-foreground capitalize">
                        {source.source_type}
                      </p>
                    </div>
                  </div>
                  
                  <div className={cn(
                    "w-2 h-2 rounded-full",
                    source.enabled ? "bg-green-500" : "bg-gray-400"
                  )} />
                </div>

                <p className="text-sm text-muted-foreground mb-4 line-clamp-2">
                  {source.description}
                </p>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <FileText className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm">
                      {source.document_count.toLocaleString()} documents
                    </span>
                  </div>

                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => handleRefresh(source.id)}
                      disabled={refreshingSource === source.id}
                      className="p-2 hover:bg-muted rounded-lg transition-colors disabled:opacity-50"
                      title="Refresh source"
                    >
                      <RefreshCw className={cn(
                        "h-4 w-4",
                        refreshingSource === source.id && "animate-spin"
                      )} />
                    </button>
                    <button
                      onClick={() => setSelectedSource(source.id)}
                      className="p-2 hover:bg-muted rounded-lg transition-colors"
                      title="View links"
                    >
                      <ExternalLink className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Modal */}
      <LinkDetailsModal
        sourceId={selectedSource || ''}
        isOpen={!!selectedSource}
        onClose={() => setSelectedSource(null)}
      />
    </>
  );
}
