import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Search, SlidersHorizontal } from "lucide-react";
import { useSearch } from "@/hooks/useDocuments";
import { cn } from "@/lib/utils";
import { SECTION_COLORS, type DOSection, type SearchFilters } from "@/types";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { SearchBar } from "@/components/SearchBar";
import { useI18n } from "@/hooks/useI18n";
import { formatDate } from "@/lib/intl";

const SECTIONS: (DOSection | undefined)[] = [undefined, "DO1", "DO2", "DO3"];

function FilterControls({ filters, setFilters }: { filters: SearchFilters; setFilters: React.Dispatch<React.SetStateAction<SearchFilters>> }) {
  const { t } = useI18n();
  return (
    <div className="space-y-4">
      <div>
        <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-2">{t("search.section")}</p>
        <div className="flex flex-wrap gap-2">
          {SECTIONS.map((s) => (
            <button
              key={s ?? "all"}
              type="button"
              onClick={() => setFilters((f) => ({ ...f, section: s }))}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors",
                filters.section === s
                  ? "bg-primary text-primary-foreground border-primary"
                  : "bg-surface-elevated text-text-secondary border-border hover:border-primary/40"
              )}
            >
              {s ?? t("search.allSections")}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function SearchPage() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const [filters, setFilters] = useState<SearchFilters>({
    query: params.get("q") || "",
    section: (params.get("section") as DOSection | null) || undefined,
  });
  const [inputValue, setInputValue] = useState(params.get("q") || "");
  const { data: results, isLoading } = useSearch(filters);

  const visualState = useMemo(() => {
    if (isLoading) return "searching" as const;
    if (inputValue.trim() && inputValue !== filters.query) return "typing" as const;
    if (filters.query) return "settled" as const;
    return "idle" as const;
  }, [filters.query, inputValue, isLoading]);

  useEffect(() => {
    const next = new URLSearchParams();
    if (filters.query) next.set("q", filters.query);
    if (filters.section) next.set("section", filters.section);
    setParams(next, { replace: true });
  }, [filters, setParams]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setFilters((f) => ({ ...f, query: inputValue }));
  };

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-4xl mx-auto space-y-6">
      {/* Sticky search bar */}
      <div className="sticky top-0 z-10 -mx-4 px-4 md:mx-0 md:px-0 py-3 bg-background/80 backdrop-blur-xl">
        <form onSubmit={handleSearch} className="flex items-start gap-2">
          <div className="flex-1">
            <SearchBar
              defaultValue={inputValue}
              onQueryChange={setInputValue}
              onSearch={(term) => {
                setInputValue(term);
                setFilters((f) => ({ ...f, query: term }));
              }}
              placeholder={t("searchBar.placeholder")}
              compact
              showShortcutHint={false}
              visualState={visualState}
              statusText={isLoading ? t("search.searchStatusSearching") : filters.query ? t("search.searchStatusReady") : undefined}
            />
          </div>

          {/* Mobile filter trigger */}
          <Sheet>
            <SheetTrigger asChild>
              <button type="button" className="md:hidden flex items-center justify-center w-11 h-11 rounded-xl border border-border bg-surface-elevated text-text-secondary hover:text-foreground">
                <SlidersHorizontal className="w-5 h-5" />
              </button>
            </SheetTrigger>
            <SheetContent side="bottom" className="rounded-t-2xl bg-surface-elevated border-border">
              <SheetHeader>
                <SheetTitle>{t("search.filters")}</SheetTitle>
              </SheetHeader>
              <div className="py-4">
                <FilterControls filters={filters} setFilters={setFilters} />
              </div>
            </SheetContent>
          </Sheet>
        </form>

        {/* Desktop filters */}
        <div className="hidden md:block mt-3">
          <FilterControls filters={filters} setFilters={setFilters} />
        </div>
      </div>

      {/* Results */}
      {filters.query.length === 0 ? (
        <div className="text-center py-16 space-y-2">
          <Search className="w-10 h-10 mx-auto text-text-tertiary" />
          <p className="text-text-secondary text-sm">{t("search.emptyPrompt")}</p>
        </div>
      ) : isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-xl bg-surface-elevated animate-pulse" />
          ))}
        </div>
      ) : results && results.length > 0 ? (
        <div className="space-y-3">
          <p className="text-xs text-text-tertiary">{t("search.resultsCount", { count: results.length })}</p>
          {results.map((r) => (
            <Link
              key={r.id}
              to={`/documento/${r.id}`}
              className="block rounded-xl border border-border bg-surface-elevated p-4 hover:border-primary/30 hover:shadow-md transition-all group"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span className={cn("text-[10px] font-bold px-2 py-0.5 rounded-md border", SECTION_COLORS[r.section])}>
                  {r.section}
                </span>
                <span className="text-[11px] text-text-tertiary">{r.organ}</span>
                <span className="text-[11px] text-text-tertiary ml-auto">
                  {formatDate(r.publishedAt)}
                </span>
              </div>
              <h3 className="text-sm font-semibold text-foreground leading-snug line-clamp-2 group-hover:text-primary transition-colors">
                {r.title}
              </h3>
              <p className="text-xs text-text-tertiary mt-1 line-clamp-2">{r.snippet}</p>
              <div className="flex gap-1.5 mt-2">
                {r.tags.slice(0, 3).map((t) => (
                  <span key={t} className="text-[10px] px-2 py-0.5 rounded-full bg-muted text-text-tertiary">
                    {t}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="text-center py-16 space-y-2">
          <p className="text-text-secondary text-sm">{t("search.noResults")}</p>
        </div>
      )}
    </div>
  );
}
