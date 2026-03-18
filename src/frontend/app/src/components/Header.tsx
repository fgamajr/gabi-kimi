import React from 'react';
import { Link } from 'react-router-dom';
import { SearchBar } from '@/components/SearchBar';
import { Icons } from '@/components/Icons';

interface HeaderSearchProps {
  defaultValue: string;
  onSearch: (q: string) => void;
  compact: true;
}

interface HeaderProps {
  showBack?: boolean;
  onBack?: () => void;
  searchProps?: HeaderSearchProps;
  actionsRight?: React.ReactNode;
}

export const Header: React.FC<HeaderProps> = ({ showBack = false, onBack, searchProps, actionsRight }) => {
  return (
    <header className="sticky top-0 z-40 glass border-b border-border">
      <div className="max-w-6xl mx-auto px-4 py-3 flex items-center gap-3">
        {showBack && (
          <button
            onClick={onBack}
            className="p-2 rounded-lg hover:bg-muted transition-colors focus-ring min-w-[44px] min-h-[44px] flex items-center justify-center shrink-0"
            aria-label="Voltar"
          >
            <Icons.back className="w-5 h-5" />
          </button>
        )}

        {searchProps ? (
          <div className="flex-1 min-w-0">
            <SearchBar defaultValue={searchProps.defaultValue} onSearch={searchProps.onSearch} compact={searchProps.compact} />
          </div>
        ) : (
          <Link
            to="/"
            className="text-lg sm:text-xl font-black tracking-tight uppercase text-foreground hover:text-primary transition-colors"
          >
            GABI DOU
          </Link>
        )}

        <div className="ml-auto flex items-center gap-1 shrink-0">{actionsRight}</div>
      </div>
    </header>
  );
};
