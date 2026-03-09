import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import type { SupportedLocale } from "@/contexts/I18nContext";
import { useI18n } from "@/hooks/useI18n";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";

export default function UserSettingsPage() {
  const { user, isAdmin, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const { locale, setLocale, t } = useI18n();

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-2xl mx-auto">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-text-tertiary hover:text-foreground mb-8 transition-colors">
        <ArrowLeft className="w-4 h-4" /> {t("common.actions.back")}
      </Link>

      <h1 className="text-xl font-bold text-foreground mb-6">{t("settings.title")}</h1>

      {user ? (
        <div className="space-y-4">
          <div className="bg-surface-elevated rounded-xl p-5 border border-border space-y-4">
            <h2 className="text-sm font-semibold text-foreground">{t("settings.theme")}</h2>
            <p className="text-xs text-text-tertiary">{t("settings.themeBody")}</p>
            <button
              onClick={toggleTheme}
              className="inline-flex min-h-[44px] items-center rounded-lg border border-border px-4 py-2 text-sm text-foreground hover:border-primary/30 transition-colors"
            >
              {t("settings.switchTo", { mode: theme === "dark" ? t("appShell.account.light").toLowerCase() : t("appShell.account.dark").toLowerCase() })}
            </button>
          </div>
          <div className="bg-surface-elevated rounded-xl p-5 border border-border space-y-4">
            <h2 className="text-sm font-semibold text-foreground">{t("settings.session")}</h2>
            <p className="text-xs text-text-tertiary">{t("settings.sessionBody")}</p>
            <button
              onClick={logout}
              className="inline-flex min-h-[44px] items-center rounded-lg border border-border px-4 py-2 text-sm text-foreground hover:border-primary/30 transition-colors"
            >
              {t("settings.signOut")}
            </button>
          </div>
          <div className="bg-surface-elevated rounded-xl p-5 border border-border space-y-4">
            <h2 className="text-sm font-semibold text-foreground">{t("settings.currentState")}</h2>
            <p className="text-xs text-text-tertiary">{t("settings.currentStateBody")}</p>
            {isAdmin ? (
              <Link to="/admin/users" className="inline-flex min-h-[44px] items-center rounded-lg border border-border px-4 py-2 text-sm text-foreground hover:border-primary/30 transition-colors">
                {t("settings.openUserManagement")}
              </Link>
            ) : null}
          </div>
          <div className="bg-surface-elevated rounded-xl p-5 border border-border space-y-4">
            <h2 className="text-sm font-semibold text-foreground">{t("settings.language")}</h2>
            <p className="text-xs text-text-tertiary">{t("settings.languageBody")}</p>
            <select
              value={locale}
              onChange={(event) => setLocale(event.target.value as SupportedLocale)}
              className="min-h-[44px] rounded-lg border border-border bg-background px-3 text-sm text-foreground"
            >
              <option value="pt-BR">Português (Brasil)</option>
              <option value="en-US">English (US)</option>
            </select>
          </div>
        </div>
      ) : (
        <p className="text-text-secondary text-sm">{t("settings.loginRequired")}</p>
      )}
    </div>
  );
}
