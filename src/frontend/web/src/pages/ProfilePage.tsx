import { ArrowLeft, KeyRound, ShieldCheck, TimerReset, User, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";

export default function ProfilePage() {
  const { user, role, roles, isAdmin } = useAuth();

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-2xl mx-auto">
      <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-text-tertiary hover:text-foreground mb-8 transition-colors">
        <ArrowLeft className="w-4 h-4" /> Voltar
      </Link>

      <h1 className="text-xl font-bold text-foreground mb-6">Perfil</h1>

      {user ? (
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 rounded-full bg-primary/20 text-primary flex items-center justify-center text-xl font-bold">
              {user.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
            </div>
            <div>
              <p className="text-lg font-semibold text-foreground">{user.name}</p>
              <span className="text-xs px-2 py-0.5 rounded-full bg-muted text-text-secondary capitalize">{role}</span>
            </div>
          </div>

          <div className="space-y-4 bg-surface-elevated rounded-xl p-5 border border-border">
            <div className="flex items-center gap-3">
              <User className="w-4 h-4 text-text-tertiary" />
              <div>
                <p className="text-xs text-text-tertiary">Principal da sessão</p>
                <p className="text-sm text-foreground">{user.name}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <ShieldCheck className="w-4 h-4 text-text-tertiary" />
              <div>
                <p className="text-xs text-text-tertiary">Escopo da sessão</p>
                <p className="text-sm text-foreground capitalize">{role}</p>
                <p className="text-xs text-text-tertiary mt-1">Papéis: {roles.join(", ") || "visitor"}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <TimerReset className="w-4 h-4 text-text-tertiary" />
              <div>
                <p className="text-xs text-text-tertiary">Sessão iniciada</p>
                <p className="text-sm text-foreground">{new Date(user.lastLoginAt).toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <KeyRound className="w-4 h-4 text-text-tertiary" />
              <div>
                <p className="text-xs text-text-tertiary">Modelo de autenticação</p>
                <p className="text-sm text-foreground">Sessão protegida por chave de acesso do ambiente</p>
              </div>
            </div>
            {isAdmin ? (
              <div className="flex items-center gap-3">
                <Users className="w-4 h-4 text-text-tertiary" />
                <div>
                  <p className="text-xs text-text-tertiary">Operação</p>
                  <Link to="/admin/users" className="text-sm text-primary hover:underline">
                    Abrir painel de usuários
                  </Link>
                </div>
              </div>
            ) : null}
          </div>

          <p className="text-xs leading-6 text-text-tertiary">
            Este perfil reflete a sessão ativa do navegador e os papéis devolvidos pelo backend. Google SSO e preferências persistidas ainda não estão conectados neste ambiente.
          </p>
        </div>
      ) : (
        <p className="text-text-secondary text-sm">Faça login para ver seu perfil.</p>
      )}
    </div>
  );
}
