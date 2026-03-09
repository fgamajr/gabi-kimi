export const APP_NAME = "GABI DOU";
export const DEFAULT_APP_DESCRIPTION = "Busca inteligente no Diário Oficial da União com análises e alertas personalizados.";
let currentLocale = "pt-BR";

export function setIntlLocale(locale: string) {
  currentLocale = locale;
}

export function getIntlLocale() {
  return currentLocale;
}

function normalizeDate(value?: string | number | Date | null) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value?: string | number | Date | null, fallback = "") {
  const date = normalizeDate(value);
  return date ? new Intl.DateTimeFormat(currentLocale).format(date) : fallback;
}

export function formatLongDate(value?: string | number | Date | null, fallback = "") {
  const date = normalizeDate(value);
  return date
    ? new Intl.DateTimeFormat(currentLocale, {
        weekday: "long",
        day: "2-digit",
        month: "long",
        year: "numeric",
      }).format(date)
    : fallback;
}

export function formatDateTime(value?: string | number | Date | null, fallback = "") {
  const date = normalizeDate(value);
  return date
    ? new Intl.DateTimeFormat(currentLocale, {
        day: "2-digit",
        month: "short",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date)
    : fallback;
}

export function formatTime(value?: string | number | Date | null, fallback = "") {
  const date = normalizeDate(value);
  return date
    ? new Intl.DateTimeFormat(currentLocale, {
        hour: "2-digit",
        minute: "2-digit",
      }).format(date)
    : fallback;
}

export function formatNumber(value?: number | null, fallback = "0") {
  return typeof value === "number" ? new Intl.NumberFormat(currentLocale).format(value) : fallback;
}

export function buildPageTitle(pageTitle: string) {
  return `${pageTitle} | ${APP_NAME}`;
}
