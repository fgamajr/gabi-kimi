import React, { startTransition, useDeferredValue, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  fetchAutocomplete,
  fetchDocument,
  fetchSearch,
  fetchSearchExamples,
  fetchStats,
  fetchTopSearches,
  fetchTypes,
} from "./api.js";
import {
  buildTimelineEntries,
  copyToClipboard,
  createLibraryStore,
  formatDate,
  parseBodyChunks,
  prettyNumber,
} from "./utils.js";
import { DocumentBody } from "./document-renderer.jsx";

const TABS = [
  { id: "home", label: "Início", icon: HomeIcon },
  { id: "search", label: "Buscar", icon: SearchIcon },
  { id: "library", label: "Biblioteca", icon: LibraryIcon },
];

const libraryStore = createLibraryStore();

function getInitialTheme() {
  return document.documentElement.getAttribute("data-theme") || "dark";
}

function getInitialTab() {
  const hash = window.location.hash.replace("#", "");
  if (hash === "search" || hash === "library") return hash;
  return "home";
}

function getDocumentPath() {
  const match = window.location.pathname.match(/^\/doc\/([^/]+)$/);
  return match ? match[1] : null;
}

function usePointerCoarse() {
  const [coarse, setCoarse] = useState(window.matchMedia("(pointer: coarse)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(pointer: coarse)");
    const onChange = () => setCoarse(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return coarse;
}

function useConnectivity() {
  const [online, setOnline] = useState(navigator.onLine);
  const [degraded, setDegraded] = useState(false);
  useEffect(() => {
    const onOnline = () => {
      setOnline(true);
      setDegraded(false);
    };
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);
  return {
    online,
    degraded,
    markHealthy: () => {
      setOnline(true);
      setDegraded(false);
    },
    markFailed: () => {
      setDegraded(true);
    },
  };
}

function useTheme() {
  const [theme, setTheme] = useState(getInitialTheme);
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("gabi-theme", theme);
    } catch {}
  }, [theme]);
  return {
    theme,
    toggleTheme: () => setTheme((value) => (value === "dark" ? "light" : "dark")),
  };
}

