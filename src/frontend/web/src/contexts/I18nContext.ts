import { createContext } from "react";

export type SupportedLocale = "pt-BR" | "en-US";

export interface I18nContextValue {
  locale: SupportedLocale;
  setLocale: (locale: SupportedLocale) => void;
  t: (key: string, variables?: Record<string, string | number>) => string;
}

export const I18nContext = createContext<I18nContextValue | null>(null);
