import React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { CommandPalette, openCommandPalette } from "@/components/CommandPalette";
import { Icons } from "@/components/Icons";

const NAV_ITEMS = [
  { to: "/", label: "Início", icon: Icons.home },
  { to: "/search", label: "Buscar", icon: Icons.search },
];

export const AppShell: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const hideMobileNav = location.pathname.startsWith("/document/") || location.pathname.startsWith("/doc/");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="md:flex">
        <aside className="hidden md:flex md:w-[88px] md:min-h-screen md:sticky md:top-0 md:flex-col md:items-center md:justify-between border-r border-border bg-surface-sunken px-3 py-6">
          <div className="flex flex-col items-center gap-6 w-full">
            <button
              onClick={() => navigate("/")}
              className="w-11 h-11 rounded-2xl bg-card border border-border flex items-center justify-center focus-ring"
              aria-label="GABI DOU"
            >
              <span className="text-sm font-bold text-primary">G</span>
            </button>
            <nav className="flex flex-col gap-2 w-full items-center">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      `w-12 h-12 rounded-2xl border flex items-center justify-center transition-colors ${
                        isActive
                          ? "bg-primary/12 border-primary/25 text-primary"
                          : "bg-card border-border text-text-secondary hover:text-foreground hover:bg-secondary"
                      }`
                    }
                    aria-label={item.label}
                  >
                    <Icon className="w-5 h-5" />
                  </NavLink>
                );
              })}
            </nav>
          </div>
          <div className="text-[10px] uppercase tracking-[0.16em] text-text-tertiary rotate-180 [writing-mode:vertical-rl]">
            GABI · DOU
          </div>
        </aside>

        <div className="flex-1 min-w-0">
          <div className="hidden md:flex items-center justify-end px-4 pt-4">
            <button
              onClick={() => openCommandPalette()}
              className="inline-flex items-center gap-2 rounded-2xl border border-border bg-card px-3 py-2 text-sm text-text-secondary hover:text-foreground hover:bg-secondary transition-colors focus-ring"
              aria-label="Abrir pesquisa rápida"
            >
              <Icons.search className="w-4 h-4" />
              Pesquisa rápida
              <span className="rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] text-text-tertiary">⌘K</span>
            </button>
          </div>
          <Outlet />
        </div>
      </div>

      {!hideMobileNav ? (
        <nav className="md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 backdrop-blur-xl px-4 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] pt-2">
          <div className="grid grid-cols-3 gap-2">
            <NavLink
              to="/"
              end
              className={`min-h-[52px] rounded-2xl border flex items-center justify-center gap-2 text-sm font-medium ${
                location.pathname === "/"
                  ? "bg-primary/12 border-primary/25 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.home className="w-4 h-4" />
              Início
            </NavLink>
            <button
              onClick={() => openCommandPalette()}
              className="min-h-[52px] rounded-2xl border flex items-center justify-center gap-2 text-sm font-medium bg-card border-border text-text-secondary focus-ring"
            >
              <Icons.command className="w-4 h-4" />
              Comando
            </button>
            <NavLink
              to="/search"
              className={`min-h-[52px] rounded-2xl border flex items-center justify-center gap-2 text-sm font-medium ${
                location.pathname.startsWith("/search")
                  ? "bg-primary/12 border-primary/25 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.search className="w-4 h-4" />
              Buscar
            </NavLink>
          </div>
        </nav>
      ) : (
        <button
          onClick={() => openCommandPalette()}
          className="md:hidden fixed right-4 bottom-24 z-40 min-h-[52px] min-w-[52px] rounded-2xl border border-border bg-card/95 backdrop-blur-xl text-text-secondary shadow-[var(--shadow-lg)] flex items-center justify-center focus-ring"
          aria-label="Abrir comando"
        >
          <Icons.command className="w-5 h-5" />
        </button>
      )}

      <CommandPalette />
    </div>
  );
};
