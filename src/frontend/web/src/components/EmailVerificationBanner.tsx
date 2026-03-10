import { Mail, Loader2 } from "lucide-react";
import { useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { resendVerification } from "@/lib/authApi";
import { Button } from "@/components/ui/button";

export function EmailVerificationBanner() {
  const { user } = useAuth();
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<"idle" | "sent" | "error">("idle");

  if (!user || user.emailVerified !== false) return null;

  async function handleResend() {
    setSending(true);
    setMessage("idle");
    try {
      await resendVerification();
      setMessage("sent");
    } catch {
      setMessage("error");
    } finally {
      setSending(false);
    }
  }

  return (
    <div
      role="region"
      aria-label="Verificação de email"
      className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 bg-primary/10 border-b border-primary/20 text-sm text-foreground"
    >
      <div className="flex items-center gap-2 min-w-0">
        <Mail className="w-4 h-4 shrink-0 text-primary" />
        <span>
          Confirme seu email para receber alertas e notificações.
        </span>
      </div>
      <Button
        variant="outline"
        size="sm"
        onClick={handleResend}
        disabled={sending}
        className="shrink-0 border-primary/30 hover:bg-primary/10"
      >
        {sending ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : message === "sent" ? (
          "Enviado!"
        ) : message === "error" ? (
          "Tente de novo"
        ) : (
          "Reenviar email de verificação"
        )}
      </Button>
    </div>
  );
}
