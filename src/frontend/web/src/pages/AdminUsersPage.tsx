import { useEffect, useState } from "react";
import { ArrowLeft, Copy, KeyRound, Mail, Plus, RefreshCcw, Shield, UserRound, Users, Wrench, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { useAdminRoles, useAdminUsers, useIssueAdminToken, useRevokeAdminToken, useUpdateAdminUserRoles, useUpsertAdminUser } from "@/hooks/useAdmin";
import type { AdminIssuedToken, AdminRole, AdminUser } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type UserFormState = {
  id?: string;
  display_name: string;
  email: string;
  status: "active" | "suspended";
  is_service_account: boolean;
};

type TokenFormState = {
  token_label: string;
};

function formatDateTime(value?: string | null) {
  if (!value) return "Nunca";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Nunca";
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function emptyForm(): UserFormState {
  return {
    display_name: "",
    email: "",
    status: "active",
    is_service_account: false,
  };
}

function emptyTokenForm(): TokenFormState {
  return {
    token_label: "",
  };
}

function summarizeUsers(users: AdminUser[]) {
  return {
    total: users.length,
    active: users.filter((user) => user.status === "active").length,
    admins: users.filter((user) => user.roles.includes("admin")).length,
    serviceAccounts: users.filter((user) => user.is_service_account).length,
  };
}

export default function AdminUsersPage() {
  const usersQuery = useAdminUsers();
  const rolesQuery = useAdminRoles();
  const upsertUser = useUpsertAdminUser();
  const updateRoles = useUpdateAdminUserRoles();
  const issueToken = useIssueAdminToken();
  const revokeToken = useRevokeAdminToken();

  const users = usersQuery.data ?? [];
  const roles = rolesQuery.data ?? [];
  const summary = summarizeUsers(users);

  const [userDialogOpen, setUserDialogOpen] = useState(false);
  const [roleDialogOpen, setRoleDialogOpen] = useState(false);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [issuedTokenDialogOpen, setIssuedTokenDialogOpen] = useState(false);
  const [form, setForm] = useState<UserFormState>(emptyForm());
  const [tokenForm, setTokenForm] = useState<TokenFormState>(emptyTokenForm());
  const [selectedUser, setSelectedUser] = useState<AdminUser | null>(null);
  const [pendingRoles, setPendingRoles] = useState<string[]>([]);
  const [issuedToken, setIssuedToken] = useState<AdminIssuedToken | null>(null);

  useEffect(() => {
    if (!roleDialogOpen) {
      setPendingRoles([]);
      setSelectedUser(null);
    }
  }, [roleDialogOpen]);

  useEffect(() => {
    if (!tokenDialogOpen) {
      setTokenForm(emptyTokenForm());
      setSelectedUser(null);
    }
  }, [tokenDialogOpen]);

  useEffect(() => {
    if (!issuedTokenDialogOpen) {
      setIssuedToken(null);
    }
  }, [issuedTokenDialogOpen]);

  function openCreateDialog() {
    setForm(emptyForm());
    setUserDialogOpen(true);
  }

  function openEditDialog(user: AdminUser) {
    setForm({
      id: user.id,
      display_name: user.display_name,
      email: user.email || "",
      status: user.status === "suspended" ? "suspended" : "active",
      is_service_account: user.is_service_account,
    });
    setUserDialogOpen(true);
  }

  function openRolesDialog(user: AdminUser) {
    setSelectedUser(user);
    setPendingRoles(user.roles);
    setRoleDialogOpen(true);
  }

  function openTokenDialog(user: AdminUser) {
    setSelectedUser(user);
    setTokenForm({
      token_label: `${user.display_name.toLowerCase().replace(/\s+/g, "-").slice(0, 24)}-${user.tokens.length + 1}`,
    });
    setTokenDialogOpen(true);
  }

  async function handleSaveUser() {
    if (!form.display_name.trim()) {
      toast.error("Informe o nome do usuário.");
      return;
    }
    try {
      await upsertUser.mutateAsync({
        id: form.id,
        display_name: form.display_name.trim(),
        email: form.email.trim() || null,
        status: form.status,
        is_service_account: form.is_service_account,
      });
      toast.success(form.id ? "Usuário atualizado." : "Usuário criado.");
      setUserDialogOpen(false);
      setForm(emptyForm());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Falha ao salvar usuário.");
    }
  }

  async function handleSaveRoles() {
    if (!selectedUser) return;
    try {
      await updateRoles.mutateAsync({
        userId: selectedUser.id,
        payload: { roles: pendingRoles },
      });
      toast.success("Papéis atualizados.");
      setRoleDialogOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Falha ao atualizar papéis.");
    }
  }

  async function handleIssueToken() {
    if (!selectedUser) return;
    if (!tokenForm.token_label.trim()) {
      toast.error("Informe um rótulo para o token.");
      return;
    }
    try {
      const token = await issueToken.mutateAsync({
        userId: selectedUser.id,
        payload: { token_label: tokenForm.token_label.trim() },
      });
      setTokenDialogOpen(false);
      setIssuedToken(token);
      setIssuedTokenDialogOpen(true);
      toast.success("Token emitido.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Falha ao emitir token.");
    }
  }

  async function handleRevokeToken(tokenId: string) {
    try {
      await revokeToken.mutateAsync(tokenId);
      toast.success("Token revogado.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Falha ao revogar token.");
    }
  }

  async function handleCopyIssuedToken() {
    if (!issuedToken?.plain_token) return;
    try {
      await navigator.clipboard.writeText(issuedToken.plain_token);
      toast.success("Token copiado.");
    } catch {
      toast.error("Falha ao copiar token.");
    }
  }

  function toggleRole(roleCode: string) {
    setPendingRoles((current) =>
      current.includes(roleCode)
        ? current.filter((item) => item !== roleCode)
        : [...current, roleCode],
    );
  }

  return (
    <div className="px-4 md:px-8 py-6 md:py-10 max-w-7xl mx-auto space-y-6 md:space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-2">
          <Link to="/" className="inline-flex items-center gap-1.5 text-sm text-text-tertiary hover:text-foreground transition-colors">
            <ArrowLeft className="w-4 h-4" /> Voltar
          </Link>
          <div>
            <p className="text-[11px] uppercase tracking-[0.22em] text-text-tertiary">Operação</p>
            <h1 className="text-2xl md:text-3xl font-semibold text-foreground">Usuários e papéis</h1>
          </div>
          <p className="max-w-2xl text-sm text-text-secondary">
            Superfície administrativa ligada ao schema real de identidade no Postgres. Aqui você lista usuários, cria contas operacionais, ajusta papéis e emite ou revoga tokens de acesso.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="border-border bg-surface-elevated text-foreground hover:bg-muted"
            onClick={() => usersQuery.refetch()}
            disabled={usersQuery.isFetching}
          >
            <RefreshCcw className={`w-4 h-4 ${usersQuery.isFetching ? "animate-spin" : ""}`} />
            Atualizar
          </Button>
          <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={openCreateDialog}>
            <Plus className="w-4 h-4" />
            Novo usuário
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {[
          { label: "Total", value: summary.total, icon: Users },
          { label: "Ativos", value: summary.active, icon: UserRound },
          { label: "Admins", value: summary.admins, icon: Shield },
          { label: "Serviço", value: summary.serviceAccounts, icon: Wrench },
        ].map(({ label, value, icon: Icon }) => (
          <div key={label} className="rounded-[24px] border border-border bg-surface-elevated p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-[11px] uppercase tracking-[0.18em] text-text-tertiary">{label}</span>
              <Icon className="w-4 h-4 text-text-tertiary" />
            </div>
            <div className="mt-4 text-3xl font-semibold tracking-tight text-foreground">{value}</div>
          </div>
        ))}
      </div>

      <div className="rounded-[28px] border border-border bg-surface-elevated/90 p-4 md:p-6 shadow-sm">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Diretório de identidade</h2>
            <p className="text-xs text-text-tertiary">Consumindo `GET /api/admin/users` e `GET /api/admin/roles`.</p>
          </div>
          {roles.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {roles.map((role) => (
                <span key={role.id} className="rounded-full border border-border px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-text-secondary">
                  {role.code}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        {usersQuery.isLoading ? (
          <div className="grid gap-3">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-32 animate-pulse rounded-[22px] border border-border bg-card/70" />
            ))}
          </div>
        ) : usersQuery.isError ? (
          <div className="rounded-[22px] border border-destructive/30 bg-destructive/10 p-5 text-sm text-destructive">
            {(usersQuery.error as Error)?.message || "Falha ao carregar usuários."}
          </div>
        ) : users.length === 0 ? (
          <div className="rounded-[22px] border border-dashed border-border bg-background/40 px-6 py-10 text-center">
            <p className="text-sm font-medium text-foreground">Nenhum usuário cadastrado.</p>
            <p className="mt-2 text-xs text-text-tertiary">
              Crie o primeiro usuário ou reinicie o backend com `GABI_API_TOKENS` para sincronizar service accounts.
            </p>
          </div>
        ) : (
          <div className="grid gap-3">
            {users.map((user) => (
              <article key={user.id} className="rounded-[22px] border border-border bg-card/80 p-4 md:p-5">
                <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-lg font-semibold text-foreground">{user.display_name}</h3>
                      <span className={`rounded-full px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] ${user.status === "active" ? "bg-emerald-500/12 text-emerald-400" : "bg-amber-500/12 text-amber-300"}`}>
                        {user.status}
                      </span>
                      {user.is_service_account ? (
                        <span className="rounded-full bg-primary/12 px-2.5 py-1 text-[11px] uppercase tracking-[0.16em] text-primary">
                          service
                        </span>
                      ) : null}
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-sm text-text-secondary">
                      <span className="inline-flex items-center gap-1.5">
                        <Mail className="w-4 h-4 text-text-tertiary" />
                        {user.email || "sem email"}
                      </span>
                      <span>Último login: {formatDateTime(user.last_login_at)}</span>
                    </div>

                    <div className="flex flex-wrap gap-2">
                      {user.roles.map((role) => (
                        <span key={role} className={`rounded-full px-3 py-1 text-[11px] uppercase tracking-[0.16em] ${role === "admin" ? "bg-primary/15 text-primary" : "bg-muted text-text-secondary"}`}>
                          {role}
                        </span>
                      ))}
                      {user.roles.length === 0 ? (
                        <span className="rounded-full bg-muted px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-text-tertiary">
                          sem papel
                        </span>
                      ) : null}
                    </div>

                    {user.tokens.length > 0 ? (
                      <div className="space-y-2 rounded-2xl border border-border bg-background/40 p-3">
                        <p className="text-[11px] uppercase tracking-[0.18em] text-text-tertiary">Tokens vinculados</p>
                        <div className="grid gap-2 md:grid-cols-2">
                          {user.tokens.map((token) => (
                            <div key={token.token_id} className="rounded-xl border border-border bg-card/70 px-3 py-2 text-xs text-text-secondary">
                              <div className="flex items-center justify-between gap-2">
                                <div className="font-medium text-foreground">{token.label}</div>
                                <span className={`rounded-full px-2 py-0.5 text-[10px] uppercase tracking-[0.16em] ${token.status === "active" ? "bg-emerald-500/12 text-emerald-400" : "bg-amber-500/12 text-amber-300"}`}>
                                  {token.status}
                                </span>
                              </div>
                              <div className="mt-1 break-all text-text-tertiary">{token.token_id}</div>
                              <div className="mt-1">Último uso: {formatDateTime(token.last_used_at)}</div>
                              {token.status === "active" ? (
                                <button
                                  className="mt-2 inline-flex items-center gap-1.5 text-[11px] text-amber-300 hover:text-amber-200 transition-colors"
                                  onClick={() => handleRevokeToken(token.token_id)}
                                  disabled={revokeToken.isPending}
                                >
                                  <XCircle className="w-3.5 h-3.5" />
                                  Revogar
                                </button>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>

                  <div className="flex flex-col gap-2 md:min-w-[180px]">
                    <Button variant="outline" className="border-border bg-background/60 text-foreground hover:bg-muted" onClick={() => openEditDialog(user)}>
                      Editar cadastro
                    </Button>
                    <Button variant="outline" className="border-border bg-background/60 text-foreground hover:bg-muted" onClick={() => openRolesDialog(user)}>
                      Editar papéis
                    </Button>
                    <Button variant="outline" className="border-border bg-background/60 text-foreground hover:bg-muted" onClick={() => openTokenDialog(user)}>
                      <KeyRound className="w-4 h-4" />
                      Emitir token
                    </Button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        )}
      </div>

      <Dialog open={userDialogOpen} onOpenChange={setUserDialogOpen}>
        <DialogContent className="border-border bg-surface-elevated sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-foreground">{form.id ? "Editar usuário" : "Novo usuário"}</DialogTitle>
            <DialogDescription className="text-text-tertiary">
              Mantém o cadastro em `auth.user`. Novos registros recebem o papel `user` por padrão.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <label className="text-xs font-medium uppercase tracking-[0.16em] text-text-tertiary">Nome</label>
              <Input
                value={form.display_name}
                onChange={(event) => setForm((current) => ({ ...current, display_name: event.target.value }))}
                placeholder="Ex.: Equipe de Operações"
                className="border-border bg-background text-foreground"
              />
            </div>

            <div className="grid gap-2">
              <label className="text-xs font-medium uppercase tracking-[0.16em] text-text-tertiary">Email</label>
              <Input
                value={form.email}
                onChange={(event) => setForm((current) => ({ ...current, email: event.target.value }))}
                placeholder="nome@exemplo.com"
                className="border-border bg-background text-foreground"
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="grid gap-2">
                <label className="text-xs font-medium uppercase tracking-[0.16em] text-text-tertiary">Status</label>
                <Select value={form.status} onValueChange={(value: "active" | "suspended") => setForm((current) => ({ ...current, status: value }))}>
                  <SelectTrigger className="border-border bg-background text-foreground">
                    <SelectValue placeholder="Selecione" />
                  </SelectTrigger>
                  <SelectContent className="border-border bg-surface-elevated text-foreground">
                    <SelectItem value="active">Ativo</SelectItem>
                    <SelectItem value="suspended">Suspenso</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <label className="mt-6 flex items-center gap-3 rounded-2xl border border-border bg-background/50 px-4 py-3 text-sm text-text-secondary">
                <Checkbox
                  checked={form.is_service_account}
                  onCheckedChange={(checked) => setForm((current) => ({ ...current, is_service_account: checked === true }))}
                />
                Conta de serviço
              </label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" className="border-border bg-background text-foreground hover:bg-muted" onClick={() => setUserDialogOpen(false)}>
              Cancelar
            </Button>
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={handleSaveUser} disabled={upsertUser.isPending}>
              {upsertUser.isPending ? "Salvando..." : form.id ? "Salvar alterações" : "Criar usuário"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={roleDialogOpen} onOpenChange={setRoleDialogOpen}>
        <DialogContent className="border-border bg-surface-elevated sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-foreground">Editar papéis</DialogTitle>
            <DialogDescription className="text-text-tertiary">
              {selectedUser ? `Atualize os papéis de ${selectedUser.display_name}.` : "Selecione os papéis do usuário."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 py-2">
            {rolesQuery.isLoading ? (
              <div className="text-sm text-text-tertiary">Carregando papéis...</div>
            ) : roles.length > 0 ? (
              roles.map((role: AdminRole) => (
                <label key={role.id} className="flex items-start gap-3 rounded-2xl border border-border bg-background/50 px-4 py-3">
                  <Checkbox
                    checked={pendingRoles.includes(role.code)}
                    onCheckedChange={() => toggleRole(role.code)}
                  />
                  <span className="space-y-1">
                    <span className="block text-sm font-medium text-foreground">{role.label}</span>
                    <span className="block text-xs uppercase tracking-[0.16em] text-text-tertiary">{role.code}</span>
                    {role.description ? <span className="block text-xs text-text-secondary">{role.description}</span> : null}
                  </span>
                </label>
              ))
            ) : (
              <div className="text-sm text-text-tertiary">Nenhum papel disponível.</div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" className="border-border bg-background text-foreground hover:bg-muted" onClick={() => setRoleDialogOpen(false)}>
              Cancelar
            </Button>
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={handleSaveRoles} disabled={updateRoles.isPending || !selectedUser}>
              {updateRoles.isPending ? "Salvando..." : "Salvar papéis"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={tokenDialogOpen} onOpenChange={setTokenDialogOpen}>
        <DialogContent className="border-border bg-surface-elevated sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-foreground">Emitir token</DialogTitle>
            <DialogDescription className="text-text-tertiary">
              {selectedUser ? `Crie um novo token para ${selectedUser.display_name}. O segredo será mostrado uma única vez.` : "Crie um novo token de acesso."}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-2">
            <div className="grid gap-2">
              <label className="text-xs font-medium uppercase tracking-[0.16em] text-text-tertiary">Rótulo do token</label>
              <Input
                value={tokenForm.token_label}
                onChange={(event) => setTokenForm({ token_label: event.target.value })}
                placeholder="ex.: operacoes-notebook"
                className="border-border bg-background text-foreground"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" className="border-border bg-background text-foreground hover:bg-muted" onClick={() => setTokenDialogOpen(false)}>
              Cancelar
            </Button>
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={handleIssueToken} disabled={issueToken.isPending || !selectedUser}>
              {issueToken.isPending ? "Emitindo..." : "Emitir token"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={issuedTokenDialogOpen} onOpenChange={setIssuedTokenDialogOpen}>
        <DialogContent className="border-border bg-surface-elevated sm:max-w-xl">
          <DialogHeader>
            <DialogTitle className="text-foreground">Token emitido</DialogTitle>
            <DialogDescription className="text-text-tertiary">
              Copie agora. O segredo não poderá ser reexibido depois que este diálogo for fechado.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2">
            <div className="rounded-2xl border border-border bg-background/60 p-4">
              <p className="text-[11px] uppercase tracking-[0.16em] text-text-tertiary">Token</p>
              <p className="mt-2 break-all font-mono text-sm text-foreground">{issuedToken?.plain_token}</p>
            </div>
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs text-amber-100">
              Guarde esse valor em local seguro. A aplicação armazena apenas o identificador hash (`token_id`) e não consegue mostrar o segredo novamente.
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" className="border-border bg-background text-foreground hover:bg-muted" onClick={() => setIssuedTokenDialogOpen(false)}>
              Fechar
            </Button>
            <Button className="bg-primary text-primary-foreground hover:bg-primary/90" onClick={handleCopyIssuedToken}>
              <Copy className="w-4 h-4" />
              Copiar token
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