function useRouter() {
  const [tab, setTab] = useState(getInitialTab);
  const [detailId, setDetailId] = useState(getDocumentPath);
  useEffect(() => {
    const sync = () => {
      setTab(getInitialTab());
      setDetailId(getDocumentPath());
    };
    window.addEventListener("hashchange", sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("hashchange", sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);
  return {
    tab,
    detailId,
    goTab(nextTab) {
      window.history.pushState({}, "", `/#${nextTab}`);
      setTab(nextTab);
      setDetailId(null);
    },
    openDocument(docId, originTab) {
      window.history.pushState({ originTab }, "", `/doc/${docId}#${originTab}`);
      setDetailId(docId);
      setTab(originTab);
    },
    closeDocument() {
      window.history.pushState({}, "", `/#${tab}`);
      setDetailId(null);
    },
  };
}

function useLibraryState() {
  const [state, setState] = useState({
    recentQueries: [],
    pinnedDocs: [],
    recentDocs: [],
    degraded: false,
  });
  const reload = async () => {
    try {
      const loaded = await libraryStore.load();
      setState((value) => ({ ...value, ...loaded, degraded: false }));
    } catch {
      setState((value) => ({ ...value, degraded: true }));
    }
  };
  useEffect(() => {
    reload();
  }, []);
  return {
    state,
    async recordQuery(query) {
      await libraryStore.recordQuery(query);
      reload();
    },
    async recordDoc(doc) {
      await libraryStore.recordDoc(doc);
      reload();
    },
    async togglePin(doc) {
      const exists = state.pinnedDocs.some((item) => item.doc_id === (doc.doc_id || doc.id));
      if (exists) {
        await libraryStore.unpinDoc(doc.doc_id || doc.id);
      } else {
        await libraryStore.pinDoc(doc);
      }
      reload();
    },
  };
}

export function App() {
  const { theme, toggleTheme } = useTheme();
  const router = useRouter();
  const connectivity = useConnectivity();
  const library = useLibraryState();
  const pointerCoarse = usePointerCoarse();
  const [sheet, setSheet] = useState({ open: false, title: "", actions: [] });
  const [banner, setBanner] = useState("");
  const refreshers = useRef({});
  const rootPanels = useRef({});

  useEffect(() => {
    if (router.tab && rootPanels.current[router.tab]) {
      rootPanels.current[router.tab].removeAttribute("inert");
    }
    for (const key of Object.keys(rootPanels.current)) {
      if (key !== router.tab) {
        rootPanels.current[key]?.setAttribute("inert", "");
      }
    }
  }, [router.tab]);

  const activeTitle = router.detailId ? "Documento" : TABS.find((item) => item.id === router.tab)?.label || "GABI";

  const openActions = (doc, sourceTab) => {
    const docId = doc.doc_id || doc.id;
    const actions = [
      {
        label: "Abrir documento",
        icon: "↗",
        onSelect: () => router.openDocument(docId, sourceTab),
      },
      {
        label: library.state.pinnedDocs.some((item) => item.doc_id === docId) ? "Remover da biblioteca" : "Salvar na biblioteca",
        icon: "★",
        onSelect: async () => {
          await library.togglePin(doc);
          setBanner("Biblioteca atualizada.");
        },
      },
      {
        label: "Copiar referência",
        icon: "⎘",
        onSelect: async () => {
          await copyToClipboard(doc.identifica || docId);
          setBanner("Referência copiada.");
        },
      },
    ];
    setSheet({ open: true, title: "Ações rápidas", actions });
  };

  const handleRefresh = () => {
    const action = refreshers.current[router.detailId ? "detail" : router.tab];
    if (action) action();
  };

  return (
    <div className="app-shell">
      <SkipLink />
      <header className="app-header">
        <div className="app-header__inner">
          <div>
            <p className="eyebrow">GABI · Diário Oficial</p>
            <h1 className="app-title">{activeTitle}</h1>
          </div>
          <div className="header-actions">
            <button className="ghost-button" onClick={handleRefresh}>Atualizar</button>
            <button className="ghost-button" onClick={toggleTheme}>{theme === "dark" ? "Claro" : "Escuro"}</button>
          </div>
        </div>
        {(!connectivity.online || connectivity.degraded || library.state.degraded) && (
          <div className="status-banner" role="status">
            {library.state.degraded
              ? "Biblioteca em modo degradado: dados locais do navegador indisponíveis."
              : connectivity.online
                ? "Conectividade instável. Tentando revalidar os dados."
                : "Você está offline. O shell continua disponível."}
          </div>
        )}
        {banner && (
          <div className="flash-banner" role="status">
            <span>{banner}</span>
            <button onClick={() => setBanner("")}>Fechar</button>
          </div>
        )}
      </header>

      <main id="main-content" className={router.detailId ? "main-content main-content--detail" : "main-content"}>
        <Panel
          visible={!router.detailId && router.tab === "home"}
          panelRef={(node) => { rootPanels.current.home = node; }}
        >
          <HomeScreen
            onOpenSearch={(query) => {
              router.goTab("search");
              window.dispatchEvent(new CustomEvent("gabi-search-fill", { detail: query }));
            }}
            registerRefresh={(fn) => { refreshers.current.home = fn; }}
            onHealthy={connectivity.markHealthy}
            onFailed={connectivity.markFailed}
            library={library.state}
          />
        </Panel>

        <Panel
          visible={!router.detailId && router.tab === "search"}
          panelRef={(node) => { rootPanels.current.search = node; }}
        >
          <SearchScreen
            pointerCoarse={pointerCoarse}
            registerRefresh={(fn) => { refreshers.current.search = fn; }}
            onHealthy={connectivity.markHealthy}
            onFailed={connectivity.markFailed}
            onOpenDocument={(docId) => router.openDocument(docId, "search")}
            onOpenActions={(doc) => openActions(doc, "search")}
            onRecordQuery={library.recordQuery}
          />
        </Panel>

        <Panel
          visible={!router.detailId && router.tab === "library"}
          panelRef={(node) => { rootPanels.current.library = node; }}
        >
          <LibraryScreen
            library={library.state}
            registerRefresh={(fn) => { refreshers.current.library = fn; }}
            onOpenDocument={(docId) => router.openDocument(docId, "library")}
            onOpenActions={(doc) => openActions(doc, "library")}
          />
        </Panel>

        {router.detailId && (
          <DetailScreen
            docId={router.detailId}
            onBack={router.closeDocument}
            onOpenActions={(doc) => openActions(doc, router.tab)}
            registerRefresh={(fn) => { refreshers.current.detail = fn; }}
            onHealthy={connectivity.markHealthy}
            onFailed={connectivity.markFailed}
            onRecordDoc={library.recordDoc}
          />
        )}
      </main>

      <TabBar currentTab={router.tab} onNavigate={router.goTab} />
      <AppRail currentTab={router.tab} onNavigate={router.goTab} />
      <BottomSheet
        open={sheet.open}
        title={sheet.title}
        actions={sheet.actions}
        onClose={() => setSheet({ open: false, title: "", actions: [] })}
      />
    </div>
  );
}

function Panel({ visible, children, panelRef }) {
  return (
    <section
      ref={panelRef}
      className={`screen-panel ${visible ? "screen-panel--active" : "screen-panel--hidden"}`}
      aria-hidden={visible ? "false" : "true"}
    >
      {children}
    </section>
  );
}

function HomeScreen({ registerRefresh, onHealthy, onFailed, onOpenSearch, library }) {
  const [state, setState] = useState({ loading: true, stats: null, top: [], examples: [], error: "" });
  const load = async () => {
    setState((value) => ({ ...value, loading: true, error: "" }));
    const controller = new AbortController();
    window.setTimeout(() => controller.abort(), 8000);
    try {
      const [stats, top, examples] = await Promise.all([
        fetchStats(controller.signal),
        fetchTopSearches(controller.signal),
        fetchSearchExamples(controller.signal),
      ]);
      startTransition(() => {
        setState({ loading: false, stats, top: top.items || [], examples: examples.items || [], error: "" });
      });
      onHealthy();
    } catch {
      setState((value) => ({ ...value, loading: false, error: "Não foi possível atualizar o painel." }));
      onFailed();
    }
  };
  useEffect(() => {
    registerRefresh(load);
    load();
  }, []);

  return (
    <div className="screen animate-spring-in">
      <section className="hero-card">
        <div>
          <p className="eyebrow">Operação</p>
          <h2 className="hero-title">Busca híbrida pronta para uso real.</h2>
          <p className="hero-copy">Visão densa, sem ruído: métricas primeiro, contexto depois, ação em um toque.</p>
        </div>
        <div className="live-chip animate-breathe">
          <StatusDot />
          <span>Dados ao vivo</span>
        </div>
      </section>

      {state.loading ? (
        <div className="kpi-grid">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : (
        <div className="kpi-grid">
          <MetricCard label="Documentos" value={prettyNumber(state.stats?.search?.total_docs)} tone="primary" />
          <MetricCard label="Janela" value={`${state.stats?.date_min || "—"} → ${state.stats?.date_max || "—"}`} tone="secondary" />
          <MetricCard label="Backend" value={state.stats?.search_backend || "—"} tone="success" />
        </div>
      )}

      <section className="status-card animate-float">
        <div>
          <p className="eyebrow">Status operacional</p>
          <h3>{state.stats?.search?.cluster_status === "green" ? "Cluster saudável" : "Verifique a indexação"}</h3>
          <p>{state.error || `Índice ${state.stats?.search?.index || "—"} · base ${state.stats?.db_size || "—"}`}</p>
        </div>
        <div className="status-pill status-pill--success">
          <StatusDot />
          <span>{state.stats?.search?.cluster_status || "—"}</span>
        </div>
      </section>

      <div className="split-grid">
        <section className="content-card">
          <div className="card-header">
            <h3>Consultas quentes</h3>
            <span className="eyebrow">Banco do Brasil density</span>
          </div>
          <div className="chip-grid">
            {(state.top.length ? state.top : state.examples).slice(0, 6).map((item) => (
              <button
                key={item.term || item.query}
                className="query-chip"
                onClick={() => onOpenSearch(item.term || item.query)}
              >
                {item.term || item.query}
              </button>
            ))}
          </div>
        </section>

        <section className="content-card">
          <div className="card-header">
            <h3>Biblioteca recente</h3>
            <span className="eyebrow">Nubank disclosure</span>
          </div>
          {library.recentDocs.length ? (
            <ul className="mini-list">
              {library.recentDocs.slice(0, 3).map((item) => (
                <li key={item.doc_id}>
                  <strong>{item.identifica}</strong>
                  <span>{formatDate(item.viewed_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Sua biblioteca ainda está vazia." description="Abra documentos e fixe os mais importantes para transformá-los em atalhos." />
          )}
        </section>
      </div>
    </div>
  );
}

function SearchScreen({ registerRefresh, pointerCoarse, onHealthy, onFailed, onOpenDocument, onOpenActions, onRecordQuery }) {
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("");
  const [artType, setArtType] = useState("");
  const [types, setTypes] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [activeSuggestion, setActiveSuggestion] = useState(-1);
  const [resultState, setResultState] = useState({ loading: false, error: "", total: 0, page: 1, pageSize: 12, inferredFilters: {}, results: [], meta: {} });
  const deferredQuery = useDeferredValue(query);
  const controllerRef = useRef(null);
  const longPressRef = useRef(0);

  const searchNow = async (page = 1, append = false, customQuery = query) => {
    if (!customQuery.trim()) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    window.setTimeout(() => controller.abort(), 8000);
    setResultState((value) => ({ ...value, loading: true, error: "" }));
    try {
      const payload = await fetchSearch({
        query: customQuery,
        page,
        max: 12,
        section,
        artType,
        dateFrom: "2002-01-01",
        dateTo: "2002-12-31",
      }, controller.signal);
      startTransition(() => {
        setResultState({
          loading: false,
          error: "",
          total: payload.total,
          page: payload.page,
          pageSize: payload.page_size,
          inferredFilters: payload.inferred_filters || {},
          results: append ? [...resultState.results, ...payload.results] : payload.results,
          meta: payload,
        });
      });
      onRecordQuery(customQuery);
      onHealthy();
    } catch {
      setResultState((value) => ({ ...value, loading: false, error: "A busca falhou. Tente novamente." }));
      onFailed();
    }
  };

  useEffect(() => {
    registerRefresh(() => searchNow(resultState.page || 1, false, query));
    const controller = new AbortController();
    fetchTypes(controller.signal)
      .then((payload) => setTypes(payload.items || payload.types || []))
      .catch(() => {});
    const fillFromEvent = (event) => {
      setQuery(event.detail || "");
      setTimeout(() => searchNow(1, false, event.detail || ""), 30);
    };
    window.addEventListener("gabi-search-fill", fillFromEvent);
    return () => {
      controller.abort();
      window.removeEventListener("gabi-search-fill", fillFromEvent);
    };
  }, []);

  useEffect(() => {
    if (!deferredQuery.trim() || deferredQuery.trim().length < 2) {
      setSuggestions([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const payload = await fetchAutocomplete(deferredQuery, controller.signal);
        setSuggestions(payload.items || []);
      } catch {}
    }, 200);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [deferredQuery]);

  const hasMore = Boolean(resultState.total && resultState.page * resultState.pageSize < resultState.total);

  return (
    <div className="screen animate-spring-in">
      <section className="search-shell">
        <div className="search-input-wrap">
          <SearchIcon />
          <input
            className="search-input"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveSuggestion(-1);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActiveSuggestion((value) => Math.min(value + 1, suggestions.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActiveSuggestion((value) => Math.max(value - 1, 0));
              } else if (event.key === "Enter") {
                event.preventDefault();
                const next = suggestions[activeSuggestion] || query;
                setQuery(next);
                searchNow(1, false, next);
              } else if (event.key === "Escape") {
                setSuggestions([]);
              }
            }}
            aria-activedescendant={activeSuggestion >= 0 ? `suggestion-${activeSuggestion}` : undefined}
            aria-label="Buscar no Diário Oficial"
            placeholder="Portaria, pregão, pessoa, órgão, conceito..."
          />
          <button className="search-submit" onClick={() => searchNow(1, false, query)}>Buscar</button>
        </div>

        {Boolean(suggestions.length) && (
          <ul className="suggestion-list" role="listbox">
            {suggestions.map((item, index) => (
              <li key={item} id={`suggestion-${index}`}>
                <button
                  className={index === activeSuggestion ? "suggestion suggestion--active" : "suggestion"}
                  onClick={() => {
                    setQuery(item);
                    searchNow(1, false, item);
                  }}
                >
                  {item}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div className="filter-row">
          <select value={section} onChange={(event) => setSection(event.target.value)}>
            <option value="">Todas as seções</option>
            <option value="do1">DO1</option>
            <option value="do2">DO2</option>
            <option value="do3">DO3</option>
          </select>
          <select value={artType} onChange={(event) => setArtType(event.target.value)}>
            <option value="">Todos os tipos</option>
            {types.slice(0, 24).map((item) => (
              <option key={item.value || item} value={item.value || item}>{item.label || item}</option>
            ))}
          </select>
        </div>

        {resultState.meta.interpreted_query && (
          <div className="inference-bar">
            <span>Interpretação: {resultState.meta.interpreted_query}</span>
            <span>{resultState.meta.backend || "—"} · lexical {resultState.meta.lexical_candidates || 0} · vector {resultState.meta.vector_candidates || 0}</span>
          </div>
        )}
      </section>

      {resultState.loading && !resultState.results.length ? (
        <div className="list-skeletons">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      ) : resultState.error ? (
        <ErrorState title="A busca não respondeu." description={resultState.error} onRetry={() => searchNow(1, false, query)} />
      ) : resultState.results.length ? (
        <>
          <div className="results-header">
            <strong>{prettyNumber(resultState.total)} resultados</strong>
            <span>{query || "Busca híbrida"}</span>
          </div>
          <ResultsList
            pointerCoarse={pointerCoarse}
            results={resultState.results}
            onOpenDocument={onOpenDocument}
            onOpenActions={onOpenActions}
          />
          {hasMore && (
            <button className="load-more" onClick={() => searchNow(resultState.page + 1, true, query)}>Carregar mais</button>
          )}
        </>
      ) : (
        <EmptyState
          title="Comece por uma pergunta forte."
          description="Exemplo: compra pública por meio eletrônico, Fernando Lima Gama, portaria Ministério da Saúde."
        />
      )}
    </div>
  );
}

function ResultsList({ results, onOpenDocument, onOpenActions, pointerCoarse }) {
  return (
    <div className="results-list">
      {results.map((item) => (
        <ResultRow
          key={item.doc_id}
          item={item}
          onOpenDocument={onOpenDocument}
          onOpenActions={onOpenActions}
          pointerCoarse={pointerCoarse}
        />
      ))}
    </div>
  );
}

function ResultRow({ item, onOpenDocument, onOpenActions, pointerCoarse }) {
  const [swiped, setSwiped] = useState(false);
  const startX = useRef(0);
  const moved = useRef(false);
  const pressTimer = useRef(0);

  const onTouchStart = (event) => {
    if (!pointerCoarse) return;
    startX.current = event.touches[0].clientX;
    moved.current = false;
    pressTimer.current = window.setTimeout(() => onOpenActions(item), 350);
  };
  const onTouchMove = (event) => {
    if (!pointerCoarse) return;
    const delta = event.touches[0].clientX - startX.current;
    if (Math.abs(delta) > 10) {
      moved.current = true;
      window.clearTimeout(pressTimer.current);
    }
    if (delta < -36) setSwiped(true);
    if (delta > 24) setSwiped(false);
  };
  const onTouchEnd = () => {
    window.clearTimeout(pressTimer.current);
    if (moved.current) return;
  };

  return (
    <article className={swiped ? "result-row result-row--swiped" : "result-row"} onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
      <div className="result-actions" aria-hidden={!swiped}>
        <button onClick={() => onOpenActions(item)}>Salvar</button>
        <button onClick={() => onOpenDocument(item.doc_id)}>Abrir</button>
      </div>
      <div className="result-card">
        <button className="result-main" onClick={() => onOpenDocument(item.doc_id)}>
          <div className="result-topline">
            <span className={`section-pill section-pill--${item.edition_section || "do1"}`}>{(item.edition_section || "do1").toUpperCase()}</span>
            <span>{formatDate(item.pub_date)}</span>
          </div>
          <h3>{item.identifica}</h3>
          <p>{item.snippet || item.ementa || "Sem resumo disponível."}</p>
          <div className="result-meta">
            <span>{item.issuing_organ || "Órgão não informado"}</span>
            <span>{item.art_type || "tipo não informado"}</span>
            <span>{item.retrieval_mode || "hybrid"}</span>
          </div>
        </button>
        <button className="row-menu-button" onClick={() => onOpenActions(item)} aria-label="Abrir ações rápidas">
          <MoreIcon />
        </button>
      </div>
    </article>
  );
}

function LibraryScreen({ library, registerRefresh, onOpenDocument, onOpenActions }) {
  useEffect(() => {
    registerRefresh(() => {});
  }, []);
  return (
    <div className="screen animate-spring-in">
      <div className="split-grid">
        <section className="content-card">
          <div className="card-header">
            <h3>Fixados</h3>
            <span className="eyebrow">Atalhos persistentes</span>
          </div>
          {library.pinnedDocs.length ? (
            <ul className="mini-list">
              {library.pinnedDocs.slice(0, 8).map((item) => (
                <li key={item.doc_id}>
                  <button onClick={() => onOpenDocument(item.doc_id)}>{item.identifica}</button>
                  <button className="text-link" onClick={() => onOpenActions(item)}>Ações</button>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nada fixado ainda." description="Use o menu rápido dos resultados para transformar documentos recorrentes em atalhos." />
          )}
        </section>

        <section className="content-card">
          <div className="card-header">
            <h3>Buscas recentes</h3>
            <span className="eyebrow">Memória local</span>
          </div>
          {library.recentQueries.length ? (
            <ul className="mini-list">
              {library.recentQueries.slice(0, 8).map((item) => (
                <li key={item.id}>
                  <strong>{item.query}</strong>
                  <span>{formatDate(item.created_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Sem histórico local." description="A biblioteca aprende com o seu uso e vira um cockpit de acesso rápido." />
          )}
        </section>
      </div>
    </div>
  );
}

function DetailScreen({ docId, onBack, onOpenActions, registerRefresh, onHealthy, onFailed, onRecordDoc }) {
  const [state, setState] = useState({ loading: true, error: "", doc: null, chunkCount: 20 });
  const load = async () => {
    setState((value) => ({ ...value, loading: true, error: "" }));
    const controller = new AbortController();
    window.setTimeout(() => controller.abort(), 8000);
    try {
      const doc = await fetchDocument(docId, controller.signal);
      setState({ loading: false, error: "", doc, chunkCount: 20 });
      onRecordDoc(doc);
      onHealthy();
    } catch {
      setState((value) => ({ ...value, loading: false, error: "Não foi possível abrir o documento." }));
      onFailed();
    }
  };
  useEffect(() => {
    registerRefresh(load);
    load();
  }, [docId]);

  const chunks = useMemo(
    () => (state.doc ? parseBodyChunks(state.doc.body_plain, state.chunkCount) : []),
    [state.doc, state.chunkCount],
  );
  const timeline = useMemo(
    () => (state.doc ? buildTimelineEntries(state.doc) : []),
    [state.doc],
  );

  return (
    <section className="detail-screen animate-spring-in">
      <div className="detail-toolbar">
        <button className="ghost-button" onClick={onBack}><ChevronLeftIcon /> Voltar</button>
        {state.doc && <button className="ghost-button" onClick={() => onOpenActions(state.doc)}>Ações</button>}
      </div>

      {state.loading ? (
        <div className="list-skeletons">
          <SkeletonRow />
          <SkeletonRow />
          <SkeletonRow />
        </div>
      ) : state.error ? (
        <ErrorState title="Documento indisponível." description={state.error} onRetry={load} />
      ) : (
        <>
          <section className="hero-card">
            <div>
              <p className="eyebrow">{state.doc.issuing_organ || "Órgão emissor"}</p>
              <h2 className="hero-title">{state.doc.identifica}</h2>
              <p className="hero-copy">{state.doc.ementa || "Documento completo com timeline operacional e leitura progressiva."}</p>
            </div>
            <div className={`section-pill section-pill--${state.doc.section || "do1"}`}>{(state.doc.section || "do1").toUpperCase()}</div>
          </section>

          <section className="publication-card">
            <div className="publication-masthead">
              <div>
                <p className="eyebrow">Publicação reconstruída</p>
                <h3>Diário Oficial da União</h3>
              </div>
              <div className="publication-meta">
                <span>{formatDate(state.doc.publication_date)}</span>
                <span>Página {state.doc.page_number || "—"}</span>
                <span>{(state.doc.section || "do1").toUpperCase()}</span>
              </div>
            </div>

            <DocumentBody doc={state.doc} plainChunkCount={state.chunkCount} />

            {!state.doc.body_html && state.doc.body_plain && chunks.join("").length < state.doc.body_plain.length && (
              <button className="load-more" onClick={() => setState((value) => ({ ...value, chunkCount: value.chunkCount + 12 }))}>
                Carregar mais texto
              </button>
            )}
          </section>

          <section className="timeline-card">
            <div className="card-header">
              <h3>Timeline</h3>
              <span className="eyebrow">Flighty + Nubank</span>
            </div>
            <ul className="timeline-list">
              {timeline.map((item) => (
                <li key={item.id} className={`timeline-item timeline-item--${item.state}`}>
                  <span className="timeline-dot" />
                  <div>
                    <strong>{item.title}</strong>
                    <p>{item.detail}</p>
                    <span>{item.meta}</span>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </section>
  );
}

function TabBar({ currentTab, onNavigate }) {
  return (
    <nav className="tab-bar" aria-label="Navegação principal">
      {TABS.map((item) => {
        const Icon = item.icon;
        return (
          <button key={item.id} className={currentTab === item.id ? "tab-item tab-item--active" : "tab-item"} onClick={() => onNavigate(item.id)} aria-current={currentTab === item.id ? "page" : undefined}>
            <Icon />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function AppRail({ currentTab, onNavigate }) {
  return (
    <nav className="app-rail" aria-label="Navegação lateral">
      <div className="app-rail__brand">
        <p className="eyebrow">GABI</p>
        <strong>Operação DOU</strong>
      </div>
      {TABS.map((item) => {
        const Icon = item.icon;
        return (
          <button key={item.id} className={currentTab === item.id ? "rail-item rail-item--active" : "rail-item"} onClick={() => onNavigate(item.id)} aria-current={currentTab === item.id ? "page" : undefined}>
            <Icon />
            <span>{item.label}</span>
          </button>
        );
      })}
    </nav>
  );
}

function BottomSheet({ open, title, actions, onClose }) {
  if (!open) return null;
  return (
    <div className="sheet-backdrop" role="presentation" onClick={onClose}>
      <div className="bottom-sheet animate-sheet-lift" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
        <div className="sheet-handle" />
        <div className="card-header">
          <h3>{title}</h3>
          <button className="ghost-button" onClick={onClose}>Fechar</button>
        </div>
        <div className="sheet-actions">
          {actions.map((action) => (
            <button
              key={action.label}
              className="sheet-action"
              onClick={async () => {
                onClose();
                await action.onSelect();
              }}
            >
              <span>{action.icon}</span>
              <span>{action.label}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function MetricCard({ label, value, tone }) {
  return (
    <section className={`metric-card metric-card--${tone}`}>
      <p className="eyebrow">{label}</p>
      <strong>{value}</strong>
    </section>
  );
}

function SkeletonCard() {
  return <div className="skeleton skeleton-card" aria-hidden="true" />;
}

function SkeletonRow() {
  return <div className="skeleton skeleton-row" aria-hidden="true" />;
}

function EmptyState({ title, description }) {
  return (
    <section className="empty-state">
      <h3>{title}</h3>
      <p>{description}</p>
    </section>
  );
}

function ErrorState({ title, description, onRetry }) {
  return (
    <section className="error-state">
      <h3>{title}</h3>
      <p>{description}</p>
      {onRetry && <button className="ghost-button" onClick={onRetry}>Tentar de novo</button>}
    </section>
  );
}

function SkipLink() {
  return (
    <a href="#main-content" className="skip-link">Ir direto para o conteúdo</a>
  );
}

function StatusDot() {
  return <span className="status-dot" aria-hidden="true" />;
}

function HomeIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" fill="currentColor" /></svg>;
}

function SearchIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m20 20-4.2-4.2M10.8 18a7.2 7.2 0 1 0 0-14.4 7.2 7.2 0 0 0 0 14.4Z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>;
}

function LibraryIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 4h9a3 3 0 0 1 3 3v13l-4-2-4 2-4-2-4 2V7a3 3 0 0 1 3-3Z" fill="currentColor" /></svg>;
}

function MoreIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.8" fill="currentColor" /><circle cx="12" cy="12" r="1.8" fill="currentColor" /><circle cx="19" cy="12" r="1.8" fill="currentColor" /></svg>;
}

function ChevronLeftIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 6-6 6 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}
