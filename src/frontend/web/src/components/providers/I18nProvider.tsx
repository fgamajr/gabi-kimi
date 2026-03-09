import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { I18nContext, type SupportedLocale } from "@/contexts/I18nContext";
import { messages } from "@/i18n/messages";
import { setIntlLocale } from "@/lib/intl";

const STORAGE_KEY = "gabi_locale";
const DEFAULT_LOCALE: SupportedLocale = "pt-BR";

function detectLocale(): SupportedLocale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "pt-BR" || stored === "en-US") return stored;
  return window.navigator.language.toLowerCase().startsWith("pt") ? "pt-BR" : "en-US";
}

function getByPath(source: Record<string, unknown>, key: string): string | null {
  const parts = key.split(".");
  let current: unknown = source;
  for (const part of parts) {
    if (!current || typeof current !== "object" || !(part in current)) return null;
    current = (current as Record<string, unknown>)[part];
  }
  return typeof current === "string" ? current : null;
}

function interpolate(template: string, variables?: Record<string, string | number>) {
  if (!variables) return template;
  return template.replace(/\{(\w+)\}/g, (_, token: string) => String(variables[token] ?? `{${token}}`));
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<SupportedLocale>(detectLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
    window.localStorage.setItem(STORAGE_KEY, locale);
    setIntlLocale(locale);

    const descriptionMeta = document.querySelector('meta[name="description"]');
    const description = getByPath(messages[locale], "app.description");
    if (descriptionMeta && description) {
      descriptionMeta.setAttribute("content", description);
    }
  }, [locale]);

  const dictionary = useMemo(() => messages[locale], [locale]);
  const fallbackDictionary = messages[DEFAULT_LOCALE];

  const t = useCallback((key: string, variables?: Record<string, string | number>) => {
    const template = getByPath(dictionary, key) || getByPath(fallbackDictionary, key) || key;
    return interpolate(template, variables);
  }, [dictionary, fallbackDictionary]);

  const value = useMemo(() => ({
    locale,
    setLocale,
    t,
  }), [locale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
