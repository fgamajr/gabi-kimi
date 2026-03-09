import { useMemo, useState } from "react";
import { FileText, Filter } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { usePipelineLogs, usePipelineRuns } from "@/hooks/usePipeline";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import WorkerUnavailableState from "./WorkerUnavailableState";

const LEVELS = ["ALL", "INFO", "WARNING", "ERROR"] as const;

function levelClass(level: string): string {
  switch (level) {
    case "ERROR":
      return "bg-red-500/10 text-red-300";
    case "WARNING":
      return "bg-amber-500/10 text-amber-300";
    default:
      return "bg-muted text-text-secondary";
  }
}

function formatLogTime(dateStr: string): string {
  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(dateStr));
}

export default function PipelineLogs() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: runs, isError: runsError, error: runsFailure } = usePipelineRuns(25);

  const [level, setLevel] = useState(searchParams.get("level") ?? "ALL");
  const [runId, setRunId] = useState(searchParams.get("run") ?? "ALL");
  const [fileId, setFileId] = useState(searchParams.get("file") ?? "");

  const queryParams = useMemo(
    () => ({
      run_id: runId !== "ALL" ? runId : undefined,
      file_id: fileId ? Number(fileId) : undefined,
      level: level !== "ALL" ? level : undefined,
      limit: 200,
    }),
    [fileId, level, runId]
  );

  const { data: logs, isLoading, isError: logsError, error: logsFailure } = usePipelineLogs(queryParams);

  const syncSearchParams = (next: { level?: string; run?: string; file?: string }) => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", "logs");
    if (next.level) params.set("level", next.level);
    if (next.run) params.set("run", next.run);
    if (next.file !== undefined) {
      if (next.file) params.set("file", next.file);
      else params.delete("file");
    }
    setSearchParams(params, { replace: true });
  };

  if (runsError || logsError) {
    const message = [runsFailure, logsFailure].find(Boolean);
    return (
      <WorkerUnavailableState
        title="Logs indisponíveis"
        message={(message as Error | undefined)?.message}
      />
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Filtros</h2>
            <p className="text-xs text-text-secondary">Refine por nível, execução ou arquivo específico.</p>
          </div>
          <Filter className="h-4 w-4 text-primary" />
        </div>
        <div className="grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_160px_auto]">
          <Select
            value={level}
            onValueChange={(value) => {
              setLevel(value);
              syncSearchParams({ level: value });
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="Level" />
            </SelectTrigger>
            <SelectContent>
              {LEVELS.map((item) => (
                <SelectItem key={item} value={item}>{item}</SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select
            value={runId}
            onValueChange={(value) => {
              setRunId(value);
              syncSearchParams({ run: value });
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder="Run" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Todos os runs</SelectItem>
              {runs?.map((run) => (
                <SelectItem key={run.id} value={run.id}>
                  {run.phase} · {run.id.slice(0, 8)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Input
            inputMode="numeric"
            placeholder="file_id"
            value={fileId}
            onChange={(event) => setFileId(event.target.value)}
            onBlur={() => syncSearchParams({ file: fileId })}
          />

          <Button
            type="button"
            variant="outline"
            onClick={() => {
              setLevel("ALL");
              setRunId("ALL");
              setFileId("");
              setSearchParams({ tab: "logs" }, { replace: true });
            }}
          >
            Limpar
          </Button>
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface-elevated p-0 shadow-sm">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Event stream</h2>
            <p className="text-xs text-text-secondary">Últimos 200 eventos estruturados do pipeline.</p>
          </div>
          <FileText className="h-4 w-4 text-primary" />
        </div>
        <ScrollArea className="h-[540px]">
          <div className="divide-y divide-border/70">
            {isLoading ? (
              <div className="p-5 text-sm text-text-tertiary">Carregando logs...</div>
            ) : logs?.length ? logs.map((log) => (
              <div key={log.id} className="space-y-2 px-5 py-4 font-mono text-xs">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-text-tertiary">{formatLogTime(log.created_at)}</span>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${levelClass(log.level)}`}>
                    {log.level}
                  </span>
                  {log.run_id ? <span className="rounded-full bg-muted px-2 py-0.5 text-text-secondary">run {log.run_id.slice(0, 8)}</span> : null}
                  {log.file_id ? <span className="rounded-full bg-muted px-2 py-0.5 text-text-secondary">file {log.file_id}</span> : null}
                </div>
                <p className="whitespace-pre-wrap break-words text-text-primary">{log.message}</p>
              </div>
            )) : (
              <div className="p-5 text-sm text-text-tertiary">
                {!runs?.length
                  ? "Nenhum evento ainda. O registry foi carregado, mas o pipeline ainda não executou fases."
                  : "Nenhum log corresponde aos filtros atuais."}
              </div>
            )}
          </div>
        </ScrollArea>
      </section>
    </div>
  );
}
