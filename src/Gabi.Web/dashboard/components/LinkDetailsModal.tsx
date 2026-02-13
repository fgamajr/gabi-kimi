import { useState, useEffect } from 'react';
import { X, ChevronLeft, ChevronRight, Link as LinkIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { api } from '../lib/api-client';
import { SourceDetails, DiscoveredLink, LinkListResponse } from '../types/api';

interface LinkDetailsModalProps {
  sourceId: string;
  isOpen: boolean;
  onClose: () => void;
}

export function LinkDetailsModal({ sourceId, isOpen, onClose }: LinkDetailsModalProps) {
  const [source, setSource] = useState<SourceDetails | null>(null);
  const [links, setLinks] = useState<LinkListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen, sourceId, page]);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    
    try {
      const [sourceData, linksData] = await Promise.all([
        api.getSourceDetails(sourceId),
        api.getSourceLinks(sourceId, page, pageSize),
      ]);
      
      setSource(sourceData);
      setLinks(linksData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div className="relative w-full max-w-5xl max-h-[90vh] bg-card rounded-xl shadow-2xl overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <div>
            <h2 className="text-xl font-semibold">{source?.name || sourceId}</h2>
            <p className="text-sm text-muted-foreground">
              {source?.totalLinks || 0} links discovered
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-muted rounded-lg transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto p-6">
          {isLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
            </div>
          ) : error ? (
            <div className="text-center text-red-500 py-8">{error}</div>
          ) : (
            <>
              {/* Statistics */}
              <div className="grid grid-cols-4 gap-4 mb-6">
                {Object.entries(source?.statistics.linksByStatus || {}).map(([status, count]) => (
                  <div key={status} className="bg-muted/50 rounded-lg p-4">
                    <p className="text-2xl font-semibold">{count}</p>
                    <p className="text-xs text-muted-foreground uppercase">{status}</p>
                  </div>
                ))}
              </div>

              {/* Links Table */}
              <div className="rounded-lg border overflow-hidden">
                <table className="w-full">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                        URL
                      </th>
                      <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                        Status
                      </th>
                      <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                        Documents
                      </th>
                      <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                        Discovered
                      </th>
                      <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                        Pipeline
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y">
                    {links?.data.map((link) => (
                      <tr key={link.id} className="hover:bg-muted/30">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <LinkIcon className="h-4 w-4 text-muted-foreground" />
                            <span className="text-sm font-mono truncate max-w-xs">
                              {link.url}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <StatusBadge status={link.status} />
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm">{link.documentCount}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-sm text-muted-foreground">
                            {new Date(link.discoveredAt).toLocaleDateString()}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <PipelineBadge pipeline={link.pipeline} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {links && links.pagination.totalPages > 1 && (
                <div className="flex items-center justify-between mt-4">
                  <p className="text-sm text-muted-foreground">
                    Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, links.pagination.totalItems)} of{' '}
                    {links.pagination.totalItems} links
                  </p>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={page === 1}
                      className="p-2 hover:bg-muted rounded-lg disabled:opacity-50"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </button>
                    <span className="text-sm">
                      Page {page} of {links.pagination.totalPages}
                    </span>
                    <button
                      onClick={() => setPage(p => Math.min(links.pagination.totalPages, p + 1))}
                      disabled={page === links.pagination.totalPages}
                      className="p-2 hover:bg-muted rounded-lg disabled:opacity-50"
                    >
                      <ChevronRight className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors = {
    pending: 'bg-yellow-100 text-yellow-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    processing: 'bg-blue-100 text-blue-700',
  };
  
  return (
    <span className={cn(
      "text-xs px-2 py-1 rounded-full font-medium",
      colors[status as keyof typeof colors] || 'bg-gray-100 text-gray-700'
    )}>
      {status}
    </span>
  );
}

function PipelineBadge({ pipeline }: { pipeline: DiscoveredLink['pipeline'] }) {
  const completed = Object.values(pipeline).filter(s => s.status === 'completed').length;
  const total = Object.keys(pipeline).length;
  
  return (
    <div className="flex items-center gap-1">
      <div className="flex -space-x-1">
        {Object.entries(pipeline).map(([name, status]) => (
          <div
            key={name}
            className={cn(
              "w-2 h-2 rounded-full border border-white",
              status.status === 'completed' && "bg-green-500",
              status.status === 'planned' && "bg-gray-300",
              status.status === 'active' && "bg-blue-500 animate-pulse"
            )}
            title={`${name}: ${status.status}`}
          />
        ))}
      </div>
      <span className="text-xs text-muted-foreground ml-1">
        {completed}/{total}
      </span>
    </div>
  );
}
