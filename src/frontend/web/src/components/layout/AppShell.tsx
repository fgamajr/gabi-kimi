import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Home, Search, BarChart3, MessageSquare, Star, LogOut, LogIn, User, Settings, Sun, Moon, Users, Shield, FileUp, ListTodo } from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useState } from "react";

const NAV_ITEMS = [
  { to: "/", icon: Home, label: "Home" },
  { to: "/busca", icon: Search, label: "Busca" },
  { to: "/analytics", icon: BarChart3, label: "Analytics" },
  { to: "/chat", icon: MessageSquare, label: "Chat" },
  { to: "/favoritos", icon: Star, label: "Favoritos" },
] as const;

function UserAvatar({ name, className }: { name: string; className?: string }) {
  const initials = name.split(" ").map((n) => n[0]).join("").slice(0, 2);
  return (
    <div className={cn("rounded-full bg-primary/20 text-primary flex items-center justify-center text-xs font-bold", className)}>
      {initials}
    </div>
  );
}

function DesktopUserMenu() {
  const { user, role, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();

  if (!user) {
    return (
      <div className="flex flex-col items-center gap-2">
        <button
          onClick={toggleTheme}
          className="flex flex-col items-center justify-center w-12 h-12 rounded-xl text-text-tertiary hover:bg-muted hover:text-text-secondary transition-colors"
          aria-label={theme === "dark" ? "Modo claro" : "Modo escuro"}
        >
          {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          <span className="text-[10px] mt-0.5 font-medium">{theme === "dark" ? "Claro" : "Escuro"}</span>
        </button>
        <NavLink
          to="/login"
          className="flex flex-col items-center justify-center w-12 h-12 rounded-xl text-text-tertiary hover:bg-muted hover:text-text-secondary transition-colors"
        >
          <LogIn className="w-4 h-4" />
          <span className="text-[10px] mt-0.5 font-medium">Entrar</span>
        </NavLink>
      </div>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="w-9 h-9 rounded-full bg-primary/20 text-primary flex items-center justify-center text-xs font-bold cursor-pointer hover:ring-2 hover:ring-primary/30 transition-all" title={user.name}>
          {user.name.split(" ").map((n) => n[0]).join("").slice(0, 2)}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="right" align="end" className="w-56 bg-surface-elevated border-border">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium text-foreground">{user.name}</p>
            <p className="text-xs text-text-tertiary">{user.email}</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-text-secondary w-fit capitalize">{role}</span>
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="bg-border" />
        <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={() => navigate("/perfil")}>
          <User className="w-4 h-4" /> Perfil
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={() => navigate("/configuracoes")}>
          <Settings className="w-4 h-4" /> Configurações
        </DropdownMenuItem>
        {isAdmin ? (
          <>
            <DropdownMenuSeparator className="bg-border" />
            <DropdownMenuLabel className="text-[10px] uppercase tracking-[0.18em] text-text-tertiary">Operação</DropdownMenuLabel>
            <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={() => navigate("/admin/upload")}>
              <FileUp className="w-4 h-4" /> Upload DOU
            </DropdownMenuItem>
            <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={() => navigate("/admin/jobs")}>
              <ListTodo className="w-4 h-4" /> Jobs
            </DropdownMenuItem>
            <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={() => navigate("/admin/users")}>
              <Shield className="w-4 h-4" /> Painel operacional
            </DropdownMenuItem>
          </>
        ) : null}
        <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={toggleTheme}>
          {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          {theme === "dark" ? "Modo claro" : "Modo escuro"}
        </DropdownMenuItem>
        <DropdownMenuSeparator className="bg-border" />
        <DropdownMenuItem className="gap-2 text-text-secondary cursor-pointer" onClick={logout}>
          <LogOut className="w-4 h-4" /> Sair
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileUserSheet() {
  const { user, role, isAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const { theme, toggleTheme } = useTheme();
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button className="flex flex-col items-center justify-center min-w-[44px] min-h-[44px] rounded-xl text-text-tertiary transition-colors hover:text-text-secondary">
          {user ? (
            <>
              <UserAvatar name={user.name} className="w-5 h-5 text-[8px]" />
              <span className="text-[10px] mt-0.5 font-medium">Conta</span>
            </>
          ) : (
            <>
              <User className="w-5 h-5" />
              <span className="text-[10px] mt-0.5 font-medium">Entrar</span>
            </>
          )}
        </button>
      </SheetTrigger>
      <SheetContent side="bottom" className="rounded-t-2xl bg-surface-elevated border-border pb-safe">
        <SheetHeader>
          <SheetTitle className="text-foreground">{user ? "Minha conta" : "Conta"}</SheetTitle>
        </SheetHeader>
        <div className="py-4 space-y-4">
          {user ? (
            <>
              <div className="flex items-center gap-3">
                <UserAvatar name={user.name} className="w-10 h-10 text-sm" />
                <div>
                  <p className="text-sm font-medium text-foreground">{user.name}</p>
                  <p className="text-xs text-text-tertiary">{user.email}</p>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-text-secondary capitalize">{role}</span>
                </div>
              </div>
              <div className="space-y-1">
                <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); navigate("/perfil"); }}>
                  <User className="w-4 h-4" /> Perfil
                </button>
                <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); navigate("/configuracoes"); }}>
                  <Settings className="w-4 h-4" /> Configurações
                </button>
                {isAdmin ? (
                  <>
                    <div className="px-3 pt-2 text-[10px] uppercase tracking-[0.18em] text-text-tertiary">Operação</div>
                    <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); navigate("/admin/upload"); }}>
                      <FileUp className="w-4 h-4" /> Upload DOU
                    </button>
                    <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); navigate("/admin/jobs"); }}>
                      <ListTodo className="w-4 h-4" /> Jobs
                    </button>
                    <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); navigate("/admin/users"); }}>
                      <Shield className="w-4 h-4" /> Painel operacional
                    </button>
                  </>
                ) : null}
                <div className="border-t border-border my-2" />
                <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={toggleTheme}>
                  {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                  {theme === "dark" ? "Modo claro" : "Modo escuro"}
                </button>
                <div className="border-t border-border my-2" />
                <button className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-text-secondary hover:bg-muted transition-colors" onClick={() => { setOpen(false); logout(); }}>
                  <LogOut className="w-4 h-4" /> Sair
                </button>
              </div>
            </>
          ) : (
            <div className="text-center space-y-3">
              <p className="text-sm text-text-secondary">Você não está logado.</p>
              <button
                className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                onClick={() => { setOpen(false); navigate("/login"); }}
              >
                <LogIn className="w-4 h-4" /> Entrar
              </button>
              <button className="inline-flex items-center gap-2 text-sm text-text-tertiary hover:text-text-secondary transition-colors mt-2" onClick={toggleTheme}>
                {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                {theme === "dark" ? "Modo claro" : "Modo escuro"}
              </button>
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function AppShell() {
  const { isAdmin } = useAuth();
  const navItems = isAdmin ? [...NAV_ITEMS, { to: "/admin/upload", icon: FileUp, label: "Upload" }, { to: "/admin/jobs", icon: ListTodo, label: "Jobs" }, { to: "/admin/users", icon: Shield, label: "Operação" }] : NAV_ITEMS;

  return (
    <div className="flex min-h-screen min-h-[100dvh]">
      {/* Desktop Rail */}
      <nav className="hidden md:flex flex-col items-center w-[72px] border-r border-border bg-surface-elevated py-6 gap-2 fixed inset-y-0 left-0 z-40">
        <div className="mb-6 flex items-center justify-center w-10 h-10 rounded-lg bg-primary text-primary-foreground font-bold text-sm">
          G
        </div>
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex flex-col items-center justify-center w-12 h-12 rounded-xl text-text-tertiary transition-colors",
                isActive ? "bg-accent text-accent-foreground" : "hover:bg-muted hover:text-text-secondary"
              )
            }
          >
            <Icon className="w-5 h-5" />
            <span className="text-[10px] mt-0.5 font-medium">{label}</span>
          </NavLink>
        ))}

        <div className="mt-auto flex flex-col items-center gap-2">
          <DesktopUserMenu />
        </div>
      </nav>

      <main className="flex-1 md:ml-[72px] pb-20 md:pb-0">
        <Outlet />
      </main>

      {/* Mobile Bottom Nav */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border bg-surface-elevated/80 backdrop-blur-xl pb-safe">
        <div className="flex items-center justify-around h-16">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex flex-col items-center justify-center min-w-[44px] min-h-[44px] rounded-xl text-text-tertiary transition-colors",
                  isActive ? "text-primary" : "hover:text-text-secondary"
                )
              }
            >
              <Icon className="w-5 h-5" />
              <span className="text-[10px] mt-0.5 font-medium">{label}</span>
            </NavLink>
          ))}
          <MobileUserSheet />
        </div>
      </nav>
    </div>
  );
}
