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
  <div className={`rounded-xl bg-card border border-border p-5 space-y-3 ${className}`}>
    <div className="skeleton h-3 w-20" />
    <div className="skeleton h-6 w-3/4" />
    <div className="skeleton h-4 w-full" />
    <div className="skeleton h-4 w-2/3" />
    <div className="flex gap-2 pt-1">
      <div className="skeleton h-5 w-16 rounded-full" />
      <div className="skeleton h-5 w-24 rounded-full" />
    </div>
  </div>
);

export const SkeletonDocument: React.FC = () => (
  <div className="max-w-5xl mx-auto px-4 py-8 lg:grid lg:grid-cols-[1fr_320px] lg:gap-12">
    <div className="space-y-6">
      <div className="skeleton h-5 w-64 mb-2" />
      <div className="skeleton h-10 w-full" />
      <div className="skeleton h-10 w-3/4" />
      <div className="border-t border-border my-6" />
      <SkeletonBlock lines={7} />
      <SkeletonBlock lines={6} />
      <SkeletonBlock lines={5} />
    </div>
    <div className="hidden lg:block space-y-4">
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="skeleton h-4 w-20" />
        <div className="skeleton h-11 w-full rounded-lg" />
        <div className="skeleton h-11 w-full rounded-lg" />
        <div className="skeleton h-11 w-full rounded-lg" />
      </div>
      <div className="rounded-xl border border-border bg-card p-4 space-y-3">
        <div className="skeleton h-4 w-24" />
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-5/6" />
        <div className="skeleton h-4 w-2/3" />
      </div>
    </div>
  </div>
);
