import { Link as LinkIcon, ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { DiscoveredLink, LinkListResponse } from '../types/api';

interface LinksTableProps {
  links: LinkListResponse | null;
  isLoading: boolean;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}

export function LinksTable({
  links,
  isLoading,
  page,
  pageSize,
  onPageChange,
}: LinksTableProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (!links || links.data.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <LinkIcon className="h-12 w-12 mx-auto mb-4 opacity-50" />
        <p>No links found</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border overflow-hidden">
        <table className="w-full">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3">
                URL
              </th>
              <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3 w-24">
                Status
              </th>
              <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3 w-24">
                Docs
              </th>
              <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3 w-32">
                Discovered
              </th>
              <th className="text-left text-xs font-medium uppercase text-muted-foreground px-4 py-3 w-32">
                Pipeline
              </th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {links.data.map((link) => (
              <LinkRow key={link.id} link={link} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {links.pagination.totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Showing {(page - 1) * pageSize + 1} to{' '}
            {Math.min(page * pageSize, links.pagination.totalItems)} of{' '}
            {links.pagination.totalItems} links
          </p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => onPageChange(page - 1)}
              disabled={page === 1}
              className="p-2 hover:bg-muted rounded-lg disabled:opacity-50 transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="text-sm text-muted-foreground">
              Page {page} of {links.pagination.totalPages}
            </span>
            <button
              onClick={() => onPageChange(page + 1)}
              disabled={page >= links.pagination.totalPages}
              className="p-2 hover:bg-muted rounded-lg disabled:opacity-50 transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function LinkRow({ link }: { link: DiscoveredLink }) {
  return (
    <tr className="hover:bg-muted/30 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <LinkIcon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm font-mono truncate max-w-md hover:text-primary transition-colors"
            title={link.url}
          >
            {link.url}
          </a>
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
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    processing: 'bg-blue-100 text-blue-700',
    discovered: 'bg-purple-100 text-purple-700',
    error: 'bg-red-100 text-red-700',
  };

  return (
    <span
      className={cn(
        'text-xs px-2 py-1 rounded-full font-medium',
        colors[status] || 'bg-gray-100 text-gray-700'
      )}
    >
      {status}
    </span>
  );
}

function PipelineBadge({ pipeline }: { pipeline: DiscoveredLink['pipeline'] }) {
  const stages = Object.entries(pipeline);
  const completed = stages.filter(([, s]) => s.status === 'completed').length;
  const hasErrors = stages.some(([, s]) => s.status === 'error');

  return (
    <div className="flex items-center gap-2">
      <div className="flex -space-x-1">
        {stages.map(([name, status]) => (
          <div
            key={name}
            className={cn(
              'w-2.5 h-2.5 rounded-full border-2 border-background',
              status.status === 'completed' && 'bg-green-500',
              status.status === 'active' && 'bg-blue-500 animate-pulse',
              status.status === 'error' && 'bg-red-500',
              status.status === 'planned' && 'bg-gray-300',
              status.status === 'pending' && 'bg-yellow-300'
            )}
            title={`${name}: ${status.status}`}
          />
        ))}
      </div>
      <span
        className={cn(
          'text-xs',
          hasErrors ? 'text-red-500' : 'text-muted-foreground'
        )}
      >
        {completed}/{stages.length}
      </span>
    </div>
  );
}
