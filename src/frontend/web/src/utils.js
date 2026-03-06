const DB_NAME = "gabi-library";
const DB_VERSION = 1;
const STORE_RECENT_QUERIES = "recentQueries";
const STORE_PINNED = "pinnedDocs";
const STORE_RECENT_DOCS = "recentDocs";

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_RECENT_QUERIES)) {
        db.createObjectStore(STORE_RECENT_QUERIES, { keyPath: "id" });
      }
      if (!db.objectStoreNames.contains(STORE_PINNED)) {
        db.createObjectStore(STORE_PINNED, { keyPath: "doc_id" });
      }
      if (!db.objectStoreNames.contains(STORE_RECENT_DOCS)) {
        db.createObjectStore(STORE_RECENT_DOCS, { keyPath: "doc_id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("indexeddb-open-failed"));
  });
}

async function withStore(storeName, mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, mode);
    const store = tx.objectStore(storeName);
    let result;
    tx.oncomplete = () => resolve(result);
    tx.onerror = () => reject(tx.error || new Error("indexeddb-tx-failed"));
    result = fn(store);
  });
}

async function readAll(storeName) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, "readonly");
    const store = tx.objectStore(storeName);
    const request = store.getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("indexeddb-read-failed"));
  }).finally(() => db.close());
}

async function writeItem(storeName, item) {
  return withStore(storeName, "readwrite", (store) => {
    store.put(item);
  });
}

async function deleteItem(storeName, key) {
  return withStore(storeName, "readwrite", (store) => {
    store.delete(key);
  });
}

export function createLibraryStore() {
  const memory = {
    recentQueries: [],
    pinnedDocs: [],
    recentDocs: [],
  };

  async function safeRead(storeName, memoryKey) {
    try {
      return await readAll(storeName);
    } catch {
      return memory[memoryKey];
    }
  }

  async function scheduleWrite(run) {
    return new Promise((resolve) => {
      const job = async () => {
        try {
          await run();
        } finally {
          resolve();
        }
      };
      if ("requestIdleCallback" in window) {
        window.requestIdleCallback(job);
      } else {
        window.setTimeout(job, 0);
      }
    });
  }

  return {
    async load() {
      const [recentQueries, pinnedDocs, recentDocs] = await Promise.all([
        safeRead(STORE_RECENT_QUERIES, "recentQueries"),
        safeRead(STORE_PINNED, "pinnedDocs"),
        safeRead(STORE_RECENT_DOCS, "recentDocs"),
      ]);
      return {
        recentQueries: recentQueries.sort((a, b) => (b.created_at || 0) - (a.created_at || 0)).slice(0, 12),
        pinnedDocs: pinnedDocs.sort((a, b) => (b.pinned_at || 0) - (a.pinned_at || 0)).slice(0, 24),
        recentDocs: recentDocs.sort((a, b) => (b.viewed_at || 0) - (a.viewed_at || 0)).slice(0, 12),
      };
    },
    async recordQuery(query) {
      const item = { id: `${Date.now()}-${query}`, query, created_at: Date.now() };
      memory.recentQueries = [item, ...memory.recentQueries].slice(0, 50);
      await scheduleWrite(() => writeItem(STORE_RECENT_QUERIES, item).catch(() => {}));
    },
    async recordDoc(doc) {
      const item = {
        doc_id: doc.doc_id || doc.id,
        identifica: doc.identifica,
        viewed_at: Date.now(),
      };
      memory.recentDocs = [item, ...memory.recentDocs.filter((entry) => entry.doc_id !== item.doc_id)].slice(0, 100);
      await scheduleWrite(() => writeItem(STORE_RECENT_DOCS, item).catch(() => {}));
    },
    async pinDoc(doc) {
      const item = {
        doc_id: doc.doc_id || doc.id,
        identifica: doc.identifica,
        pinned_at: Date.now(),
      };
      memory.pinnedDocs = [item, ...memory.pinnedDocs.filter((entry) => entry.doc_id !== item.doc_id)].slice(0, 200);
      await scheduleWrite(() => writeItem(STORE_PINNED, item).catch(() => {}));
    },
    async unpinDoc(docId) {
      memory.pinnedDocs = memory.pinnedDocs.filter((entry) => entry.doc_id !== docId);
      await scheduleWrite(() => deleteItem(STORE_PINNED, docId).catch(() => {}));
    },
  };
}

export function formatDate(value) {
  if (!value) return "Sem data";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export function prettyNumber(value) {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("pt-BR").format(value);
}

export function buildTimelineEntries(document) {
  const entries = [];
  if (document.publication_date) {
    entries.push({
      id: "publication",
      state: "info",
      title: "Publicação",
      detail: `Publicado no ${document.section?.toUpperCase?.() || "DOU"}`,
      meta: formatDate(document.publication_date),
    });
  }
  if (document.issuing_organ) {
    entries.push({
      id: "organ",
      state: "pending",
      title: "Órgão emissor",
      detail: document.issuing_organ,
      meta: document.art_type || "Documento",
    });
  }
  if (document.normative_refs?.length) {
    entries.push({
      id: "refs",
      state: "success",
      title: "Referências normativas",
      detail: `${document.normative_refs.length} referência(s) vinculada(s)`,
      meta: "Relações extraídas do texto",
    });
  }
  if (document.media?.length || document.signatures?.length) {
    entries.push({
      id: "attachments",
      state: "warning",
      title: "Mídias e assinaturas",
      detail: `${document.media?.length || 0} mídia(s) · ${document.signatures?.length || 0} assinatura(s)`,
      meta: "Recursos associados",
    });
  }
  return entries;
}

export function parseBodyChunks(text, chunkCount) {
  if (!text) return [];
  const parts = text.split(/\n\s*\n/).filter(Boolean);
  const chunks = [];
  let chars = 0;
  for (const part of parts) {
    if (chunks.length >= chunkCount) break;
    if (chars + part.length > 12000 && chunks.length > 0) break;
    chunks.push(part.trim());
    chars += part.length;
  }
  return chunks;
}

export function copyToClipboard(value) {
  if (!value) return Promise.resolve();
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(value);
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "absolute";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
  return Promise.resolve();
}
