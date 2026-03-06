import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind classes with proper precedence
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Format date for display (Brazilian Portuguese)
 */
export function formatDate(date: string | Date, options?: Intl.DateTimeFormatOptions): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const defaultOptions: Intl.DateTimeFormatOptions = {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...options,
  };
  return d.toLocaleDateString("pt-BR", defaultOptions);
}

/**
 * Format relative time (e.g., "há 2 minutos")
 */
export function formatRelativeTime(date: string | Date): string {
  const d = typeof date === "string" ? new Date(date) : date;
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSecs < 60) return "agora";
  if (diffMins < 60) return `há ${diffMins} min`;
  if (diffHours < 24) return `há ${diffHours}h`;
  if (diffDays < 7) return `há ${diffDays} dias`;
  
  return formatDate(date);
}

/**
 * Format number with Brazilian separators
 */
export function formatNumber(num: number): string {
  return num.toLocaleString("pt-BR");
}

/**
 * Truncate text with ellipsis
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength).trim() + "...";
}

/**
 * Generate a shareable URL with state
 */
export function generateShareUrl(
  baseUrl: string,
  params: Record<string, string | number | boolean | undefined>
): string {
  const url = new URL(baseUrl, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

/**
 * Debounce function
 */
export function debounce<T extends (...args: string[]) => void>(
  fn: T,
  delay: number
): (arg: string) => void {
  let timeoutId: ReturnType<typeof setTimeout>;
  return (arg: string) => {
    clearTimeout(timeoutId);
    timeoutId = setTimeout(() => fn(arg), delay);
  };
}

/**
 * Get section color by DOU section number
 */
export function getSectionColor(section: 1 | 2 | 3 | "e" | string): string {
  const colors: Record<string, string> = {
    "1": "#4FA8FF",  // Azul
    "2": "#FF9040",  // Laranja
    "3": "#B06EFF",  // Violeta
    "e": "#FF4D6A",  // Vermelho
    "E": "#FF4D6A",
  };
  return colors[String(section)] || "#A0A0BE";
}

/**
 * Get section name by DOU section number
 */
export function getSectionName(section: 1 | 2 | 3 | "e" | string): string {
  const names: Record<string, string> = {
    "1": "Seção 1",
    "2": "Seção 2",
    "3": "Seção 3",
    "e": "Extra",
    "E": "Extra",
  };
  return names[String(section)] || "Seção";
}

/**
 * Sanitize HTML for display (basic)
 */
export function sanitizeHtml(html: string): string {
  // Remove script tags and event handlers
  return html
    .replace(/<script[^>]*>.*?<\/script>/gi, "")
    .replace(/on\w+\s*=/gi, "data-blocked=");
}

/**
 * Copy to clipboard with fallback
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fallback for older browsers
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    try {
      document.execCommand("copy");
      return true;
    } catch {
      return false;
    } finally {
      document.body.removeChild(textarea);
    }
  }
}

/**
 * Check if device is touch-capable
 */
export function isTouchDevice(): boolean {
  return "ontouchstart" in window || navigator.maxTouchPoints > 0;
}

/**
 * Check if user prefers reduced motion
 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
