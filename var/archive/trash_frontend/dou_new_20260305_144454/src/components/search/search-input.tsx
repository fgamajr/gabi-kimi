"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Search, Mic, X, Loader2 } from "lucide-react";

// =============================================================================
// Search Input Component — Design System v4.0
// =============================================================================

export interface SearchInputProps
  extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "size" | "onSubmit"> {
  value: string;
  onChange: (value: string) => void;
  onSubmit?: (value: string) => void;
  onClear?: () => void;
  isLoading?: boolean;
  showVoice?: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  inputSize?: "sm" | "md" | "lg";
}

const SearchInput = React.forwardRef<HTMLInputElement, SearchInputProps>(
  (
    {
      className,
      value,
      onChange,
      onSubmit,
      onClear,
      isLoading = false,
      showVoice = true,
      placeholder = "O que você procura?",
      autoFocus = false,
      inputSize = "md",
      ...props
    },
    ref
  ) => {
    const inputRef = React.useRef<HTMLInputElement>(null);
    const [isListening, setIsListening] = React.useState(false);

    // Merge refs
    React.useImperativeHandle(ref, () => inputRef.current!);

    // Handle keyboard shortcuts
    React.useEffect(() => {
      const handleKeyDown = (e: KeyboardEvent) => {
        // Focus search on "/" key
        if (e.key === "/" && !e.metaKey && !e.ctrlKey) {
          const target = e.target as HTMLElement;
          if (target.tagName !== "INPUT" && target.tagName !== "TEXTAREA") {
            e.preventDefault();
            inputRef.current?.focus();
          }
        }
        // Clear on Escape
        if (e.key === "Escape" && value) {
          onChange("");
          onClear?.();
        }
      };

      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }, [value, onChange, onClear]);

    // Auto focus
    React.useEffect(() => {
      if (autoFocus && inputRef.current) {
        inputRef.current.focus();
      }
    }, [autoFocus]);

    const handleSubmit = (e: React.FormEvent) => {
      e.preventDefault();
      if (value.trim()) {
        onSubmit?.(value);
      }
    };

    const handleClear = () => {
      onChange("");
      onClear?.();
      inputRef.current?.focus();
    };

    const handleVoiceClick = () => {
      // Voice search placeholder - would integrate with Web Speech API
      setIsListening(true);
      setTimeout(() => setIsListening(false), 2000);
    };

    const sizes = {
      sm: "h-10 pl-9 pr-8 text-sm rounded-lg",
      md: "h-12 pl-11 pr-10 text-base rounded-xl",
      lg: "h-14 pl-12 pr-12 text-lg rounded-xl",
    };

    const iconSizes = {
      sm: "h-4 w-4",
      md: "h-5 w-5",
      lg: "h-6 w-6",
    };

    const iconPositions = {
      sm: "left-3",
      md: "left-3.5",
      lg: "left-4",
    };

    return (
      <form onSubmit={handleSubmit} className={cn("relative w-full", className)}>
        {/* Search icon */}
        <div
          className={cn(
            "absolute top-1/2 -translate-y-1/2 text-muted pointer-events-none",
            iconPositions[inputSize]
          )}
        >
          {isLoading ? (
            <Loader2 className={cn(iconSizes[inputSize], "animate-spin text-brand")} />
          ) : (
            <Search className={iconSizes[inputSize]} />
          )}
        </div>

        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className={cn(
            "w-full bg-raised border border-border",
            "text-primary placeholder:text-muted",
            "font-display",
            "transition-all duration-150 ease-out",
            "focus:outline-none focus:border-brand focus:ring-2 focus:ring-brand/20",
            "input-focus touch-target-lg",
            sizes[inputSize],
            className
          )}
          inputMode="search"
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck="false"
          {...props}
        />

        {/* Right side actions */}
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
          {/* Clear button */}
          {value && (
            <button
              type="button"
              onClick={handleClear}
              className={cn(
                "p-1.5 rounded-lg text-muted hover:text-primary hover:bg-sunken",
                "transition-colors duration-150",
                "touch-target"
              )}
              aria-label="Limpar busca"
            >
              <X className={iconSizes[inputSize]} />
            </button>
          )}

          {/* Voice search button */}
          {showVoice && !value && (
            <button
              type="button"
              onClick={handleVoiceClick}
              className={cn(
                "p-1.5 rounded-lg text-muted hover:text-brand hover:bg-brand/10",
                "transition-colors duration-150",
                "touch-target",
                isListening && "text-brand bg-brand/10 animate-pulse"
              )}
              aria-label="Busca por voz"
            >
              <Mic className={iconSizes[inputSize]} />
            </button>
          )}
        </div>
      </form>
    );
  }
);

SearchInput.displayName = "SearchInput";

export { SearchInput };
