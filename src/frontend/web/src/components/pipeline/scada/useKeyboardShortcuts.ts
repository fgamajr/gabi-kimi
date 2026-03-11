import { useCallback, useEffect, useState } from "react";

interface UseKeyboardShortcutsOptions {
  stageCount: number;
  onPause: (index: number) => void;
  onResume: (index: number) => void;
  onTrigger: (index: number) => void;
  onMasterToggle: () => void;
}

export function useKeyboardShortcuts({
  stageCount,
  onPause,
  onResume,
  onTrigger,
  onMasterToggle,
}: UseKeyboardShortcutsOptions) {
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      // 1-7: focus stage
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= stageCount) {
        e.preventDefault();
        setFocusedIndex(num - 1);
        return;
      }

      // Escape: clear focus
      if (e.key === "Escape") {
        e.preventDefault();
        setFocusedIndex(null);
        return;
      }

      // Space: master valve
      if (e.key === " ") {
        e.preventDefault();
        onMasterToggle();
        return;
      }

      if (focusedIndex === null) return;

      // P: pause focused stage
      if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        onPause(focusedIndex);
        return;
      }

      // R: resume focused stage
      if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        onResume(focusedIndex);
        return;
      }

      // T: trigger focused stage
      if (e.key === "t" || e.key === "T") {
        e.preventDefault();
        onTrigger(focusedIndex);
        return;
      }
    },
    [stageCount, focusedIndex, onPause, onResume, onTrigger, onMasterToggle],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return { focusedIndex, setFocusedIndex };
}
