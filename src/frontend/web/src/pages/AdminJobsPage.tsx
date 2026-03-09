import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { DatabaseZap, FileUp, Loader2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import {
  getAdminJobsList,
  getAdminJobDetail,
  getAdminJobStreamUrl,
  retryAdminJob,
  type AdminJobListItem,
  type AdminJobDetail,
} from "@/lib/api";
import { useAdminAnalyticsStatus, useRefreshAdminAnalyticsCache } from "@/hooks/useAdmin";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return format(d, "dd/MM/yyyy HH:mm", { locale: ptBR });
}

function formatRelativeAge(value: string | null | undefined, nowMs: number): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const diffMs = nowMs - d.getTime();
  if (diffMs <= 0) return "agora";
  const totalMinutes = Math.floor(diffMs / 60000);
  if (totalMinutes < 1) return "agora";
  if (totalMinutes < 60) return `há ${totalMinutes} min`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours < 24) return minutes > 0 ? `há ${hours}h ${minutes}min` : `há ${hours}h`;
  const days = Math.floor(hours / 24);
  const remHours = hours % 24;
  return remHours > 0 ? `há ${days}d ${remHours}h` : `há ${days}d`;
}

function articleCount(job: AdminJobListItem): number | null {
  const n = job.articles_found ?? null;
  if (n != null) return n;
  const a = job.articles_ingested ?? 0;
  const b = job.articles_dup ?? 0;
  const c = job.articles_failed ?? 0;
  if (a + b + c > 0) return a + b + c;
  return null;
}

function statusVariant(status: string): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "completed":
      return "default";
    case "partial":
      return "secondary";
    case "failed":
      return "destructive";
    case "processing":
    case "queued":
      return "outline";
    default:
      return "outline";
  }
}

function analyticsStatusVariant(
  status: string | null | undefined,
  isStale: boolean | undefined
): "default" | "secondary" | "destructive" | "outline" {
  if (status === "failed") return "destructive";
  if (isStale) return "secondary";
  if (status === "ok") return "default";
  return "outline";
}

