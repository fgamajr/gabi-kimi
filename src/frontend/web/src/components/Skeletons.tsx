import React from 'react';

interface SkeletonBlockProps {
  lines?: number;
  className?: string;
}

export const SkeletonBlock: React.FC<SkeletonBlockProps> = ({ lines = 3, className = '' }) => (
  <div className={`space-y-3 ${className}`}>
    {Array.from({ length: lines }).map((_, i) => (
      <div
        key={i}
        className="skeleton h-4"
        style={{ width: i === lines - 1 ? '60%' : '100%' }}
      />
    ))}
  </div>
);

export const SkeletonCard: React.FC<{ className?: string }> = ({ className = '' }) => (
  <div className={`rounded-lg bg-card p-4 space-y-3 ${className}`}>
    <div className="skeleton h-3 w-20" />
    <div className="skeleton h-5 w-3/4" />
    <div className="skeleton h-4 w-full" />
    <div className="skeleton h-4 w-2/3" />
    <div className="flex gap-2 pt-1">
      <div className="skeleton h-5 w-16 rounded-full" />
      <div className="skeleton h-5 w-24 rounded-full" />
    </div>
  </div>
);

export const SkeletonDocument: React.FC = () => (
  <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
    <div className="skeleton h-6 w-48 mb-2" />
    <div className="skeleton h-8 w-full" />
    <div className="skeleton h-8 w-3/4" />
    <div className="border-t border-border my-6" />
    <SkeletonBlock lines={6} />
    <SkeletonBlock lines={4} />
    <SkeletonBlock lines={5} />
  </div>
);
