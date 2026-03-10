import { useState, type FormEvent } from "react";
import { useSearchParams, Link, useNavigate } from "react-router-dom";
import { Loader2, LockKeyhole, Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { resetPassword } from "@/lib/authApi";
import { AuthApiError } from "@/lib/authApi";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const valid = password.length >= 8 && password === confirm;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token || !valid) return;
    setError("");
    setLoading(true);
    try {
      await resetPassword(token, password);
      navigate("/login", { replace: true, state: { message: "Senha redefinida. Faça login com a nova senha." } });
    } catch (err: unknown) {
      setError(
        err instanceof AuthApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erro ao redefinir senha",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!token) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center px-4 bg-background">
        <div className="w-full max-w-sm space-y-4 text-center">
          <p className="text-sm text-destructive font-medium">
            Link inválido. Solicite um novo link para redefinir sua senha.
          </p>
          <Link to="/forgot-password" className="text-sm text-primary hover:text-primary/80 font-medium">
            Solicitar novo link
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[100dvh] flex items-center justify-center px-4 bg-background relative overflow-hidden">
      <div
        className="absolute inset-0 -z-10 pointer-events-none"
        style={{
          backgroundImage:
            "radial-gradient(ellipse 70% 50% at 50% 30%, hsl(262 60% 58% / 0.10), transparent), radial-gradient(ellipse 50% 40% at 80% 90%, hsl(199 80% 50% / 0.06), transparent)",
        }}
      />

      <div className="w-full max-w-sm space-y-8">
        <div className="text-center space-y-2">
          <div className="mx-auto w-14 h-14 rounded-2xl bg-primary text-primary-foreground flex items-center justify-center font-bold text-xl">
            G
          </div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">
            Nova senha
          </h1>
          <p className="text-sm text-text-secondary">
            Defina uma nova senha (mínimo 8 caracteres).
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="reset-password" className="text-xs font-medium text-text-secondary">
              Senha
            </label>
            <div className="relative flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <LockKeyhole className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="reset-password"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none pr-10"
                placeholder="Mínimo 8 caracteres"
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

          <div className="space-y-1.5">
            <label htmlFor="reset-confirm" className="text-xs font-medium text-text-secondary">
              Confirmar senha
            </label>
            <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
              <LockKeyhole className="w-4 h-4 text-text-tertiary shrink-0" />
              <input
                id="reset-confirm"
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                required
                minLength={8}
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                className="w-full bg-transparent text-base text-foreground placeholder:text-text-tertiary outline-none"
                placeholder="Repita a senha"
              />
            </div>
            {confirm && password !== confirm && (
              <p className="text-xs text-destructive">As senhas não coincidem.</p>
            )}
          </div>

          <button
            type="submit"
            disabled={loading || !valid}
            className={cn(
              "w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
              "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-60",
            )}
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            {loading ? "Redefinindo..." : "Redefinir senha"}
          </button>

          <div className="text-center">
            <Link to="/login" className="text-xs text-text-secondary hover:text-primary transition-colors">
              Voltar para login
            </Link>
          </div>
        </form>

        {error && (
          <p className="text-xs text-destructive font-medium bg-destructive/10 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
