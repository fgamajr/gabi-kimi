import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { Loader2, Mail, ArrowLeft } from "lucide-react";
import { cn } from "@/lib/utils";
import { forgotPassword } from "@/lib/authApi";
import { AuthApiError } from "@/lib/authApi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await forgotPassword(email);
      setSent(true);
    } catch (err: unknown) {
      setError(
        err instanceof AuthApiError
          ? err.detail
          : err instanceof Error
            ? err.message
            : "Erro ao enviar",
      );
    } finally {
      setLoading(false);
    }
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
            Esqueceu sua senha?
          </h1>
          <p className="text-sm text-text-secondary">
            Digite seu email e enviaremos instruções para redefinir.
          </p>
        </div>

        {sent ? (
          <div className="space-y-4 text-center">
            <p className="text-sm text-foreground bg-primary/10 rounded-xl px-4 py-3">
              Se este email estiver cadastrado, você receberá um email com o link para redefinir sua senha.
            </p>
            <Link
              to="/login"
              className="inline-flex items-center gap-2 text-sm text-primary hover:text-primary/80 font-medium"
            >
              <ArrowLeft className="w-4 h-4" />
              Voltar para login
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="forgot-email" className="text-xs font-medium text-text-secondary">
                Email
              </label>
              <div className="flex items-center gap-3 rounded-xl border border-border bg-surface-elevated px-4 py-3 focus-within:border-primary focus-within:ring-1 focus-within:ring-ring transition-colors">
                <Mail className="w-4 h-4 text-text-tertiary shrink-0" />
                <input
                  id="forgot-email"
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

            <button
              type="submit"
              disabled={loading || !email.trim()}
              className={cn(
                "w-full flex items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 focus:ring-offset-background",
                "bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-60",
              )}
            >
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
              {loading ? "Enviando..." : "Enviar instruções"}
            </button>

            <div className="text-center">
              <Link
                to="/login"
                className="inline-flex items-center gap-2 text-xs text-text-secondary hover:text-primary transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                Voltar para login
              </Link>
            </div>
          </form>
        )}

        {error && (
          <p className="text-xs text-destructive font-medium bg-destructive/10 rounded-lg px-3 py-2">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
