import React, { useId } from "react";
import { Icons } from "./Icons";
import { useI18n } from "@/hooks/useI18n";
import { useSearchBarController } from "@/hooks/useSearchBarController";

type SearchVisualState = 'idle' | 'typing' | 'searching' | 'settled';

interface SearchBarProps {
  defaultValue?: string;
  onSearch?: (q: string) => void;
  onQueryChange?: (q: string) => void;
  autoFocus?: boolean;
  compact?: boolean;
  placeholder?: string;
  showShortcutHint?: boolean;
  visualState?: SearchVisualState;
  statusText?: string;
  ariaLabel?: string;
}

export const SearchBar: React.FC<SearchBarProps> = ({
  defaultValue = '',
  onSearch,
  onQueryChange,
  autoFocus = false,
  compact = false,
  placeholder,
  showShortcutHint = true,
  visualState = 'idle',
  statusText,
  ariaLabel,
}) => {
  const { t } = useI18n();
  const inputId = useId();
  const listboxId = `${inputId}-suggestions`;
  const statusId = `${inputId}-status`;
  const resolvedPlaceholder = placeholder || t("searchBar.placeholder");
  const resolvedAriaLabel = ariaLabel || t("searchBar.ariaLabel");
  const {
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
  } = useSearchBarController({
    defaultValue,
    onQueryChange,
    onSearch,
  });
  const activeOptionId = showPanel && selectedIdx >= 0 ? `${inputId}-option-${selectedIdx}` : undefined;
  const resolvedVisualState: SearchVisualState = visualState !== 'idle'
    ? visualState
    : suggesting
      ? 'typing'
      : query.trim().length > 0
        ? 'typing'
        : 'idle';
  const resolvedStatusText = statusText
    || (resolvedVisualState === 'searching'
      ? t("searchBar.status.searching")
      : resolvedVisualState === 'settled'
        ? t("searchBar.status.settled")
        : resolvedVisualState === 'typing'
          ? t("searchBar.status.typing")
          : '');

  return (
    <div ref={containerRef} className="relative z-20 w-full">
      <label htmlFor={inputId} className="sr-only">
        {resolvedAriaLabel}
      </label>
      <div
        className={`search-field-shell flex items-center gap-3 rounded-[24px] border transition-all
        ${compact ? 'px-4 py-3' : 'px-5 py-4'}`}
      >
        <div
          className={`search-state-shell shrink-0 ${
            resolvedVisualState === 'idle'
              ? 'is-idle'
              : resolvedVisualState === 'searching'
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
          <span className="search-state-orb search-state-orb--c" />
          <Icons.search className="relative z-10 h-[18px] w-[18px] text-foreground" />
        </div>
        <input
          id={inputId}
          ref={inputRef}
          type="text"
          value={query}
          onChange={handleChange}
          onFocus={handleFocus}
          onKeyDown={handleKeyDown}
          placeholder={resolvedPlaceholder}
          autoFocus={autoFocus}
          className={`flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground ${compact ? 'text-[15px]' : 'text-lg'}`}
          role="combobox"
          aria-expanded={showPanel}
          aria-autocomplete="list"
          aria-controls={showPanel ? listboxId : undefined}
          aria-activedescendant={activeOptionId}
          aria-describedby={resolvedStatusText ? statusId : undefined}
          aria-haspopup="listbox"
        />

        {resolvedStatusText ? (
          <>
            <span id={statusId} className="sr-only" role="status" aria-live="polite">
              {resolvedStatusText}
            </span>
            <span className="search-status-pill hidden items-center rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-text-secondary md:inline-flex">
              {resolvedStatusText}
            </span>
          </>
        ) : null}

        {query ? (
          <button
            type="button"
            onClick={clearQuery}
            className="flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl border border-border bg-background/40 transition-colors hover:bg-background/70"
            aria-label={t("searchBar.clear")}
          >
            <Icons.close className="w-4 h-4 text-muted-foreground" />
          </button>
        ) : showShortcutHint ? (
          <span className="hidden rounded-md border border-border bg-background/40 px-2 py-1 text-[11px] text-text-tertiary md:inline-flex">
            ⌘K
          </span>
        ) : null}
      </div>

      {showPanel && (
        <div
          id={listboxId}
          className="search-suggestion-panel relative z-30 mt-3 w-full overflow-hidden rounded-[24px] border shadow-[var(--shadow-lg)] backdrop-blur-xl"
        >
          <div className="border-b border-border/70 px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
            {isAutocompleteMode ? 'Sugestões' : 'Pesquisas recentes'}
          </div>
          <ul role="listbox" className="max-h-[min(18rem,42vh)] overflow-y-auto">
            {panelItems.map((item, i) => (
              <li
                id={`${inputId}-option-${i}`}
                key={`${item}-${i}`}
                role="option"
                aria-selected={i === selectedIdx}
                className={`flex min-h-[52px] cursor-pointer items-center gap-3 px-4 py-3 text-sm transition-colors
                ${i === selectedIdx ? 'bg-primary/10 text-foreground' : 'text-secondary-foreground hover:bg-background/70'}`}
                onPointerDown={(event) => {
                  event.preventDefault();
                  selectItem(item);
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
