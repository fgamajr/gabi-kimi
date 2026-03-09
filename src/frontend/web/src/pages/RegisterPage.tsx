import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { Loader2, LockKeyhole, Mail, User, Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { AuthApiError } from "@/lib/authApi";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const redirect = params.get("redirect") || "/";

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);

  const isFormValid = displayName.trim().length >= 2 && email.trim().length > 0 && password.length >= 8;

  function mapRegisterError(err: unknown): string {
    if (err instanceof AuthApiError) {
      switch (err.status) {
        case 409:
          return "Este email ja esta cadastrado";
        case 429:
          return "Muitas tentativas. Tente novamente mais tarde.";
        case 422:
          return "Verifique os dados informados";
        default:
          return err.detail || "Erro ao criar conta.";
      }
    }
    return err instanceof Error ? err.message : "Erro ao criar conta.";
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!isFormValid) return;
    setError("");
    setLoading(true);
    try {
      await register(email, password, displayName.trim());
      navigate(redirect, { replace: true });
    } catch (err: unknown) {
      setError(mapRegisterError(err));
      setShake(true);
      setTimeout(() => setShake(false), 500);
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
          <p className="text-xs text-text-tertiary">Criar sua conta</p>
        </div>

        {/* Register Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Display Name */}
          <div className="space-y-1.5">
            <label htmlFor="register-name" className="text-xs font-medium text-text-secondary">
              Nome
            </label>
            <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <User className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="register-name"
                type="text"
                autoComplete="name"
                required
                minLength={2}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none"
                placeholder="Seu nome"
              />
            </div>
          </div>

          {/* Email */}
          <div className="space-y-1.5">
            <label htmlFor="register-email" className="text-xs font-medium text-text-secondary">
              Email
            </label>
            <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <Mail className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="register-email"
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
            <label htmlFor="register-password" className="text-xs font-medium text-text-secondary">
              Senha
            </label>
            <div className="relative flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <LockKeyhole className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="register-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
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
            <p className="text-[11px] text-text-tertiary pl-1">Minimo 8 caracteres</p>
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={loading || !isFormValid}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary text-primary-foreground py-3 text-sm font-semibold hover:bg-primary/90 disabled:opacity-60 transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            {loading ? "Criando conta..." : "Criar conta"}
          </button>
        </form>

        {/* Login link */}
        <p className="text-center text-sm text-text-secondary">
          Ja tem conta?{" "}
          <Link
            to={`/login${redirect !== "/" ? `?redirect=${encodeURIComponent(redirect)}` : ""}`}
            className="text-primary hover:text-primary/80 font-medium transition-colors"
          >
            Entrar
          </Link>
        </p>

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
