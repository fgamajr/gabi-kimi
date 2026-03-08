import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
  CommandShortcut,
} from "@/components/ui/command";
import { Icons } from "@/components/Icons";
import { getRecentDocuments, getRecentSearches } from "@/lib/history";
import { searchDocuments } from "@/lib/api";
import type { SearchResult } from "@/lib/api";
import { navigateToDocument } from "@/lib/navigation";

export const COMMAND_PALETTE_EVENT = "gabi:open-command-palette";

export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(COMMAND_PALETTE_EVENT));
}

export const CommandPalette: React.FC = () => {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    const handleOpenEvent = () => setOpen(true);

    window.addEventListener("keydown", handleShortcut);
    window.addEventListener(COMMAND_PALETTE_EVENT, handleOpenEvent as EventListener);
    return () => {
      window.removeEventListener("keydown", handleShortcut);
      window.removeEventListener(COMMAND_PALETTE_EVENT, handleOpenEvent as EventListener);
    };
  }, []);

  useEffect(() => {
    if (!open) return;
    if (query.trim().length < 2) {
      setResults([]);
      return;
    }
    const timer = window.setTimeout(async () => {
      try {
        const response = await searchDocuments({ q: query.trim(), max: 5 });
        setResults(response.results);
      } catch {
        setResults([]);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  const recentSearches = useMemo(() => getRecentSearches().slice(0, 5), [open]);
  const recentDocs = useMemo(() => getRecentDocuments().slice(0, 5), [open]);

  const closeAndNavigate = (href: string) => {
    setOpen(false);
    setQuery("");
    navigate(href);
  };

  const closeAndOpenDocument = (documentId: string, origin: "command-palette") => {
    setOpen(false);
    setQuery("");
    navigateToDocument(navigate, documentId, origin);
  };

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput
        placeholder="Buscar documentos, órgãos, tipos de ato ou atalhos..."
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>Nenhum resultado encontrado.</CommandEmpty>

        {query.trim().length === 0 ? (
          <>
            <CommandGroup heading="Ir para">
              <CommandItem onSelect={() => closeAndNavigate("/")}>
                <Icons.home className="mr-2 h-4 w-4 text-text-tertiary" />
                Início
              </CommandItem>
              <CommandItem onSelect={() => closeAndNavigate("/search")}>
                <Icons.search className="mr-2 h-4 w-4 text-text-tertiary" />
                Busca estruturada
              </CommandItem>
              <CommandItem onSelect={() => closeAndNavigate("/chat")}>
                <Icons.chat className="mr-2 h-4 w-4 text-text-tertiary" />
                Chat com a GABI
              </CommandItem>
            </CommandGroup>

            {recentSearches.length > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup heading="Pesquisas recentes">
                  {recentSearches.map((search) => (
                    <CommandItem key={search} onSelect={() => closeAndNavigate(`/search?q=${encodeURIComponent(search)}`)}>
                      <Icons.clock className="mr-2 h-4 w-4 text-text-tertiary" />
                      {search}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            ) : null}

            {recentDocs.length > 0 ? (
              <>
                <CommandSeparator />
                <CommandGroup heading="Documentos recentes">
                  {recentDocs.map((doc) => (
                    <CommandItem key={doc.id} onSelect={() => closeAndOpenDocument(doc.id, "command-palette")}>
                      <Icons.document className="mr-2 h-4 w-4 text-text-tertiary" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate">{doc.title}</p>
                        <p className="text-xs text-text-tertiary truncate">
                          {[doc.section?.toUpperCase(), doc.issuingOrgan].filter(Boolean).join(" · ")}
                        </p>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            ) : null}
          </>
        ) : null}

        {results.length > 0 ? (
          <>
            <CommandSeparator />
            <CommandGroup heading="Resultados">
              {results.map((result) => (
                <CommandItem
                  key={result.id}
                  onSelect={() => closeAndOpenDocument(result.id, "command-palette")}
                >
                  <Icons.document className="mr-2 h-4 w-4 text-text-tertiary" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate">{result.title}</p>
                    <p className="text-xs text-text-tertiary truncate">
                      {[result.issuing_organ, result.pub_date].filter(Boolean).join(" · ")}
                    </p>
                  </div>
                </CommandItem>
              ))}
              <CommandItem onSelect={() => closeAndNavigate(`/search?q=${encodeURIComponent(query.trim())}`)}>
                <Icons.search className="mr-2 h-4 w-4 text-primary" />
                <span className="text-primary">Ver todos os resultados para “{query.trim()}”</span>
                <CommandShortcut>Enter</CommandShortcut>
              </CommandItem>
            </CommandGroup>
          </>
        ) : null}
      </CommandList>
    </CommandDialog>
  );
};
