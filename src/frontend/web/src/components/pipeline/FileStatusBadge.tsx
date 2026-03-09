import type { FileStatus } from "@/types/pipeline";
import { cn } from "@/lib/utils";

const STATUS_CONFIG: Record<FileStatus, { color: string; dotClass: string; pulse?: boolean }> = {
  DISCOVERED: { color: "text-gray-400", dotClass: "bg-gray-400" },
  QUEUED: { color: "text-blue-400", dotClass: "bg-blue-400" },
  DOWNLOADING: { color: "text-yellow-400", dotClass: "bg-yellow-400", pulse: true },
  DOWNLOADED: { color: "text-cyan-400", dotClass: "bg-cyan-400" },
  EXTRACTING: { color: "text-yellow-400", dotClass: "bg-yellow-400", pulse: true },
  EXTRACTED: { color: "text-cyan-400", dotClass: "bg-cyan-400" },
  INGESTING: { color: "text-yellow-400", dotClass: "bg-yellow-400", pulse: true },
  INGESTED: { color: "text-indigo-400", dotClass: "bg-indigo-400" },
  VERIFIED: { color: "text-emerald-400", dotClass: "bg-emerald-400" },
  DOWNLOAD_FAILED: { color: "text-red-400", dotClass: "bg-red-400" },
  EXTRACT_FAILED: { color: "text-red-400", dotClass: "bg-red-400" },
  INGEST_FAILED: { color: "text-red-400", dotClass: "bg-red-400" },
  VERIFY_FAILED: { color: "text-red-400", dotClass: "bg-red-400" },
};

interface FileStatusBadgeProps {
  status: FileStatus;
  className?: string;
}

export default function FileStatusBadge({ status, className }: FileStatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? { color: "text-gray-400", dotClass: "bg-gray-400" };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium bg-muted/60",
        config.color,
        className
      )}
    >
      <span
        className={cn("h-1.5 w-1.5 rounded-full", config.dotClass, config.pulse && "animate-pulse")}
      />
      {status.replace(/_/g, " ")}
    </span>
  );
}
