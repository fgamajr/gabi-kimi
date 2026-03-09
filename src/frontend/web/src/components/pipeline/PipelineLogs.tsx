import { useState, useRef, useEffect } from "react";
import { usePipelineLogs, usePipelineRuns } from "@/hooks/usePipeline";
import type { LogEntry } from "@/types/pipeline";
import { cn } from "@/lib/utils";
import { ArrowDown, Filter } from "lucide-react";

const LEVELS = ["ALL", "INFO", "WARNING", "ERROR"] as const;
type LevelFilter = (typeof LEVELS)[number];

function formatTimestamp(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function LevelBadge({ level }: { level: string }) {
  return (
    <span
      className={cn(
        "inline-block min-w-[56px] text-center text-[10px] font-semibold px-1.5 py-0.5 rounded",
        level === "INFO" && "bg-zinc-500/15 text-zinc-400",
        level === "WARNING" && "bg-yellow-500/15 text-yellow-400",
        level === "ERROR" && "bg-red-500/15 text-red-400",
        level !== "INFO" &&
          level !== "WARNING" &&
          level !== "ERROR" &&
          "bg-zinc-500/15 text-zinc-400"
      )}
    >
      {level}
    </span>
  );
}

export default function PipelineLogs() {
  const [levelFilter, setLevelFilter] = useState<LevelFilter>("ALL");
  const [runFilter, setRunFilter] = useState<string>("");
  const [fileFilter, setFileFilter] = useState<string>("");
  const [autoScroll, setAutoScroll] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: runs } = usePipelineRuns(20);

  const params: Parameters<typeof usePipelineLogs>[0] = {
    limit: 200,
    ...(levelFilter !== "ALL" && { level: levelFilter }),
    ...(runFilter && { run_id: runFilter }),
    ...(fileFilter && { file_id: parseInt(fileFilter, 10) || undefined }),
  };

  const { data: logs, isLoading } = usePipelineLogs(params);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-3.5 h-3.5 text-text-tertiary" />
          <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
            Filters
          </h3>
        </div>
        <div className="flex flex-wrap gap-3 items-end">
          {/* Level filter */}
          <div className="space-y-1">
            <label className="text-[10px] text-text-tertiary uppercase font-medium">
              Level
            </label>
            <div className="flex gap-0.5 rounded-lg border border-border p-0.5">
              {LEVELS.map((level) => (
                <button
                  key={level}
                  onClick={() => setLevelFilter(level)}
                  className={cn(
                    "px-2.5 py-1 text-xs font-medium rounded-md transition-colors",
                    levelFilter === level
                      ? "bg-primary/15 text-primary"
                      : "text-text-tertiary hover:text-text-secondary"
                  )}
                >
                  {level}
                </button>
              ))}
            </div>
          </div>

          {/* Run filter */}
          <div className="space-y-1">
            <label className="text-[10px] text-text-tertiary uppercase font-medium">
              Run
            </label>
            <select
              value={runFilter}
              onChange={(e) => setRunFilter(e.target.value)}
              className="block rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-text-primary focus:outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">All runs</option>
              {runs?.map((run) => (
                <option key={run.id} value={run.id}>
                  {run.phase} - {run.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>

          {/* File ID filter */}
          <div className="space-y-1">
            <label className="text-[10px] text-text-tertiary uppercase font-medium">
              File ID
            </label>
            <input
              type="text"
              value={fileFilter}
              onChange={(e) => setFileFilter(e.target.value)}
              placeholder="e.g. 42"
              className="block w-24 rounded-lg border border-border bg-background px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Auto-scroll toggle */}
          <button
            onClick={() => setAutoScroll((v) => !v)}
            className={cn(
              "inline-flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors",
              autoScroll
                ? "border-primary/40 text-primary bg-primary/10"
                : "border-border text-text-tertiary hover:text-text-secondary"
            )}
          >
            <ArrowDown className="w-3 h-3" />
            Auto-scroll
          </button>
        </div>
      </div>

      {/* Log stream */}
      <div className="rounded-xl border border-border bg-surface-elevated">
        <div
          ref={scrollRef}
          className="max-h-[600px] overflow-y-auto p-2"
        >
          {isLoading ? (
            <div className="space-y-1 p-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="h-5 rounded bg-muted animate-pulse"
                />
              ))}
            </div>
          ) : logs && logs.length > 0 ? (
            <div className="space-y-px">
              {logs.map((entry: LogEntry) => (
                <div
                  key={entry.id}
                  className={cn(
                    "flex items-start gap-2 px-2 py-1 rounded text-xs hover:bg-muted/50 transition-colors",
                    entry.level === "ERROR" && "bg-red-500/5"
                  )}
                >
                  <span className="text-text-tertiary font-mono shrink-0 pt-px">
                    {formatTimestamp(entry.created_at)}
                  </span>
                  <LevelBadge level={entry.level} />
                  <span className="text-text-primary font-mono break-all leading-relaxed">
                    {entry.message}
                  </span>
                  {entry.file_id && (
                    <span className="shrink-0 text-primary/70 font-mono text-[10px] pt-px">
                      file:{entry.file_id}
                    </span>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="flex items-center justify-center py-12">
              <p className="text-sm text-text-tertiary">
                No logs matching filters
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