const TERMINAL_STATUSES = ["completed", "failed", "partial"];

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<AdminJobListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<AdminJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [relativeNowMs, setRelativeNowMs] = useState(() => Date.now());
  const analyticsStatus = useAdminAnalyticsStatus();
  const refreshAnalytics = useRefreshAdminAnalyticsCache();

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRelativeNowMs(Date.now());
    }, 60_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAdminJobsList(50, 0)
      .then((items) => {
        if (!cancelled) setJobs(items);
      })
      .catch(() => {
        if (!cancelled) setJobs([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const openDetail = (job: AdminJobListItem) => {
    setDetail(null);
    setDetailLoading(true);
    getAdminJobDetail(job.id)
      .then((d) => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  };

  // SSE stream when detail is open and job is queued or processing (JOBS-05)
  const streamRef = useRef<EventSource | null>(null);
  useEffect(() => {
    if (!detail?.id || TERMINAL_STATUSES.includes(detail.status)) return;
    const url = getAdminJobStreamUrl(detail.id);
    const es = new EventSource(url);
    streamRef.current = es;
    es.addEventListener("job", (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data) as AdminJobDetail;
        setDetail(data);
        if (TERMINAL_STATUSES.includes(data.status)) {
          es.close();
          streamRef.current = null;
        }
      } catch {
        // ignore parse errors
      }
    });
    es.addEventListener("error", () => {
      es.close();
      streamRef.current = null;
    });
    return () => {
      es.close();
      streamRef.current = null;
    };
  }, [detail?.id, detail?.status]);

  const handleRetry = () => {
    if (!detail || retrying) return;
    setRetrying(true);
    retryAdminJob(detail.id)
      .then((d) => {
        setDetail(d);
        setJobs((prev) => prev.map((j) => (j.id === d.id ? { ...j, ...d } : j)));
      })
      .catch(() => {})
      .finally(() => setRetrying(false));
  };

  const handleRefreshAnalytics = () => {
    if (refreshAnalytics.isPending) return;
    refreshAnalytics.mutate(undefined, {
      onSuccess: (result) => {
        toast.success(`Cache analytics atualizado em ${result.duration_ms} ms`);
      },
      onError: (error) => {
        toast.error(error instanceof Error ? error.message : "Falha ao atualizar analytics");
      },
    });
  };

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto max-w-5xl px-4 py-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Jobs de upload</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Histórico de envios (somente leitura, audit log).
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              className="w-fit"
              onClick={handleRefreshAnalytics}
              disabled={refreshAnalytics.isPending}
            >
              {refreshAnalytics.isPending ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Atualizando analytics…
                </>
              ) : (
                <>
                  <DatabaseZap className="w-4 h-4 mr-2" /> Atualizar analytics
                </>
              )}
            </Button>
            <Button asChild variant="outline" className="w-fit">
              <Link to="/admin/upload" className="inline-flex items-center gap-2">
                <FileUp className="w-4 h-4" /> Novo upload
              </Link>
            </Button>
          </div>
        </div>

        <div className="mb-6 rounded-lg border border-border bg-card p-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-medium text-foreground">Cache de analytics</p>
              <p className="text-xs text-muted-foreground mt-1">
                Último refresh:{" "}
                {analyticsStatus.data?.last_refreshed_at
                  ? formatDateTime(analyticsStatus.data.last_refreshed_at)
                  : "nunca"}
                {analyticsStatus.data?.last_refreshed_at
                  ? ` (${formatRelativeAge(analyticsStatus.data.last_refreshed_at, relativeNowMs)})`
                  : ""}
                {" · "}
                origem: {analyticsStatus.data?.last_refresh_source ?? "—"}
                {" · "}
                duração: {analyticsStatus.data?.last_duration_ms != null ? `${analyticsStatus.data.last_duration_ms} ms` : "—"}
              </p>
              {analyticsStatus.data?.is_stale ? (
                <p className="text-xs text-amber-600 mt-1">
                  Cache stale: último refresh excedeu {analyticsStatus.data.stale_after_hours}h.
                </p>
              ) : null}
              {analyticsStatus.data?.last_error ? (
                <p className="text-xs text-destructive mt-1 break-words">
                  Último erro: {analyticsStatus.data.last_error}
                </p>
              ) : null}
            </div>
            <Badge variant={analyticsStatusVariant(analyticsStatus.data?.last_status, analyticsStatus.data?.is_stale)}>
              {analyticsStatus.isLoading
                ? "carregando"
                : analyticsStatus.data?.last_status === "ok" && analyticsStatus.data?.is_stale
                  ? "stale"
                  : analyticsStatus.data?.last_status ?? "unknown"}
            </Badge>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="w-8 h-8 animate-spin" />
          </div>
        ) : (
          <div className="rounded-lg border border-border overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Arquivo</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Enviado em</TableHead>
                  <TableHead>Concluído em</TableHead>
                  <TableHead className="text-right">Artigos</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {jobs.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground py-8">
                      Nenhum job encontrado.
                    </TableCell>
                  </TableRow>
                ) : (
                  jobs.map((job) => (
                    <TableRow
                      key={job.id}
                      className="cursor-pointer"
                      onClick={() => openDetail(job)}
                    >
                      <TableCell className="font-medium">{job.filename}</TableCell>
                      <TableCell>
                        <Badge variant={statusVariant(job.status)}>
                          {job.status === "queued" && "Na fila"}
                          {job.status === "processing" && "Processando"}
                          {job.status === "completed" && "Concluído"}
                          {job.status === "partial" && "Parcial"}
                          {job.status === "failed" && "Falhou"}
                          {!["queued", "processing", "completed", "partial", "failed"].includes(job.status) && job.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(job.created_at)}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(job.completed_at)}
                      </TableCell>
                      <TableCell className="text-right">
                        {articleCount(job) != null ? String(articleCount(job)) : "—"}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <Dialog open={!!detail || detailLoading} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Detalhe do job</DialogTitle>
          </DialogHeader>
          {detailLoading && !detail ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : detail ? (
            <div className="space-y-4 text-sm">
              <div className="grid gap-2">
                <p><span className="text-muted-foreground">Arquivo:</span> {detail.filename}</p>
                <p>
                  <span className="text-muted-foreground">Status:</span>{" "}
                  <Badge variant={statusVariant(detail.status)}>{detail.status}</Badge>
                </p>
                <p><span className="text-muted-foreground">Enviado em:</span> {formatDateTime(detail.created_at)}</p>
                <p><span className="text-muted-foreground">Concluído em:</span> {formatDateTime(detail.completed_at)}</p>
                {detail.uploaded_by && (
                  <p><span className="text-muted-foreground">Enviado por:</span> {detail.uploaded_by}</p>
                )}
              </div>
              <div className="rounded-lg border border-border p-3 space-y-1 bg-muted/30">
                <p className="font-medium text-foreground">Resumo por artigo</p>
                <p><span className="text-muted-foreground">Total detectado:</span> {detail.articles_found ?? "—"}</p>
                <p><span className="text-muted-foreground">Ingeridos:</span> {detail.articles_ingested ?? "—"}</p>
                <p><span className="text-muted-foreground">Duplicados (ignorados):</span> {detail.articles_dup ?? "—"}</p>
                <p><span className="text-muted-foreground">Falhas:</span> {detail.articles_failed ?? "—"}</p>
              </div>
              {detail.error_message && (
                <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                  <p className="font-medium text-foreground mb-1">Mensagens de erro</p>
                  <p className="text-muted-foreground whitespace-pre-wrap break-words">{detail.error_message}</p>
                </div>
              )}
              {(detail.status === "failed" || detail.status === "partial") && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleRetry}
                  disabled={retrying}
                  className="w-full sm:w-auto"
                >
                  {retrying ? (
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                  ) : (
                    <RotateCcw className="w-4 h-4 mr-2" />
                  )}
                  Tentar novamente
                </Button>
              )}
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
