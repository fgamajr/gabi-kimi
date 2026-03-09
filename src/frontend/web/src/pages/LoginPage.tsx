import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useI18n } from "@/hooks/useI18n";
import { Loader2, LockKeyhole, LogIn } from "lucide-react";
import { cn } from "@/lib/utils";

export default function LoginPage() {
  const { t } = useI18n();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const redirect = params.get("redirect") || "/";

  const [accessKey, setAccessKey] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(accessKey);
      navigate(redirect, { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("login.errorFallback"));
      setShake(true);
      setTimeout(() => setShake(false), 500);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center px-4 bg-background relative overflow-hidden">
      {/* Radial background */}
      <div className="absolute inset-0 -z-10 pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 70% 50% at 50% 30%, hsl(262 60% 58% / 0.10), transparent), radial-gradient(ellipse 50% 40% at 80% 90%, hsl(199 80% 50% / 0.06), transparent)",
        }}
      />

      <div className={cn("w-full max-w-sm space-y-8", shake && "animate-[shake_0.4s_ease-in-out]")}>
        {/* Logo */}
        <div className="text-center space-y-2">
          <div className="mx-auto w-14 h-14 rounded-2xl bg-primary text-primary-foreground flex items-center justify-center font-bold text-xl">
            G
          </div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">
            GABI <span className="text-primary">· DOU</span>
          </h1>
          <p className="text-xs text-text-tertiary">{t("login.subtitle")}</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="access-key" className="text-xs font-medium text-text-secondary">
              {t("login.accessKey")}
            </label>
            <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <LockKeyhole className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="access-key"
                type="password"
                autoComplete="current-password"
                required
                value={accessKey}
                onChange={(e) => setAccessKey(e.target.value)}
                className="w-full bg-transparent text-sm text-foreground placeholder:text-text-tertiary outline-none"
                placeholder={t("login.placeholder")}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !accessKey.trim()}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary text-primary-foreground py-3 text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
            {loading ? t("login.submitLoading") : t("login.submitIdle")}
          </button>

          <button
            type="button"
            disabled
            className="w-full flex items-center justify-center gap-2 rounded-xl border border-border bg-surface-elevated py-3 text-sm font-medium text-text-tertiary opacity-70 cursor-not-allowed"
          >
            {t("login.continueWithGoogle")}
            <span className="text-[10px] uppercase tracking-wider">{t("login.comingSoon")}</span>
          </button>
        </form>

        {/* Info note */}
        <p className="text-center text-[11px] text-text-tertiary leading-relaxed">
          {t("login.infoBody").split("\n").map((line, index) => (
            <span key={index}>
              {line}
              {index < 1 ? <br /> : null}
            </span>
          ))}
        </p>

        {/* Guest link */}
        <div className="text-center">
          <Link
            to="/"
            className="text-xs text-text-secondary hover:text-primary transition-colors underline underline-offset-2"
          >
            {t("login.continueAsGuest")}
          </Link>
        </div>

        <div className="rounded-xl border border-border bg-surface-elevated/60 p-3 space-y-1">
          <p className="text-[10px] font-semibold text-text-tertiary uppercase tracking-wider">{t("login.note")}</p>
          <p className="text-[11px] text-text-secondary leading-relaxed">
            {t("login.noteBody")}
          </p>
        </div>
        {error && (
          <p className="text-xs text-destructive font-medium bg-destructive/10 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
