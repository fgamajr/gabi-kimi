import { usePipelineMonths, usePipelineRuns, usePipelineStats, usePipelineStatus, useTriggerPipeline } from "@/hooks/usePipeline";
import type { FileStatus, RegistryStatus } from "@/types/pipeline";
import { toast } from "sonner";
import { AlertTriangle, CheckCircle2, Clock, Files, Rocket } from "lucide-react";
import CoverageChart from "./CoverageChart";
import WorkerUnavailableState from "./WorkerUnavailableState";

const PENDING_STATES: FileStatus[] = [
  "DISCOVERED",
  "QUEUED",
  "DOWNLOADING",
  "DOWNLOADED",
  "EXTRACTING",
  "EXTRACTED",
  "BM25_INDEXING",
  "BM25_INDEXED",
  "EMBEDDING",
  "EMBEDDED",
  "VERIFYING",
];

const FAILED_STATES: FileStatus[] = [
  "DOWNLOAD_FAILED",
  "EXTRACT_FAILED",
  "BM25_INDEX_FAILED",
  "EMBEDDING_FAILED",
  "VERIFY_FAILED",
];

function sumStatuses(status: RegistryStatus | undefined, keys: FileStatus[]): number {
  if (!status) return 0;
  return keys.reduce((acc, key) => acc + (status[key] ?? 0), 0);
}

function totalFiles(status: RegistryStatus | undefined): number {
  if (!status) return 0;
  return Object.values(status).reduce((acc, value) => acc + value, 0);
}

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "agora";
  if (mins < 60) return `${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

export default function PipelineOverview() {
  const { data: status, isLoading: statusLoading, isError: statusError, error: statusFailure } = usePipelineStatus();
  const { data: stats, isError: statsError, error: statsFailure } = usePipelineStats();
  const { data: months, isLoading: monthsLoading, isError: monthsError, error: monthsFailure } = usePipelineMonths();
  const { data: runs, isError: runsError, error: runsFailure } = usePipelineRuns(5);
  const triggerMut = useTriggerPipeline();

  const total = totalFiles(status);
  const verified = status?.VERIFIED ?? 0;
  const pending = sumStatuses(status, PENDING_STATES);
  const failed = sumStatuses(status, FAILED_STATES);
  const verifiedPct = total > 0 ? Math.round((verified / total) * 100) : 0;
  const isBootstrappedAwaitingFirstRun = total > 0 && !stats?.latest_run;

  const handleTrigger = (phase: string) => {
    triggerMut.mutate(phase, {
      onSuccess: () => toast.success(`Pipeline "${phase}" acionado.`),
      onError: (err) => toast.error(`Falha ao acionar: ${(err as Error).message}`),
    });
  };

  if (statusLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl bg-surface-elevated" />
        ))}
      </div>
    );
  }

  if (statusError || statsError || monthsError || runsError) {
    const message = [
      statusFailure,
      statsFailure,
      monthsFailure,
      runsFailure,
    ].find(Boolean);
    return (
      <WorkerUnavailableState
        title="Observabilidade indisponível"
        message={(message as Error | undefined)?.message}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <MetricCard icon={<Files className="h-4 w-4 text-blue-400" />} label="Arquivos" value={total.toLocaleString()} />
        <MetricCard
          icon={<CheckCircle2 className="h-4 w-4 text-emerald-400" />}
          label="Verificados"
          value={verified.toLocaleString()}
          sub={`${verifiedPct}%`}
        />
        <MetricCard icon={<Clock className="h-4 w-4 text-yellow-400" />} label="Na fila" value={pending.toLocaleString()} />
        <MetricCard icon={<AlertTriangle className="h-4 w-4 text-red-400" />} label="Falhas" value={failed.toLocaleString()} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <InfoCard
          label="Documentos indexados"
          value={(stats?.total_docs ?? 0).toLocaleString()}
          helper={stats?.last_verified_at ? `Última verificação há ${formatRelativeTime(stats.last_verified_at)}` : "Sem verificações ainda"}
        />
        <InfoCard
          label="Backlog de retry"
          value={String(stats?.retry_backlog ?? 0)}
          helper={`Maior contador de retry: ${stats?.max_retry_count ?? 0}`}
        />
        <InfoCard
          label="Última execução"
          value={stats?.latest_run?.phase ?? (isBootstrappedAwaitingFirstRun ? "bootstrap pronto" : "nenhuma")}
          helper={
            stats?.latest_run
              ? `${stats.latest_run.status} · ${formatRelativeTime(stats.latest_run.started_at)}`
              : isBootstrappedAwaitingFirstRun
                ? "Catálogo carregado no registry; aguardando o primeiro ciclo do pipeline."
                : "Sem runs registrados"
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-elevated p-4">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Atividade recente</h3>
          {runs && runs.length > 0 ? (
            <ul className="space-y-2">
              {runs.map((run) => (
                <li
                  key={run.id}
                  className="flex items-center justify-between border-b border-border/50 py-1.5 text-sm last:border-0"
                >
                  <div className="min-w-0">
                    <span className="truncate font-medium text-text-primary">{run.phase}</span>
                    <span className="ml-2 text-xs text-text-tertiary">{run.status}</span>
                  </div>
                  <span className="shrink-0 text-xs text-text-tertiary">{formatRelativeTime(run.started_at)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-text-tertiary">
              {isBootstrappedAwaitingFirstRun
                ? "Catálogo carregado, mas nenhuma fase do pipeline executou ainda."
                : "Nenhuma execução recente."}
            </p>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface-elevated p-4">
          <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Cobertura por ano</h3>
          {monthsLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-6 animate-pulse rounded bg-muted" />
              ))}
            </div>
          ) : months ? (
            <CoverageChart months={months} />
          ) : (
            <p className="text-sm text-text-tertiary">Sem dados.</p>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-border bg-surface-elevated p-4">
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Ações rápidas</h3>
        <div className="flex flex-wrap gap-2">
          <QuickAction label="Discovery" onClick={() => handleTrigger("discovery")} disabled={triggerMut.isPending} />
          <QuickAction label="Download" onClick={() => handleTrigger("download")} disabled={triggerMut.isPending} />
          <QuickAction label="BM25" onClick={() => handleTrigger("bm25")} disabled={triggerMut.isPending} />
          <QuickAction label="Embedding" onClick={() => handleTrigger("embed")} disabled={triggerMut.isPending} />
          <QuickAction label="Pipeline completo" onClick={() => handleTrigger("full")} disabled={triggerMut.isPending} primary />
        </div>
      </div>
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated p-4">
      <div className="mb-2 flex items-center gap-2">
        {icon}
        <span className="text-xs font-medium text-text-tertiary">{label}</span>
      </div>
      <div className="flex items-end gap-1.5">
        <span className="text-2xl font-bold text-foreground">{value}</span>
        {sub ? <span className="mb-0.5 text-xs text-text-secondary">{sub}</span> : null}
      </div>
    </div>
  );
}

function InfoCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface-elevated p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-text-tertiary">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-foreground">{value}</p>
      <p className="mt-1 text-xs text-text-secondary">{helper}</p>
    </div>
  );
}

function QuickAction({
  label,
  onClick,
  disabled,
  primary = false,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
  primary?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={[
        "inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        primary
          ? "border border-primary/40 text-primary hover:bg-primary/10"
          : "border border-border text-text-secondary hover:bg-muted hover:text-text-primary",
      ].join(" ")}
    >
      <Rocket className="h-3.5 w-3.5" />
      {label}
    </button>
  );
}
