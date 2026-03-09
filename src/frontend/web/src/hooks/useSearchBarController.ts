import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getAutocomplete } from "@/lib/api";
import { addRecentSearch, getRecentSearches } from "@/lib/history";

const MIN_SUGGESTION_QUERY_LENGTH = 2;
const SUGGESTION_DEBOUNCE_MS = 200;

interface UseSearchBarControllerOptions {
  defaultValue: string;
  onSearch?: (query: string) => void;
  onQueryChange?: (query: string) => void;
}

function normalizeSuggestions(payload: unknown): string[] {
  if (!Array.isArray(payload)) return [];

  return payload
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object" && "suggestion" in item) {
        const suggestion = (item as { suggestion?: string }).suggestion;
        return suggestion || "";
      }
      return "";
    })
    .filter(Boolean);
}

export function useSearchBarController({
  defaultValue,
  onSearch,
  onQueryChange,
}: UseSearchBarControllerOptions) {
  const [query, setQuery] = useState(defaultValue);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [recentSearches, setRecentSearches] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [suggesting, setSuggesting] = useState(false);
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

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  useEffect(() => {
    const handlePointerOutside = (event: MouseEvent | PointerEvent | TouchEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    };

    document.addEventListener("pointerdown", handlePointerOutside);
    document.addEventListener("touchstart", handlePointerOutside, { passive: true });

    return () => {
      document.removeEventListener("pointerdown", handlePointerOutside);
      document.removeEventListener("touchstart", handlePointerOutside);
    };
  }, []);

  const fetchSuggestions = useCallback(async (nextQuery: string) => {
    if (nextQuery.length < MIN_SUGGESTION_QUERY_LENGTH) {
      setSuggestions([]);
      setShowSuggestions(false);
      setSuggesting(false);
      return;
    }

    try {
      setSuggesting(true);
      const nextSuggestions = normalizeSuggestions(await getAutocomplete(nextQuery));
      setSuggestions(nextSuggestions);
      setShowSuggestions(nextSuggestions.length > 0);
    } catch {
      setSuggestions([]);
      setShowSuggestions(false);
    } finally {
      setSuggesting(false);
    }
  }, []);

  const queueSuggestionFetch = useCallback(
    (nextQuery: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        void fetchSuggestions(nextQuery);
      }, SUGGESTION_DEBOUNCE_MS);
    },
    [fetchSuggestions]
  );

  const submit = useCallback(
    (nextQuery: string) => {
      const trimmed = nextQuery.trim();
      if (!trimmed) return;

      setRecentSearches(addRecentSearch(trimmed));
      setShowSuggestions(false);
      setSuggestions([]);
      onQueryChange?.(trimmed);

      if (onSearch) {
        onSearch(trimmed);
        return;
      }

      navigate(`/search?q=${encodeURIComponent(trimmed)}`);
    },
    [navigate, onQueryChange, onSearch]
  );

  const handleChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) => {
      const nextQuery = event.target.value;
      setQuery(nextQuery);
      onQueryChange?.(nextQuery);
      setSelectedIdx(-1);
      queueSuggestionFetch(nextQuery);
    },
    [onQueryChange, queueSuggestionFetch]
  );

  const handleFocus = useCallback(() => {
    const nextRecentSearches = getRecentSearches();
    setRecentSearches(nextRecentSearches);

    if (suggestions.length > 0 || nextRecentSearches.length > 0 || query.trim().length === 0) {
      setShowSuggestions(true);
    }
  }, [query, suggestions.length]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>) => {
      const panelItems = query.trim().length >= MIN_SUGGESTION_QUERY_LENGTH ? suggestions : recentSearches;

      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (!showSuggestions && panelItems.length > 0) {
          setShowSuggestions(true);
        }
        setSelectedIdx((index) => Math.min(index + 1, panelItems.length - 1));
        return;
      }

      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIdx((index) => Math.max(index - 1, -1));
        return;
      }

      if (event.key === "Enter") {
        event.preventDefault();
        submit(selectedIdx >= 0 ? panelItems[selectedIdx] : query);
        return;
      }

      if (event.key === "Escape") {
        setShowSuggestions(false);
      }
    },
    [query, recentSearches, selectedIdx, showSuggestions, submit, suggestions]
  );

  const clearQuery = useCallback(() => {
    setQuery("");
    setSuggestions([]);
    setShowSuggestions(false);
    setSelectedIdx(-1);
    onQueryChange?.("");
    inputRef.current?.focus();
  }, [onQueryChange]);

  const selectItem = useCallback(
    (item: string) => {
      setQuery(item);
      submit(item);
    },
    [submit]
  );

  const isAutocompleteMode = query.trim().length >= MIN_SUGGESTION_QUERY_LENGTH;
  const panelItems = isAutocompleteMode ? suggestions : recentSearches;
  const showPanel = showSuggestions && panelItems.length > 0;

  return {
    clearQuery,
    containerRef,
    handleChange,
    handleFocus,
    handleKeyDown,
    inputRef,
    isAutocompleteMode,
    panelItems,
    query,
    selectItem,
    selectedIdx,
    setSelectedIdx,
    showPanel,
    suggesting,
  };
}
