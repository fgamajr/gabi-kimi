import { useMemo, useState } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import { ChevronDown, FileText, RotateCcw } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { MonthData, FileStatus } from "@/types/pipeline";
import { useRetryFile } from "@/hooks/usePipeline";
import { toast } from "sonner";
import FileStatusBadge from "./FileStatusBadge";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface MonthCardProps {
  month: string;
  files: MonthData[];
}

const SECTION_CLASSES: Record<string, string> = {
  do1: "section-badge-1",
  do2: "section-badge-2",
  do3: "section-badge-3",
  se: "section-badge-e",
};

function formatMonthLabel(yearMonth: string): string {
  const [year, month] = yearMonth.split("-").map(Number);
  const date = new Date(year, month - 1);
  return new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(date);
}

function aggregateStatus(files: MonthData[]): "green" | "red" | "yellow" {
  const allVerified = files.every((f) => f.status === "VERIFIED");
  if (allVerified) return "green";
  const anyFailed = files.some((f) => f.status.endsWith("_FAILED"));
  if (anyFailed) return "red";
  return "yellow";
}

const AGG_COLORS = {
  green: "bg-emerald-400",
  red: "bg-red-400",
  yellow: "bg-yellow-400",
};

function isFailed(status: FileStatus): boolean {
  return status.endsWith("_FAILED");
}

function formatSectionLabel(section: string): string {
  return section.toUpperCase();
}

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimestamp(value: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

function formatDuration(file: MonthData): string {
  const start = file.queued_at ?? file.discovered_at;
  const end = file.verified_at
    ?? file.embedded_at
    ?? file.bm25_indexed_at
    ?? file.ingested_at
    ?? file.extracted_at
    ?? file.downloaded_at
    ?? file.updated_at;
  if (!start || !end) return "-";
  const diffMs = new Date(end).getTime() - new Date(start).getTime();
  if (!Number.isFinite(diffMs) || diffMs <= 0) return "-";
  const totalMinutes = Math.round(diffMs / 60000);
  if (totalMinutes < 1) return "<1m";
  if (totalMinutes < 60) return `${totalMinutes}m`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
}

export default function MonthCard({ month, files }: MonthCardProps) {
  const [open, setOpen] = useState(false);
  const retryMut = useRetryFile();
  const navigate = useNavigate();
  const agg = aggregateStatus(files);
  const totals = useMemo(() => ({
    verified: files.filter((file) => file.status === "VERIFIED").length,
    failed: files.filter((file) => isFailed(file.status)).length,
  }), [files]);

  const handleRetry = (fileId: number) => {
    retryMut.mutate(fileId, {
      onSuccess: () => toast.success("Retry queued."),
      onError: (err) => toast.error(`Retry failed: ${(err as Error).message}`),
    });
  };

  return (
    <Collapsible.Root open={open} onOpenChange={setOpen}>
      <Collapsible.Trigger asChild>
        <button className="w-full flex items-center justify-between rounded-xl bg-surface-elevated border border-border p-4 hover:ring-1 hover:ring-primary/20 transition-all text-left group">
          <div className="flex min-w-0 items-center gap-3">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", AGG_COLORS[agg])} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="font-medium text-text-primary capitalize">
                  {formatMonthLabel(month)}
                </span>
                <span className="text-xs text-text-tertiary">{files.length} arquivos</span>
              </div>
              <p className="text-xs text-text-tertiary">
                {totals.verified} verificados
                {totals.failed > 0 ? ` · ${totals.failed} falhas` : ""}
              </p>
            </div>
          </div>
          <ChevronDown
            className={cn(
              "w-4 h-4 text-text-tertiary transition-transform duration-200",
              open && "rotate-180"
            )}
          />
        </button>
      </Collapsible.Trigger>

      <Collapsible.Content className="overflow-hidden data-[state=open]:animate-fade-in">
        <div className="mt-1 rounded-xl bg-surface-elevated border border-border divide-y divide-border/50">
          {files.map((file) => {
            const sectionCls = SECTION_CLASSES[file.section] ?? "section-badge-e";
            return (
              <div key={file.id} className="px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 space-y-2">
                    <div className="flex items-center gap-2 min-w-0 flex-wrap">
                      <span
                        className={cn(
                          "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                          sectionCls
                        )}
                      >
                        {formatSectionLabel(file.section)}
                      </span>
                      <span className="truncate text-sm font-medium text-text-primary">
                        {file.filename}
                      </span>
                      <FileStatusBadge status={file.status} />
                    </div>
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-tertiary">
                      <span>{file.doc_count ?? 0} docs</span>
                      <span>{formatFileSize(file.file_size_bytes)}</span>
                      <span>retries: {file.retry_count}</span>
                      <span>duração: {formatDuration(file)}</span>
                      <span>última atividade: {formatTimestamp(file.updated_at)}</span>
                    </div>
                    {file.error_message ? (
                      <p className="text-xs text-red-400">{file.error_message}</p>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {isFailed(file.status) ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => handleRetry(file.id)}
                        disabled={retryMut.isPending}
                        className="border-red-400/30 text-red-300 hover:bg-red-500/10 hover:text-red-200"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Retry
                      </Button>
                    ) : null}
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => navigate(`/pipeline?tab=logs&file=${file.id}`)}
                      className="h-8 px-2 text-xs text-text-secondary"
                    >
                      <FileText className="mr-1 h-3.5 w-3.5" />
                      Logs
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  );
}
