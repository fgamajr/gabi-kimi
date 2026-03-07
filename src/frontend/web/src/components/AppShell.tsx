import React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { CommandPalette, openCommandPalette } from "@/components/CommandPalette";
import { Icons } from "@/components/Icons";

const NAV_ITEMS = [
  { to: "/", label: "Início", icon: Icons.home },
  { to: "/search", label: "Buscar", icon: Icons.search },
  { to: "/analytics", label: "Analytics", icon: Icons.analytics },
];

export const AppShell: React.FC = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const hideMobileNav = location.pathname.startsWith("/document/") || location.pathname.startsWith("/doc/");

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_top_left,rgba(90,67,176,0.12),transparent_32%),radial-gradient(circle_at_bottom_right,rgba(24,90,180,0.08),transparent_28%)]" />
      <div className="relative md:flex">
        <aside className="hidden md:flex md:w-[74px] md:min-h-screen md:sticky md:top-0 md:flex-col md:items-center md:justify-between border-r border-white/5 bg-[#0b0e14]/95 px-3 py-4">
          <div className="flex w-full flex-col items-center gap-5">
            <button
              onClick={() => navigate("/")}
              className="flex h-10 w-10 items-center justify-center rounded-2xl border border-transparent bg-transparent text-primary focus-ring"
              aria-label="GABI DOU"
            >
              <span className="text-sm font-semibold">G</span>
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
                      `flex h-10 w-10 items-center justify-center rounded-xl border transition-all ${
                        isActive
                          ? "border-primary/25 bg-primary/18 text-primary shadow-[0_0_0_1px_rgba(126,87,255,0.08)]"
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
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-transparent text-text-secondary transition-colors hover:bg-white/[0.04] hover:text-foreground focus-ring"
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
        <nav className="app-shell-mobile-nav md:hidden fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 px-4 pb-[calc(env(safe-area-inset-bottom)+0.5rem)] pt-2 backdrop-blur-xl">
          <div className="grid grid-cols-4 gap-2">
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
            <NavLink
              to="/analytics"
              className={`min-h-[52px] rounded-2xl border flex items-center justify-center gap-2 text-sm font-medium ${
                location.pathname.startsWith("/analytics")
                  ? "bg-primary/12 border-primary/25 text-primary"
                  : "bg-card border-border text-text-secondary"
              }`}
            >
              <Icons.analytics className="w-4 h-4" />
              Dados
            </NavLink>
            <button
              onClick={() => openCommandPalette()}
              className="min-h-[52px] rounded-2xl border flex items-center justify-center gap-2 text-sm font-medium bg-card border-border text-text-secondary focus-ring"
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
