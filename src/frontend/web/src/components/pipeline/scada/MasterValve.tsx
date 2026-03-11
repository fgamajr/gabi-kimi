import { Switch } from "@/components/ui/switch";
import { usePauseAll, useResumeAll } from "@/hooks/usePipeline";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface MasterValveProps {
  paused: boolean;
}

export default function MasterValve({ paused }: MasterValveProps) {
  const pauseAll = usePauseAll();
  const resumeAll = useResumeAll();

  const handleToggle = async (checked: boolean) => {
    try {
      if (checked) {
        await resumeAll.mutateAsync();
        toast.success("Pipeline resumed.");
      } else {
        await pauseAll.mutateAsync();
        toast.success("Pipeline paused.");
      }
    } catch (err) {
      toast.error(`Toggle failed: ${(err as Error).message}`);
    }
  };

  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-lg border p-3",
        paused
          ? "border-red-500/50 bg-red-500/5"
          : "border-green-500/50 bg-green-500/5"
      )}
    >
      <span
        className="text-[10px] uppercase tracking-widest text-gray-400"
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        Master
      </span>
      <Switch
        checked={!paused}
        onCheckedChange={handleToggle}
        className={cn(
          paused
            ? "data-[state=unchecked]:bg-red-600"
            : "data-[state=checked]:bg-green-600"
        )}
      />
      <span
        className={cn(
          "text-[10px] font-semibold",
          paused ? "text-red-400" : "text-green-400"
        )}
        style={{ fontFamily: "'JetBrains Mono', monospace" }}
      >
        {paused ? "STOPPED" : "RUNNING"}
      </span>
    </div>
  );
}
