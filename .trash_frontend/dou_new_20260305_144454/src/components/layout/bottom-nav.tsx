"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Search, FileText, Bell, User } from "lucide-react";
import type { AppSection } from "@/types";

// =============================================================================
// Bottom Navigation — Mobile-First Thumb Zone
// =============================================================================

interface NavItem {
  id: AppSection;
  label: string;
  icon: React.ElementType;
  badge?: number;
}

const navItems: NavItem[] = [
  { id: "search", label: "Buscar", icon: Search },
  { id: "today", label: "Hoje", icon: FileText },
  { id: "alerts", label: "Alertas", icon: Bell, badge: 0 },
  { id: "profile", label: "Perfil", icon: User },
];

interface BottomNavProps {
  activeSection: AppSection;
  onNavigate: (section: AppSection) => void;
  alertCount?: number;
  className?: string;
}

export function BottomNav({
  activeSection,
  onNavigate,
  alertCount = 0,
  className,
}: BottomNavProps) {
  return (
    <nav
      className={cn(
        "fixed bottom-0 left-0 right-0 z-50",
        "bg-base/95 backdrop-blur-lg border-t border-border",
        "safe-bottom",
        className
      )}
    >
      <div className="flex items-center justify-around h-16 max-w-lg mx-auto px-2">
        {navItems.map((item) => {
          const isActive = activeSection === item.id;
          const badgeCount = item.id === "alerts" ? alertCount : item.badge;
          const Icon = item.icon;

          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={cn(
                "flex flex-col items-center justify-center",
                "w-16 h-full rounded-xl",
                "transition-all duration-150 ease-out",
                "touch-target-lg",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand/50",
                isActive
                  ? "text-brand"
                  : "text-muted hover:text-secondary"
              )}
              aria-current={isActive ? "page" : undefined}
            >
              <div className="relative">
                <Icon
                  className={cn(
                    "w-6 h-6 transition-transform duration-150",
                    isActive && "scale-110"
                  )}
                  strokeWidth={isActive ? 2.5 : 2}
                />
                
                {/* Badge */}
                {badgeCount && badgeCount > 0 ? (
                  <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 flex items-center justify-center bg-error text-white text-2xs font-bold rounded-full">
                    {badgeCount > 9 ? "9+" : badgeCount}
                  </span>
                ) : null}
              </div>
              
              <span
                className={cn(
                  "text-2xs mt-1 font-display font-medium transition-colors",
                  isActive ? "text-brand" : "text-muted"
                )}
              >
                {item.label}
              </span>
            </button>
          );
        })}
      </div>
      
      {/* Home indicator spacing for iOS */}
      <div className="h-[env(safe-area-inset-bottom)]" />
    </nav>
  );
}
