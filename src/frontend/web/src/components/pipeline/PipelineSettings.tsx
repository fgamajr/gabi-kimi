import { AlertTriangle, HardDrive, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { usePausePipeline, useResumePipeline, useWorkerHealth } from "@/hooks/usePipeline";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import WorkerUnavailableState from "./WorkerUnavailableState";

const SCHEDULE_ROWS = [
  { id: "discovery", label: "Discovery", schedule: "23:00 UTC" },
  { id: "download", label: "Download", schedule: "23:30 UTC" },
  { id: "extract", label: "Extract", schedule: "23:45 UTC" },
  { id: "bm25", label: "BM25 index", schedule: "00:00 UTC" },
  { id: "embed", label: "Embedding", schedule: "00:30 UTC" },
  { id: "verify", label: "Verify", schedule: "01:00 UTC" },
  { id: "retry", label: "Retry", schedule: "06:00 UTC" },
  { id: "heartbeat", label: "Heartbeat", schedule: "a cada 60s" },
];

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function PipelineSettings() {
  const { data: health, isError, error } = useWorkerHealth();
  const pauseMut = usePausePipeline();
  const resumeMut = useResumePipeline();

  const dbSize = health?.disk_usage.db_size_bytes ?? 0;

  if (isError) {
    return (
      <WorkerUnavailableState
        title="Settings indisponível"
        message={(error as Error | undefined)?.message}
      />
    );
  }

  const handlePause = async () => {
    if (!window.confirm("Pausar o scheduler do pipeline?")) return;
    try {
      await pauseMut.mutateAsync();
      toast.success("Scheduler pausado.");
    } catch (error) {
      toast.error(`Falha ao pausar: ${(error as Error).message}`);
    }
  };

  const handleResume = async () => {
    try {
      await resumeMut.mutateAsync();
      toast.success("Scheduler retomado.");
    } catch (error) {
      toast.error(`Falha ao retomar: ${(error as Error).message}`);
    }
  };

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Schedule</h2>
            <p className="text-xs text-text-secondary">Configuração atual embutida no worker. Alteração exige deploy.</p>
          </div>
          <ShieldAlert className="h-4 w-4 text-primary" />
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {SCHEDULE_ROWS.map((row) => (
            <div key={row.id} className="rounded-xl bg-background/40 px-4 py-3">
              <p className="text-sm font-medium capitalize text-text-primary">{row.label}</p>
              <p className="text-xs text-text-secondary">{row.schedule}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface-elevated p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-text-primary">Uso de disco</h2>
            <p className="text-xs text-text-secondary">Métrica disponível hoje: tamanho de `registry.db`.</p>
          </div>
          <HardDrive className="h-4 w-4 text-primary" />
        </div>
        <div className="rounded-xl bg-background/40 px-4 py-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-text-secondary">SQLite registry</span>
            <span className="text-sm font-medium text-text-primary">{formatBytes(dbSize)}</span>
          </div>
        </div>
        {dbSize > 100 * 1024 * 1024 ? (
          <Alert className="mt-4 border-amber-500/30 bg-amber-500/5 text-amber-200">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Tamanho acima do limiar de atenção</AlertTitle>
            <AlertDescription>O `registry.db` passou de 100 MB. Vale monitorar retenção e vacuum.</AlertDescription>
          </Alert>
        ) : null}
      </section>

      <section className="rounded-2xl border border-red-500/30 bg-red-500/5 p-5 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-red-100">Danger zone</h2>
            <p className="text-xs text-red-200/80">Intervenções manuais devem ser excepcionais e auditáveis.</p>
          </div>
          <AlertTriangle className="h-4 w-4 text-red-200" />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="destructive"
            onClick={handlePause}
            disabled={pauseMut.isPending || health?.scheduler_paused}
          >
            Pause pipeline
          </Button>
          <Button
            type="button"
            variant="outline"
            onClick={handleResume}
            disabled={resumeMut.isPending || !health?.scheduler_paused}
            className="border-red-300/30 bg-transparent text-red-100 hover:bg-red-500/10 hover:text-red-50"
          >
            Resume pipeline
          </Button>
          <span className="text-xs text-red-100/80">
            Estado atual: {health?.scheduler_paused ? "pausado" : "rodando"}
          </span>
        </div>
      </section>
    </div>
  );
}
