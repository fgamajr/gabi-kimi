import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAutocomplete } from '@/lib/api';
import { addRecentSearch, getRecentSearches } from '@/lib/history';
import { Icons } from './Icons';

interface SearchBarProps {
  defaultValue?: string;
  onSearch?: (q: string) => void;
  autoFocus?: boolean;
  compact?: boolean;
  placeholder?: string;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  defaultValue = '',
  onSearch,
  autoFocus = false,
  compact = false,
  placeholder = 'Pesquisar no Diário Oficial...',
}) => {
  const [query, setQuery] = useState(defaultValue);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const navigate = useNavigate();

  useEffect(() => {
    setQuery(defaultValue);
  }, [defaultValue]);

  useEffect(() => {
    setRecentSearches(getRecentSearches());
  }, []);

  const fetchSuggestions = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSuggestions([]);
      setShowSuggestions(false);
      return;
    }
    try {
      const data = await getAutocomplete(q);
      const items = Array.isArray(data)
        ? data.map((d) => (typeof d === 'string' ? d : (d as any).suggestion || ''))
        : [];
      const nextSuggestions = items.filter(Boolean);
      setSuggestions(nextSuggestions);
      setShowSuggestions(nextSuggestions.length > 0);
    } catch {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    setQuery(val);
    setSelectedIdx(-1);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(val), 200);
  };

  const submit = (q: string) => {
    const trimmed = q.trim();
    if (!trimmed) return;
    setRecentSearches(addRecentSearch(trimmed));
    setShowSuggestions(false);
    setSuggestions([]);
    if (onSearch) {
      onSearch(trimmed);
    } else {
      navigate(`/search?q=${encodeURIComponent(trimmed)}`);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!showSuggestions && suggestions.length > 0) {
        setShowSuggestions(true);
      }
      setSelectedIdx((i) => Math.min(i + 1, suggestions.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, -1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      submit(selectedIdx >= 0 ? suggestions[selectedIdx] : query);
    } else if (e.key === 'Escape') {
      setShowSuggestions(false);
    }
  };

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const panelItems = query.trim().length >= 2 ? suggestions : recentSearches;
  const showPanel = showSuggestions && panelItems.length > 0;

  return (
    <div ref={containerRef} className="relative w-full">
      <div className={`flex items-center gap-3 rounded-xl bg-card border border-border transition-all focus-within:border-primary focus-within:shadow-[var(--shadow-glow)]
        ${compact ? 'px-3 py-2' : 'px-4 py-3.5'}`}>
        <Icons.search className="w-5 h-5 text-muted-foreground shrink-0" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={() => {
            setRecentSearches(getRecentSearches());
            if (suggestions.length > 0 || recentSearches.length > 0 || query.trim().length === 0) {
              setShowSuggestions(true);
            }
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className="flex-1 bg-transparent outline-none text-foreground placeholder:text-muted-foreground text-base"
          role="combobox"
          aria-expanded={showSuggestions}
          aria-autocomplete="list"
          aria-controls="search-suggestions"
        />
        {query && (
          <button
            onClick={() => { setQuery(''); setSuggestions([]); inputRef.current?.focus(); }}
            className="p-1 rounded-md hover:bg-muted transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
            aria-label="Limpar pesquisa"
          >
            <Icons.close className="w-4 h-4 text-muted-foreground" />
          </button>
        )}
      </div>

      {showPanel && (
        <div
          id="search-suggestions"
          className="absolute z-50 top-full mt-2 w-full rounded-xl bg-popover border border-border shadow-[var(--shadow-lg)] overflow-hidden"
        >
          <div className="px-4 py-2.5 border-b border-border text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
            {query.trim().length >= 2 ? 'Sugestões' : 'Pesquisas recentes'}
          </div>
          <ul role="listbox">
            {panelItems.map((item, i) => (
              <li
                key={`${item}-${i}`}
                role="option"
                aria-selected={i === selectedIdx}
                className={`px-4 py-3 text-sm cursor-pointer transition-colors flex items-center gap-3 min-h-[44px]
                ${i === selectedIdx ? 'bg-muted text-foreground' : 'text-secondary-foreground hover:bg-muted/50'}`}
                onMouseDown={() => {
                  setQuery(item);
                  submit(item);
                }}
                onMouseEnter={() => setSelectedIdx(i)}
              >
                <Icons.search className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
