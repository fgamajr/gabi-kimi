import React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { CommandPalette, openCommandPalette } from "@/components/CommandPalette";
import { Icons } from "@/components/Icons";

const NAV_ITEMS = [
  { to: "/", label: "Início", icon: Icons.home },
  { to: "/search", label: "Buscar", icon: Icons.search },
  { to: "/chat", label: "Chat", icon: Icons.chat },
  { to: "/analytics", label: "Analytics", icon: Icons.analytics },
];

export const AppShell: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const hideMobileNav = location.pathname.startsWith("/document/") || location.pathname.startsWith("/doc/");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(120,80,220,0.06),transparent_30%),radial-gradient(circle_at_82%_18%,rgba(80,100,180,0.05),transparent_24%),radial-gradient(circle_at_bottom_right,rgba(100,120,200,0.04),transparent_24%)]" />
      <div className="relative md:flex">
        <aside className="hidden border-r border-white/5 bg-[rgba(12,14,24,0.92)] px-3 py-4 md:sticky md:top-0 md:flex md:min-h-screen md:w-[78px] md:flex-col md:items-center md:justify-between backdrop-blur-xl">
          <div className="flex w-full flex-col items-center gap-5">
            <button
              onClick={() => navigate("/")}
              className="flex h-11 w-11 items-center justify-center rounded-[1.35rem] border border-white/10 bg-white/[0.03] text-primary focus-ring"
              aria-label="GABI DOU"
            >
              <span className="font-editorial text-lg font-semibold leading-none">G</span>
            </button>

            <nav className="flex w-full flex-col items-center gap-2">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      `flex h-11 w-11 items-center justify-center rounded-[1.05rem] border transition-all ${
                        isActive
                          ? "border-primary/20 bg-primary/12 text-primary shadow-[0_18px_36px_rgba(0,0,0,0.18)]"
                          : "border-transparent bg-transparent text-text-secondary hover:bg-white/[0.04] hover:text-foreground"
                      }`
                    }
                    aria-label={item.label}
                    title={item.label}
                  >
                    <Icon className="h-[18px] w-[18px]" />
                  </NavLink>
                );
              })}
            </nav>
          </div>

          <button
            onClick={() => openCommandPalette()}
            className="flex h-11 w-11 items-center justify-center rounded-[1.05rem] border border-transparent text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
            aria-label="Comandos"
            title="Comandos"
          >
            <Icons.settings className="h-[18px] w-[18px]" />
          </button>
        </aside>

        <div className="min-w-0 flex-1">
          <Outlet />
        </div>
      </div>

      {!hideMobileNav ? (
        <nav className="app-shell-mobile-nav fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 px-4 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] pt-2 backdrop-blur-xl md:hidden">
          <div className="grid grid-cols-5 gap-2">
            <NavLink
              to="/"
              end
              className={`flex min-h-[52px] items-center justify-center gap-2 rounded-[1.15rem] border text-sm font-medium ${
                location.pathname === "/"
                  ? "border-primary/20 bg-primary/12 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.home className="w-4 h-4" />
              Início
            </NavLink>
            <NavLink
              to="/search"
              className={`flex min-h-[52px] items-center justify-center gap-2 rounded-[1.15rem] border text-sm font-medium ${
                location.pathname.startsWith("/search")
                  ? "border-primary/20 bg-primary/12 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.search className="w-4 h-4" />
              Buscar
            </NavLink>
            <NavLink
              to="/analytics"
              className={`flex min-h-[52px] items-center justify-center gap-2 rounded-[1.15rem] border text-sm font-medium ${
                location.pathname.startsWith("/analytics")
                  ? "border-primary/20 bg-primary/12 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.analytics className="w-4 h-4" />
              Dados
            </NavLink>
            <NavLink
              to="/chat"
              className={`flex min-h-[52px] items-center justify-center gap-2 rounded-[1.15rem] border text-sm font-medium ${
                location.pathname.startsWith("/chat")
                  ? "border-primary/20 bg-primary/12 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.chat className="w-4 h-4" />
              Chat
            </NavLink>
            <button
              onClick={() => openCommandPalette()}
              className="flex min-h-[52px] items-center justify-center gap-2 rounded-[1.15rem] border border-border bg-card text-sm font-medium text-text-secondary focus-ring"
            >
              <Icons.command className="w-4 h-4" />
              Comando
            </button>
          </div>
        </nav>
      ) : null}

      <CommandPalette />
    </div>
  );
};
