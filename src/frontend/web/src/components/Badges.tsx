import React from 'react';

interface SectionBadgeProps {
  section: string;
  className?: string;
}

export const SectionBadge: React.FC<SectionBadgeProps> = ({ section, className = '' }) => {
  const s = section?.toLowerCase().replace(/\s+/g, '') || '';
  let badgeClass = 'section-badge-1';
  let label = 'Seção 1';

  if (s.includes('2') || s === 'secao2') {
    badgeClass = 'section-badge-2';
    label = 'Seção 2';
  } else if (s.includes('3') || s === 'secao3') {
    badgeClass = 'section-badge-3';
    label = 'Seção 3';
  }
  else if (s.includes('extra') || s.includes('e') && s.length <= 2) {
    badgeClass = 'section-badge-e';
    label = 'Extra';
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium tracking-wide ${badgeClass} ${className}`}>
      {label}
    </span>
  );
};

interface FilterChipProps {
  label: string;
  active?: boolean;
  onRemove?: () => void;
  onClick?: () => void;
}

export const FilterChip: React.FC<FilterChipProps> = ({ label, active, onRemove, onClick }) => (
  <button
    onClick={onClick || onRemove}
    className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors press-effect focus-ring min-h-[44px] min-w-[44px] justify-center
      ${active
        ? 'bg-primary text-primary-foreground'
        : 'bg-secondary text-secondary-foreground hover:bg-muted'
      }`}
    aria-pressed={active}
  >
    {label}
    {onRemove && active && (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
        <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
      </svg>
    )}
  </button>
);
