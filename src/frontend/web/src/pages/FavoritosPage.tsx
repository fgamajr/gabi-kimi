import { Clock3, Search, Star } from "lucide-react";
import { Link } from "react-router-dom";
import { getRecentDocuments, getRecentSearches } from "@/lib/history";
import { useMemo } from "react";

export default function FavoritosPage() {
  const recentDocs = useMemo(() => getRecentDocuments(), []);
  const recentSearches = useMemo(() => getRecentSearches(), []);

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-4xl mx-auto space-y-6">
      <div className="space-y-2">
        <h1 className="text-xl md:text-2xl font-bold text-foreground">Favoritos</h1>
        <p className="text-sm text-text-secondary">
          O backend ainda não expõe uma coleção persistente de favoritos. Por enquanto, esta área mostra apenas sinais locais do navegador para não simular um recurso inexistente.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl border border-border bg-surface-elevated p-5">
          <div className="mb-4 flex items-center gap-2">
            <Clock3 className="w-4 h-4 text-text-tertiary" />
            <h2 className="text-sm font-semibold text-foreground">Documentos recentes</h2>
          </div>
          {recentDocs.length > 0 ? (
            <div className="space-y-3">
              {recentDocs.slice(0, 6).map((doc) => (
                <Link key={doc.id} to={`/documento/${doc.id}`} className="block rounded-lg border border-border/80 px-3 py-3 hover:border-primary/30 transition-colors">
                  <p className="text-sm font-medium text-foreground line-clamp-2">{doc.title}</p>
                  <p className="mt-1 text-xs text-text-tertiary">
                    {doc.pubDate ? new Date(doc.pubDate).toLocaleDateString("pt-BR") : "Sem data"}
                    {doc.issuingOrgan ? ` · ${doc.issuingOrgan}` : ""}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <p className="text-sm text-text-tertiary">Nenhum documento recente no armazenamento local.</p>
          )}
        </section>

        <section className="rounded-xl border border-border bg-surface-elevated p-5">
          <div className="mb-4 flex items-center gap-2">
            <Search className="w-4 h-4 text-text-tertiary" />
            <h2 className="text-sm font-semibold text-foreground">Buscas recentes</h2>
          </div>
          {recentSearches.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {recentSearches.slice(0, 8).map((term) => (
                <Link
                  key={term}
                  to={`/busca?q=${encodeURIComponent(term)}`}
                  className="rounded-full border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-primary/30 hover:text-foreground transition-colors"
                >
                  {term}
                </Link>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-10 space-y-3">
              <Star className="w-10 h-10 text-text-tertiary" />
              <p className="text-sm text-text-secondary">Nenhum sinal local disponível ainda.</p>
              <p className="text-xs text-text-tertiary text-center">Quando a persistência real de favoritos existir no backend, esta página passa a refletir esse estado.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
