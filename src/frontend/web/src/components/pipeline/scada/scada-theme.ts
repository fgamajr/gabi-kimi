import type { PlantStage, StageState } from "@/types/pipeline";

// ---------------------------------------------------------------------------
// SCADA Industrial Theme Constants
// ---------------------------------------------------------------------------

export const SCADA_COLORS = {
  bg: "#0A0E17",
  surfaceElevated: "#111827",
  surfaceMid: "#1F2937",
  border: "#374151",
  text: "#F9FAFB",
  textSecondary: "#9CA3AF",
  textTertiary: "#6B7280",
  green: "#22C55E",
  amber: "#F59E0B",
  red: "#EF4444",
  gray: "#6B7280",
} as const;

export const STATE_STYLES: Record<
  StageState,
  {
    border: string;
    glow: string;
    bg: string;
    dot: string;
    label: string;
    ring: string;
  }
> = {
  AUTO: {
    border: "border-green-500",
    glow: "shadow-[0_0_12px_rgba(34,197,94,0.3)]",
    bg: "bg-green-500/10",
    dot: "bg-green-400",
    label: "text-green-400",
    ring: "ring-green-500/40",
  },
  PAUSED: {
    border: "border-amber-500",
    glow: "shadow-[0_0_8px_rgba(245,158,11,0.2)]",
    bg: "bg-amber-500/10",
    dot: "bg-amber-400",
    label: "text-amber-400",
    ring: "ring-amber-500/40",
  },
  ERROR: {
    border: "border-red-500",
    glow: "shadow-[0_0_16px_rgba(239,68,68,0.4)]",
    bg: "bg-red-500/10",
    dot: "bg-red-400 animate-pulse",
    label: "text-red-400",
    ring: "ring-red-500/40",
  },
  IDLE: {
    border: "border-gray-600",
    glow: "",
    bg: "bg-gray-500/5",
    dot: "bg-gray-500",
    label: "text-gray-500",
    ring: "ring-gray-600/30",
  },
};

export const PIPE_STYLES = {
  active: {
    border: "border-green-500/60",
    bg: "bg-gradient-to-r from-green-500/20 to-green-500/5",
    glow: "shadow-[0_0_6px_rgba(34,197,94,0.15)]",
  },
  blocked: {
    border: "border-red-500/60",
    bg: "bg-gradient-to-r from-red-500/20 to-red-500/5",
    glow: "",
  },
  empty: {
    border: "border-gray-600 border-dashed",
    bg: "bg-transparent",
    glow: "",
  },
} as const;

export const STAGE_NAMES: Record<string, string> = {
  discovery: "Discovery",
  backfill_missing: "Backfill",
  download: "Download",
  extract: "Extract",
  bm25: "BM25 Index",
  embed: "Embedding",
  verify: "Verify",
};

/** Derive effective state from a PlantStage (client-side). */
export function deriveStageState(stage: PlantStage): StageState {
  if (!stage.enabled) return "IDLE";
  if (stage.failed_count > 0) return "ERROR";
  if (stage.state === "PAUSED") return "PAUSED";
  if (stage.state === "AUTO") return "AUTO";
  return stage.state;
}

/** Format uptime seconds as Xh Ym. */
export function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/** Format bytes to human-readable. */
export function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

/** Relative time from ISO string. */
export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `${hours}h ago`;
}

/** Threshold color class based on percent. */
export function thresholdColor(pct: number): string {
  if (pct > 80) return "text-red-400";
  if (pct > 60) return "text-amber-400";
  return "text-green-400";
}

export function thresholdBg(pct: number): string {
  if (pct > 80) return "bg-red-500";
  if (pct > 60) return "bg-amber-500";
  return "bg-green-500";
}
