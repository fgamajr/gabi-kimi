import { useState } from "react";
import * as Collapsible from "@radix-ui/react-collapsible";
import { ChevronDown, RotateCcw } from "lucide-react";
import type { MonthData, FileStatus } from "@/types/pipeline";
import { useRetryFile } from "@/hooks/usePipeline";
import { toast } from "sonner";
import FileStatusBadge from "./FileStatusBadge";
import { cn } from "@/lib/utils";

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

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === undefined) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function MonthCard({ month, files }: MonthCardProps) {
  const [open, setOpen] = useState(false);
  const retryMut = useRetryFile();
  const agg = aggregateStatus(files);

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
          <div className="flex items-center gap-3">
            <span className={cn("h-2.5 w-2.5 rounded-full", AGG_COLORS[agg])} />
            <span className="font-medium text-text-primary capitalize">
              {formatMonthLabel(month)}
            </span>
            <span className="text-xs text-text-tertiary">{files.length} files</span>
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
          {files.map((file, idx) => {
            const sectionCls = SECTION_CLASSES[file.section] ?? "section-badge-e";
            return (
              <div key={`${file.year_month}-${file.section}-${idx}`} className="px-4 py-3">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-md px-1.5 py-0.5 text-[10px] font-semibold uppercase",
                        sectionCls
                      )}
                    >
                      {file.section}
                    </span>
                    <span className="text-sm text-text-primary truncate">
                      {file.year_month}_{file.section}
                    </span>
                    <FileStatusBadge status={file.status} />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-text-tertiary shrink-0">
                    {file.doc_count !== null && (
                      <span>{file.doc_count} docs</span>
                    )}
                    {isFailed(file.status) && (
                      <button
                        onClick={() => handleRetry(idx)}
                        disabled={retryMut.isPending}
                        className="inline-flex items-center gap-1 text-xs text-red-400 hover:text-red-300 transition-colors disabled:opacity-50"
                      >
                        <RotateCcw className="w-3 h-3" />
                        Retry
                      </button>
                    )}
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
