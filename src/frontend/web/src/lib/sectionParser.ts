export interface Section {
  id: string;
  label: string;
  element: HTMLElement;
}

const PATTERNS: Array<{ regex: RegExp; prefix: string; labelFn: (match: string) => string }> = [
  {
    regex: /Art\.\s*\d+[ºª°]?/,
    prefix: 'art',
    labelFn: (m) => m.replace(/\s+/g, ' ').trim(),
  },
  {
    regex: /CAP[ÍI]TULO\s+[IVXLCDM]+/,
    prefix: 'cap',
    labelFn: (m) => m.replace(/\s+/g, ' ').trim(),
  },
  {
    regex: /SE[ÇC][ÃA]O\s+[IVXLCDM]+/,
    prefix: 'sec',
    labelFn: (m) => m.replace(/\s+/g, ' ').trim(),
  },
  {
    regex: /T[ÍI]TULO\s+[IVXLCDM]+/,
    prefix: 'tit',
    labelFn: (m) => m.replace(/\s+/g, ' ').trim(),
  },
  {
    regex: /^(DO|DA|DOS|DAS)\s+[A-ZÁÊÇÃÕÉÍÓÚ]{2,}/m,
    prefix: 'named',
    labelFn: (m) => {
      const clean = m.replace(/\s+/g, ' ').trim();
      return clean.length > 40 ? clean.slice(0, 37) + '…' : clean;
    },
  },
];

function slugify(text: string): string {
  return text
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 30);
}

/**
 * Parse sections from rendered DOM content.
 * Walks all text nodes inside the container, detects section patterns,
 * and assigns IDs to the parent elements for anchor linking.
 */
export function parseSections(container: HTMLElement): Section[] {
  const sections: Section[] = [];
  const seen = new Set<string>();

  // Walk block-level elements
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let node: Text | null;

  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent?.trim();
    if (!text || text.length < 3) continue;

    for (const pattern of PATTERNS) {
      const match = text.match(pattern.regex);
      if (!match) continue;

      const label = pattern.labelFn(match[0]);
      const id = `${pattern.prefix}-${slugify(match[0])}`;

      if (seen.has(id)) continue;
      seen.add(id);

      // Find the nearest block parent
      let el = node.parentElement;
      while (el && el !== container && getComputedStyle(el).display === 'inline') {
        el = el.parentElement;
      }
      if (!el || el === container) continue;

      // Assign anchor ID
      if (!el.id) el.id = id;

      sections.push({ id: el.id, label, element: el });
      break; // one match per text node
    }
  }

  return sections;
}
