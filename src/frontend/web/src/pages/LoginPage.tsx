import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useI18n } from "@/hooks/useI18n";
import { Loader2, LockKeyhole, LogIn, Eye, EyeOff, Mail } from "lucide-react";
import { cn } from "@/lib/utils";
import { AuthApiError } from "@/lib/authApi";

type LoginMode = "password" | "token";

export default function LoginPage() {
  const { t } = useI18n();
  const { login, loginWithPassword } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const redirect = params.get("redirect") || "/";

  const [mode, setMode] = useState<LoginMode>("password");

  // Password mode state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  // Token mode state
  const [accessKey, setAccessKey] = useState("");

  // Shared state
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);

  function triggerShake() {
    setShake(true);
    setTimeout(() => setShake(false), 500);
  }

  function mapPasswordError(err: unknown): string {
    if (err instanceof AuthApiError) {
      switch (err.status) {
        case 401:
          return "Email ou senha incorretos";
        case 429:
          return "Muitas tentativas. Tente novamente em alguns minutos.";
        default:
          return err.detail || "Erro ao autenticar.";
      }
    }
    return err instanceof Error ? err.message : "Erro ao autenticar.";
  }

  async function handlePasswordSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await loginWithPassword(email, password);
      navigate(redirect, { replace: true });
    } catch (err: unknown) {
      setError(mapPasswordError(err));
      triggerShake();
    } finally {
      setLoading(false);
    }
  }

  async function handleTokenSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(accessKey);
      navigate(redirect, { replace: true });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t("login.errorFallback"));
      triggerShake();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center px-4 bg-background relative overflow-hidden">
      {/* Radial background */}
      <div
        className="absolute inset-0 -z-10 pointer-events-none"
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
            GABI <span className="text-primary">&middot; DOU</span>
          </h1>
          <p className="text-xs text-text-tertiary">{t("login.subtitle")}</p>
        </div>

        {mode === "password" ? (
          <>
            {/* Email + Password Form */}
            <form onSubmit={handlePasswordSubmit} className="space-y-4">
              {/* Email */}
              <div className="space-y-1.5">
                <label htmlFor="login-email" className="text-xs font-medium text-text-secondary">
                  Email
                </label>
                <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
                  <Mail className="w-4 h-4 text-text-tertiary shrink-0" />
                  <input
                    id="login-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none"
                    placeholder="seu@email.com"
                  />
                </div>
              </div>

              {/* Password */}
              <div className="space-y-1.5">
                <label htmlFor="login-password" className="text-xs font-medium text-text-secondary">
                  Senha
                </label>
                <div className="relative flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
                  <LockKeyhole className="w-4 h-4 text-text-tertiary shrink-0" />
                  <input
                    id="login-password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none pr-10"
                    placeholder="Sua senha"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    className="absolute right-3 p-1 text-text-tertiary hover:text-text-secondary transition-colors"
                    aria-label={showPassword ? "Ocultar senha" : "Mostrar senha"}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* Submit */}
              <button
                type="submit"
                disabled={loading || !email.trim() || !password.trim()}
                className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary text-primary-foreground py-3 text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <LogIn className="w-4 h-4" />}
                {loading ? "Validando..." : "Entrar"}
              </button>
            </form>

            {/* Register link */}
            <p className="text-center text-sm text-text-secondary">
              Nao tem conta?{" "}
              <Link
                to={`/cadastro${redirect !== "/" ? `?redirect=${encodeURIComponent(redirect)}` : ""}`}
                className="text-primary hover:text-primary/80 font-medium transition-colors"
              >
                Criar conta
              </Link>
            </p>

            {/* Token login secondary */}
            <div className="text-center">
              <button
                type="button"
                onClick={() => { setError(""); setMode("token"); }}
                className="text-xs text-text-tertiary hover:text-text-secondary transition-colors underline underline-offset-2"
              >
                Entrar com chave de acesso
              </button>
            </div>
          </>
        ) : (
          <>
            {/* Token Form */}
            <form onSubmit={handleTokenSubmit} className="space-y-4">
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
                    className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none"
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
            </form>

            {/* Back to email login */}
            <div className="text-center">
              <button
                type="button"
                onClick={() => { setError(""); setMode("password"); }}
                className="text-xs text-text-secondary hover:text-primary transition-colors underline underline-offset-2"
              >
                Voltar para login com email
              </button>
            </div>
          </>
        )}

        {/* Guest link */}
        <div className="text-center">
          <Link
            to="/"
            className="text-xs text-text-secondary hover:text-primary transition-colors underline underline-offset-2"
          >
            {t("login.continueAsGuest")}
          </Link>
        </div>

        {/* Error display */}
        {error && (
          <p className="text-xs text-destructive font-medium bg-destructive/10 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
