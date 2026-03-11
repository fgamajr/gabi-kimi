import { PIPE_STYLES } from "./scada-theme";
import { cn } from "@/lib/utils";

interface PipeConnectionProps {
  state: "active" | "blocked" | "empty";
  vertical?: boolean;
}

export default function PipeConnection({ state, vertical = false }: PipeConnectionProps) {
  const style = PIPE_STYLES[state];

  if (vertical) {
    return (
      <div className={cn("mx-auto h-6 w-0.5 border-l-2", style.border, style.glow)} />
    );
  }

  return (
    <div
      className={cn(
        "hidden lg:flex items-center self-center",
        "w-8 h-0.5 border-t-2",
        "md:w-4 lg:w-8",
        style.border,
        style.bg,
        style.glow,
      )}
    />
  );
}
