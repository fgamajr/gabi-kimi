import { useContext } from "react";
import { I18nContext } from "@/contexts/I18nContext";
import { messages } from "@/i18n/messages";

const fallbackContext = {
  locale: "pt-BR" as const,
  setLocale: () => undefined,
  t: (key: string, variables?: Record<string, string | number>) => {
    const parts = key.split(".");
    let current: unknown = messages["pt-BR"];
    for (const part of parts) {
      if (!current || typeof current !== "object" || !(part in current)) return key;
      current = (current as Record<string, unknown>)[part];
    }
    if (typeof current !== "string") return key;
    return current.replace(/\{(\w+)\}/g, (_, token: string) => String(variables?.[token] ?? `{${token}}`));
  },
};

export function useI18n() {
  const ctx = useContext(I18nContext);
  return ctx || fallbackContext;
}
