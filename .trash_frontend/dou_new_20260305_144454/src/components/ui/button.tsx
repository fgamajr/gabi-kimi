"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { Loader2 } from "lucide-react";

// =============================================================================
// Button Component — Design System v4.0
// =============================================================================

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "ghost" | "destructive" | "outline";
  size?: "sm" | "md" | "lg" | "icon";
  isLoading?: boolean;
  fullWidth?: boolean;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      isLoading = false,
      fullWidth = false,
      leftIcon,
      rightIcon,
      children,
      disabled,
      ...props
    },
    ref
  ) => {
    const baseStyles = cn(
      // Layout
      "inline-flex items-center justify-center gap-2",
      "touch-target btn-press no-select",
      
      // Typography
      "font-display font-semibold tracking-tight",
      
      // Transitions
      "transition-all duration-150 ease-out",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-canvas",
      
      // Disabled state
      "disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100",
      
      // Full width
      fullWidth && "w-full",
      
      className
    );

    const variants = {
      primary: cn(
        "bg-brand text-canvas",
        "hover:bg-brand-dim",
        "shadow-lg shadow-brand/20",
        "active:shadow-md active:shadow-brand/10"
      ),
      secondary: cn(
        "bg-raised text-primary",
        "border border-border hover:border-border-strong",
        "hover:bg-overlay"
      ),
      ghost: cn(
        "bg-transparent text-secondary",
        "hover:text-primary hover:bg-sunken"
      ),
      destructive: cn(
        "bg-error/10 text-error",
        "hover:bg-error/20",
        "border border-error/20"
      ),
      outline: cn(
        "bg-transparent text-primary",
        "border border-border",
        "hover:bg-raised hover:border-border-strong"
      ),
    };

    const sizes = {
      sm: "h-9 px-3 text-sm rounded-lg",
      md: "h-11 px-4 text-base rounded-xl",
      lg: "h-14 px-6 text-lg rounded-xl",
      icon: "h-11 w-11 rounded-xl",
    };

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variants[variant], sizes[size])}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            {children}
          </>
        ) : (
          <>
            {leftIcon && <span className="flex-shrink-0">{leftIcon}</span>}
            {children}
            {rightIcon && <span className="flex-shrink-0">{rightIcon}</span>}
          </>
        )}
      </button>
    );
  }
);

Button.displayName = "Button";

export { Button };
