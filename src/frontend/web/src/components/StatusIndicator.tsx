import React from "react";

type StatusKind = "ok" | "warn" | "error";

interface StatusIndicatorProps {
  status: StatusKind;
  label: string;
  detail?: string;
  className?: string;
}

const STATUS_COLOR: Record<StatusKind, string> = {
  ok: "hsl(var(--status-ok))",
  warn: "hsl(var(--status-warn))",
  error: "hsl(var(--status-error))",
};

const STATUS_DURATION: Record<StatusKind, string> = {
  ok: "2.2s",
  warn: "1.2s",
  error: "0s",
};

export const StatusIndicator: React.FC<StatusIndicatorProps> = ({
  status,
  label,
  detail,
  className = "",
}) => {
  const pulseDuration = STATUS_DURATION[status];
  const color = STATUS_COLOR[status];
  const animated = status !== "error";
  const radiusValues = status === "warn" ? "4;12;12" : "4;10;10";
  const opacityValues = status === "warn" ? "0.5;0;0" : "0.35;0;0";

  return (
    <div className={`flex items-start gap-3 ${className}`}>
      <div className="mt-0.5 shrink-0" aria-hidden="true">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="4" fill={color} />
          {animated ? (
            <circle cx="12" cy="12" r="4" fill={color} opacity="0.5">
              <animate attributeName="r" values={radiusValues} dur={pulseDuration} repeatCount="indefinite" />
              <animate attributeName="opacity" values={opacityValues} dur={pulseDuration} repeatCount="indefinite" />
            </circle>
          ) : null}
        </svg>
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-foreground leading-tight">{label}</p>
        {detail ? <p className="text-xs text-text-secondary mt-1 leading-relaxed">{detail}</p> : null}
      </div>
    </div>
  );
};
