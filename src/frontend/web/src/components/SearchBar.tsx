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
  showShortcutHint?: boolean;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  defaultValue = '',
  onSearch,
  autoFocus = false,
  compact = false,
  placeholder = 'Pesquisar no Diário Oficial...',
  showShortcutHint = true,
}) => {
  const [query, setQuery] = useState(defaultValue);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const navigate = useNavigate();
  const [panelHeight, setPanelHeight] = useState(0);

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
    const handlePointerOutside = (e: MouseEvent | PointerEvent | TouchEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };

    document.addEventListener('pointerdown', handlePointerOutside);
    document.addEventListener('touchstart', handlePointerOutside, { passive: true });

    return () => {
      document.removeEventListener('pointerdown', handlePointerOutside);
      document.removeEventListener('touchstart', handlePointerOutside);
    };
  }, []);

  const panelItems = query.trim().length >= 2 ? suggestions : recentSearches;
  const showPanel = showSuggestions && panelItems.length > 0;

  useEffect(() => {
    if (!showPanel) {
      setPanelHeight(0);
      return;
    }

    const updatePanelHeight = () => {
      setPanelHeight((panelRef.current?.offsetHeight || 0) + 12);
    };

    updatePanelHeight();
    window.addEventListener('resize', updatePanelHeight);
    return () => window.removeEventListener('resize', updatePanelHeight);
  }, [panelItems.length, showPanel]);

  return (
    <div ref={containerRef} className="relative z-20 w-full">
      <div
        className={`flex items-center gap-3 rounded-[20px] border bg-[linear-gradient(180deg,rgba(26,28,36,0.94),rgba(18,20,28,0.98))] transition-all focus-within:border-primary/90 focus-within:shadow-[0_0_0_1px_rgba(126,87,255,0.25),0_0_24px_rgba(126,87,255,0.12)]
        ${compact ? 'px-4 py-3' : 'px-5 py-4'}`}
      >
        <Icons.search className="h-5 w-5 shrink-0 text-muted-foreground" />
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
          className={`flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground ${compact ? 'text-[15px]' : 'text-lg'}`}
          role="combobox"
          aria-expanded={showSuggestions}
          aria-autocomplete="list"
          aria-controls="search-suggestions"
        />

        {query ? (
          <button
            onClick={() => { setQuery(''); setSuggestions([]); inputRef.current?.focus(); }}
            className="flex min-h-[36px] min-w-[36px] items-center justify-center rounded-lg border border-border bg-white/[0.03] transition-colors hover:bg-white/[0.06]"
            aria-label="Limpar pesquisa"
          >
            <Icons.close className="w-4 h-4 text-muted-foreground" />
          </button>
        ) : showShortcutHint ? (
          <span className="hidden rounded-md border border-white/8 bg-white/[0.04] px-2 py-1 text-[11px] text-text-tertiary md:inline-flex">
            ⌘K
          </span>
        ) : null}
      </div>

      {showPanel && (
        <div
          id="search-suggestions"
          ref={panelRef}
          className="absolute z-50 top-full mt-3 w-full overflow-hidden rounded-[20px] border border-white/8 bg-[#141821] shadow-[var(--shadow-lg)]"
        >
          <div className="border-b border-white/6 px-4 py-2.5 text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
            {query.trim().length >= 2 ? 'Sugestões' : 'Pesquisas recentes'}
          </div>
          <ul role="listbox" className="max-h-[min(18rem,42vh)] overflow-y-auto">
            {panelItems.map((item, i) => (
              <li
                key={`${item}-${i}`}
                role="option"
                aria-selected={i === selectedIdx}
                className={`flex min-h-[48px] cursor-pointer items-center gap-3 px-4 py-3 text-sm transition-colors
                ${i === selectedIdx ? 'bg-white/[0.05] text-foreground' : 'text-secondary-foreground hover:bg-white/[0.04]'}`}
                onPointerDown={(event) => {
                  event.preventDefault();
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

      {showPanel ? <div aria-hidden="true" style={{ height: `${panelHeight}px` }} /> : null}
    </div>
  );
};
