import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { FileUp, Loader2 } from "lucide-react";
import {
  getAdminJobsList,
  getAdminJobDetail,
  type AdminJobListItem,
  type AdminJobDetail,
} from "@/lib/api";
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

export default function AdminJobsPage() {
  const [jobs, setJobs] = useState<AdminJobListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<AdminJobDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

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
          <Button asChild variant="outline" className="w-fit">
            <Link to="/admin/upload" className="inline-flex items-center gap-2">
              <FileUp className="w-4 h-4" /> Novo upload
            </Link>
          </Button>
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
            </div>
          ) : null}
        </DialogContent>
      </Dialog>
    </div>
  );
}
