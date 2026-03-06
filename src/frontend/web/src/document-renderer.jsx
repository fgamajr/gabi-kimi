import React, { useMemo, useState } from "react";
import { formatDate, parseBodyChunks } from "./utils.js";

const ALLOWED_TAGS = new Set([
  "article",
  "section",
  "div",
  "span",
  "p",
  "br",
  "strong",
  "em",
  "b",
  "i",
  "u",
  "small",
  "sup",
  "sub",
  "blockquote",
  "ul",
  "ol",
  "li",
  "table",
  "thead",
  "tbody",
  "tfoot",
  "tr",
  "td",
  "th",
  "caption",
  "a",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
]);

function mediaNameFromValue(raw) {
  if (!raw) return "";
  const value = String(raw).trim().split("/").pop() || "";
  return value.replace(/\.[A-Za-z0-9]{2,5}$/u, "");
}

function inferContextHint(image) {
  const haystack = [
    image?.context_hint || "",
    image?.source_filename || "",
    image?.alt_text || "",
    image?.original_url || "",
  ].join(" ");
  if (/\b(tabela|quadro|anexo|tab|grid)\b/ui.test(haystack)) return "table";
  if (/\b(assinatura|sign|rubrica)\b/ui.test(haystack)) return "signature";
  if (/\b(bras[aã]o|logo|emblema)\b/ui.test(haystack)) return "emblem";
  return image?.context_hint || "unknown";
}

function fallbackCopy(contextHint) {
  switch (contextHint) {
    case "table":
      return "Tabela disponível apenas no documento original";
    case "signature":
      return "Assinatura — conteúdo não disponível digitalmente";
    case "emblem":
      return "Brasão/logotipo institucional";
    case "chart":
      return "Gráfico disponível apenas no documento original";
    default:
      return "Conteúdo gráfico não disponível";
  }
}

function buildReferenceLine(doc) {
  const bits = [];
  if (doc?.publication_date) bits.push(`DOU ${formatDate(doc.publication_date)}`);
  if (doc?.section) bits.push(`Seção ${(doc.section || "").replace(/^do/ui, "")}`);
  if (doc?.page_number) bits.push(`Página ${doc.page_number}`);
  return bits.join(" · ");
}

function buildImageLookup(images) {
  const bySequence = new Map();
  const bySourceFilename = new Map();
  const byOriginalUrl = new Map();
  const byMediaName = new Map();
  (images || []).forEach((item) => {
    const sequence = item.position_in_doc || item.sequence_in_document;
    if (sequence) bySequence.set(Number(sequence), item);
    if (item.source_filename) bySourceFilename.set(String(item.source_filename), item);
    if (item.original_url) byOriginalUrl.set(String(item.original_url), item);
    if (item.media_name) byMediaName.set(String(item.media_name), item);
  });
  return { bySequence, bySourceFilename, byOriginalUrl, byMediaName };
}

function resolveImageRecord(element, lookup, sequence) {
  const seq = Number(element.getAttribute("data-image-seq") || sequence);
  const src = element.getAttribute("data-original-url") || element.getAttribute("src") || "";
  const sourceFilename = src ? src.split("/").pop() : "";
  const mediaName = mediaNameFromValue(sourceFilename || src);
  const explicit = (
    lookup.bySequence.get(seq)
    || lookup.byOriginalUrl.get(src)
    || lookup.bySourceFilename.get(sourceFilename)
    || lookup.byMediaName.get(mediaName)
    || null
  );
  const contextHint = inferContextHint({
    ...explicit,
    alt_text: explicit?.alt_text || element.getAttribute("alt") || "",
    source_filename: explicit?.source_filename || sourceFilename,
    original_url: explicit?.original_url || src,
  });
  return {
    media_name: explicit?.media_name || mediaName || `image-${seq}`,
    blob_url: explicit?.blob_url || null,
    status: explicit?.status || explicit?.availability_status || "unknown",
    alt_text: explicit?.alt_text || element.getAttribute("alt") || "",
    context_hint: contextHint,
    fallback_text: explicit?.fallback_text || fallbackCopy(contextHint),
    original_url: explicit?.original_url || src || null,
    source_filename: explicit?.source_filename || sourceFilename || null,
    width_px: explicit?.width_px || null,
    height_px: explicit?.height_px || null,
    position_in_doc: explicit?.position_in_doc || seq,
  };
}

