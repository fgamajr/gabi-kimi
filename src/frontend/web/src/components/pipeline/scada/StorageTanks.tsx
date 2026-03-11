import type { PlantStorage } from "@/types/pipeline";
import { formatBytes, thresholdBg, thresholdColor } from "./scada-theme";
import { cn } from "@/lib/utils";

interface StorageTanksProps {
  storage: PlantStorage;
}

interface TankProps {
  label: string;
  value: string;
  pct: number;
}

function Tank({ label, value, pct }: TankProps) {
  const clampedPct = Math.min(100, Math.max(0, pct));
  return (
    <div className="flex flex-col items-center gap-1.5">
      <span className="text-[10px] uppercase tracking-wider text-gray-500">{label}</span>
      {/* Tank body */}
      <div className="relative h-20 w-6 rounded-sm border border-gray-600 bg-gray-800/50 overflow-hidden">
        <div
          className={cn("absolute bottom-0 left-0 right-0 transition-all", thresholdBg(clampedPct))}
          style={{ height: `${clampedPct}%`, opacity: 0.7 }}
        />
      </div>
      <span
        className={cn("text-[10px] font-mono font-semibold", thresholdColor(clampedPct))}
      >
        {value}
      </span>
    </div>
  );
}

export default function StorageTanks({ storage }: StorageTanksProps) {
  const diskUsedPct =
    storage.disk_total_bytes > 0
      ? ((storage.disk_total_bytes - storage.disk_free_bytes) / storage.disk_total_bytes) * 100
      : 0;

  // SQLite as percent of 1 GB reference
  const sqlitePct = Math.min(100, (storage.sqlite_bytes / (1024 * 1024 * 1024)) * 100);

  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-gray-700/50 bg-gray-900/40 p-3">
      <span
        className="text-[10px] uppercase tracking-widest text-gray-500"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        Storage
      </span>
      <div className="flex gap-4">
        <Tank label="Registry" value={formatBytes(storage.sqlite_bytes)} pct={sqlitePct} />
        <Tank label="Disk" value={`${diskUsedPct.toFixed(0)}%`} pct={diskUsedPct} />
        <Tank label="ES" value="N/A" pct={0} />
      </div>
    </div>
  );
}
