import { useEffect, useMemo } from "react";
import { matchPath, useLocation } from "react-router-dom";
import { useI18n } from "@/hooks/useI18n";
import { buildPageTitle } from "@/lib/intl";

const ROUTE_LABELS: Array<{ pattern: string; key: string }> = [
  { pattern: "/", key: "route.home" },
  { pattern: "/busca", key: "route.search" },
  { pattern: "/search", key: "route.search" },
  { pattern: "/documento/:id", key: "route.document" },
  { pattern: "/document/:id", key: "route.document" },
  { pattern: "/doc/:id", key: "route.document" },
  { pattern: "/analytics", key: "route.analytics" },
  { pattern: "/chat", key: "route.chat" },
  { pattern: "/perfil", key: "route.profile" },
  { pattern: "/configuracoes", key: "route.settings" },
  { pattern: "/favoritos", key: "route.favorites" },
  { pattern: "/admin/users", key: "route.adminUsers" },
  { pattern: "/admin/upload", key: "route.adminUpload" },
  { pattern: "/admin/jobs", key: "route.adminJobs" },
  { pattern: "/login", key: "route.login" },
];

export function RouteMetadata() {
  const location = useLocation();
  const { t } = useI18n();

  const pageLabel = useMemo(() => {
    const exactMatch = ROUTE_LABELS.find(({ pattern }) => matchPath({ path: pattern, end: true }, location.pathname));
    return exactMatch ? t(exactMatch.key) : t("route.fallback");
  }, [location.pathname, t]);

  useEffect(() => {
    document.title = buildPageTitle(pageLabel);
  }, [pageLabel]);

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {pageLabel}
    </div>
  );
}
