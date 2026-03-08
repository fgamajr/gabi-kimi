import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getAutocomplete } from '@/lib/api';
import { addRecentSearch, getRecentSearches } from '@/lib/history';
import { Icons } from './Icons';

type SearchVisualState = 'idle' | 'typing' | 'searching' | 'settled';

interface SearchBarProps {
  defaultValue?: string;
  onSearch?: (q: string) => void;
  autoFocus?: boolean;
  compact?: boolean;
  placeholder?: string;
  showShortcutHint?: boolean;
  visualState?: SearchVisualState;
  statusText?: string;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  defaultValue = '',
  onSearch,
  autoFocus = false,
  compact = false,
  placeholder = 'Pesquisar no Diário Oficial...',
  showShortcutHint = true,
  visualState = 'idle',
  statusText,
}) => {
  const [query, setQuery] = useState(defaultValue);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [suggesting, setSuggesting] = useState(false);
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
      setSuggesting(false);
      return;
    }
    try {
      setSuggesting(true);
      const data = await getAutocomplete(q);
      const items = Array.isArray(data)
        ? data.map((d) => {
            if (typeof d === 'string') return d;
            if (d && typeof d === 'object' && 'suggestion' in d) {
              const suggestion = (d as { suggestion?: string }).suggestion;
              return suggestion || '';
            }
            return '';
          })
        : [];
      const nextSuggestions = items.filter(Boolean);
      setSuggestions(nextSuggestions);
      setShowSuggestions(nextSuggestions.length > 0);
    } catch {
      setSuggestions([]);
      setShowSuggestions(false);
    } finally {
      setSuggesting(false);
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
  const resolvedVisualState: SearchVisualState = visualState !== 'idle'
    ? visualState
    : suggesting
      ? 'typing'
      : query.trim().length > 0
        ? 'typing'
        : 'idle';
  const resolvedStatusText = statusText
    || (resolvedVisualState === 'searching'
      ? 'Consultando o acervo'
      : resolvedVisualState === 'settled'
        ? 'Resultados prontos'
        : resolvedVisualState === 'typing'
          ? 'Lapidando consulta'
          : '');

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
        className={`flex items-center gap-3 rounded-[24px] border border-white/8 bg-[linear-gradient(180deg,rgba(16,18,30,0.92),rgba(10,12,22,0.98))] shadow-[0_20px_40px_rgba(0,0,0,0.14)] transition-all focus-within:border-primary/40 focus-within:shadow-[0_0_0_1px_rgba(120,80,220,0.18),0_18px_42px_rgba(0,0,0,0.22)]
        ${compact ? 'px-4 py-3' : 'px-5 py-4'}`}
      >
        <div
          className={`search-state-shell shrink-0 ${
            resolvedVisualState === 'searching'
              ? 'is-searching'
              : resolvedVisualState === 'settled'
                ? 'is-settled'
                : resolvedVisualState === 'typing'
                  ? 'is-typing'
                  : ''
          }`}
          aria-hidden="true"
        >
          <span className="search-state-core" />
          <span className="search-state-orb search-state-orb--a" />
          <span className="search-state-orb search-state-orb--b" />
          <Icons.search className="relative z-10 h-[18px] w-[18px] text-foreground" />
        </div>
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

        {resolvedStatusText ? (
          <span className="search-status-pill hidden items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-secondary md:inline-flex">
            {resolvedStatusText}
          </span>
        ) : null}

        {query ? (
          <button
            onClick={() => { setQuery(''); setSuggestions([]); inputRef.current?.focus(); }}
            className="flex min-h-[36px] min-w-[36px] items-center justify-center rounded-xl border border-border bg-white/[0.03] transition-colors hover:bg-white/[0.06]"
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
          className="absolute top-full z-50 mt-3 w-full overflow-hidden rounded-[24px] border border-white/8 bg-[rgba(12,14,24,0.97)] shadow-[var(--shadow-lg)] backdrop-blur-xl"
        >
          <div className="border-b border-white/6 px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
            {query.trim().length >= 2 ? 'Sugestões' : 'Pesquisas recentes'}
          </div>
          <ul role="listbox" className="max-h-[min(18rem,42vh)] overflow-y-auto">
            {panelItems.map((item, i) => (
              <li
                key={`${item}-${i}`}
                role="option"
                aria-selected={i === selectedIdx}
                className={`flex min-h-[52px] cursor-pointer items-center gap-3 px-4 py-3 text-sm transition-colors
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