function sanitizeHref(href) {
  if (!href) return null;
  const value = href.trim();
  if (/^(https?:|\/|#)/iu.test(value)) return value;
  return null;
}

function DocumentImageIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="9" cy="10" r="1.6" fill="currentColor" />
      <path d="M6.5 16.5 10.5 12.5l2.5 2.5 2.5-2 2 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ImageFallback({ image, doc }) {
  const contextHint = inferContextHint(image);
  const description = image?.fallback_text || fallbackCopy(contextHint);
  const referenceLine = buildReferenceLine(doc);
  const originalLink = image?.original_url || null;
  const title = image?.original_url || "Imagem indisponível";

  return (
    <div className="image-fallback" title={title} data-context-hint={contextHint}>
      <div className="image-fallback__icon">
        <DocumentImageIcon />
      </div>
      <div className="image-fallback__body">
        <strong>Imagem indisponível</strong>
        <p>{description}</p>
        {referenceLine ? <span>{referenceLine}</span> : null}
        {originalLink ? (
          <a href={originalLink} target="_blank" rel="noreferrer noopener">
            Consultar DOU original ↗
          </a>
        ) : null}
      </div>
    </div>
  );
}

export function ImageAsset({ image, doc }) {
  const [failed, setFailed] = useState(image?.status !== "available" || !image?.blob_url);
  const [loaded, setLoaded] = useState(false);

  if (failed) {
    return <ImageFallback image={image} doc={doc} />;
  }

  const style = image?.width_px && image?.height_px
    ? { aspectRatio: `${image.width_px} / ${image.height_px}` }
    : undefined;

  return (
    <figure className="document-image" title={image?.original_url || undefined}>
      <div className={loaded ? "document-image__frame document-image__frame--loaded" : "document-image__frame"} style={style}>
        {!loaded ? <div className="document-image__skeleton" aria-hidden="true" /> : null}
        <img
          src={image.blob_url}
          alt={image.alt_text || image.media_name || "Imagem do documento"}
          loading="lazy"
          onLoad={() => setLoaded(true)}
          onError={() => {
            console.error("DOU image failed to load", {
              media_name: image?.media_name,
              blob_url: image?.blob_url,
              original_url: image?.original_url,
            });
            setFailed(true);
          }}
        />
      </div>
      {image?.alt_text ? <figcaption>{image.alt_text}</figcaption> : null}
    </figure>
  );
}

function renderChildren(node, doc, lookup, state, keyPrefix) {
  return Array.from(node.childNodes || []).map((child, index) => renderNode(child, doc, lookup, state, `${keyPrefix}-${index}`));
}

function renderNode(node, doc, lookup, state, key) {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    return null;
  }

  const tag = node.tagName.toLowerCase();
  if (tag === "img") {
    state.sequence += 1;
    const image = resolveImageRecord(node, lookup, state.sequence);
    return <ImageAsset key={key} image={image} doc={doc} />;
  }

  const children = renderChildren(node, doc, lookup, state, key);
  if (!ALLOWED_TAGS.has(tag)) {
    return <React.Fragment key={key}>{children}</React.Fragment>;
  }

  const props = { key };
  const className = node.getAttribute("class");
  if (className) props.className = className;

  if (tag === "a") {
    const href = sanitizeHref(node.getAttribute("href"));
    if (href) props.href = href;
    if (/^https?:/iu.test(href || "")) {
      props.target = "_blank";
      props.rel = "noreferrer noopener";
    }
  }

  if (tag === "td" || tag === "th") {
    const colspan = node.getAttribute("colspan");
    const rowspan = node.getAttribute("rowspan");
    if (colspan) props.colSpan = Number(colspan);
    if (rowspan) props.rowSpan = Number(rowspan);
  }

  return React.createElement(tag, props, ...children);
}

export function DocumentBody({ doc, plainChunkCount = 20 }) {
  const nodes = useMemo(() => {
    if (!doc?.body_html || typeof DOMParser === "undefined") {
      return null;
    }
    const parser = new DOMParser();
    const parsed = parser.parseFromString(doc.body_html, "text/html");
    const lookup = buildImageLookup(doc.images || doc.media || []);
    const state = { sequence: 0 };
    return Array.from(parsed.body.childNodes).map((node, index) =>
      renderNode(node, doc, lookup, state, `doc-node-${index}`),
    );
  }, [doc]);

  if (nodes) {
    return <article className="publication-body publication-body--html">{nodes}</article>;
  }

  const bodyPlain = String(doc?.body_plain || "").trim();
  if (!bodyPlain) {
    return <article className="publication-body publication-body--plain" />;
  }
  const chunks = parseBodyChunks(bodyPlain, plainChunkCount);
  return (
    <article className="publication-body publication-body--plain">
      {chunks.map((chunk, index) => (
        <p key={`plain-${index}`}>{chunk.trim()}</p>
      ))}
    </article>
  );
}
