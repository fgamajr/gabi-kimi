import type { SupportedLocale } from "@/contexts/I18nContext";
import { enUSMessages } from "./en-US";
import { ptBRMessages } from "./pt-BR";

export const messages = {
  "pt-BR": ptBRMessages,
  "en-US": enUSMessages,
} as const satisfies Record<SupportedLocale, Record<string, unknown>>;
