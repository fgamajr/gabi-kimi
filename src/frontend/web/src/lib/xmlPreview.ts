/**
 * Client-side XML preview for DOU files (UPLD-07): article count, date range, sections.
 * Best-effort parsing; backend does authoritative parse.
 */
export interface XmlPreview {
  articleCount: number;
  dateMin: string | null;
  dateMax: string | null;
  sections: string[];
  error?: string;
}

const SECTION_LIKE = /^(do[123]|seção|section|edition|edição)$/i;
const DATE_LIKE = /^\d{4}-\d{2}-\d{2}/;

function textContent(el: Element): string {
  return (el.textContent || "").trim();
}

function extractDates(doc: Document): string[] {
  const dates: string[] = [];
  const walk = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      for (const attr of Array.from(el.attributes)) {
        if (/(date|data|pub|publicacao)/i.test(attr.name) && DATE_LIKE.test(attr.value)) {
          dates.push(attr.value.slice(0, 10));
        }
      }
      const text = textContent(el);
      const m = text.match(/\d{4}-\d{2}-\d{2}/);
      if (m) dates.push(m[0]);
      el.childNodes.forEach(walk);
    }
  };
  walk(doc.documentElement);
  return dates;
}

function extractSections(doc: Document): string[] {
  const set = new Set<string>();
  const walk = (node: Node) => {
    if (node.nodeType === Node.ELEMENT_NODE) {
      const el = node as Element;
      const tag = el.tagName.toLowerCase();
      const name = textContent(el);
      if (SECTION_LIKE.test(tag) && name) set.add(name);
      if (tag === "pubname" || tag === "pub_name" || tag === "section") {
        if (name) set.add(name);
      }
      el.childNodes.forEach(walk);
    }
  };
  walk(doc.documentElement);
  return Array.from(set);
}

/**
 * Parse XML string and return preview (article count, date range, sections).
 */
export function parseXmlPreview(xmlString: string): XmlPreview {
  const result: XmlPreview = {
    articleCount: 0,
    dateMin: null,
    dateMax: null,
    sections: [],
  };
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlString, "text/xml");
    const parseError = doc.querySelector("parsererror");
    if (parseError) {
      result.error = textContent(parseError).slice(0, 120) || "XML inválido";
      return result;
    }

    // Article-like elements (DOU/INLabs common tag names)
    const articleTags = ["article", "materia", "materiaprincipal", "documento"];
    for (const tag of articleTags) {
      const list = doc.getElementsByTagName(tag);
      if (list.length > 0) {
        result.articleCount = list.length;
        break;
      }
    }
    if (result.articleCount === 0) {
      const byClass = doc.querySelectorAll("[class*='article'], [class*='materia']");
      if (byClass.length > 0) result.articleCount = byClass.length;
    }

    const dates = extractDates(doc);
    if (dates.length > 0) {
      dates.sort();
      result.dateMin = dates[0];
      result.dateMax = dates[dates.length - 1];
    }

    result.sections = extractSections(doc);
    if (result.sections.length === 0 && result.articleCount === 0 && !result.dateMin) {
      result.error = "Nenhum artigo ou data detectado";
    }
  } catch (e) {
    result.error = e instanceof Error ? e.message : "Erro ao analisar XML";
  }
  return result;
}
