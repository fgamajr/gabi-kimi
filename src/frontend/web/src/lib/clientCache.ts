const CACHE_PREFIX = "gabi-client-cache:";

interface CachedValue<T> {
  value: T;
  expiresAt: number;
}

export function readCachedValue<T>(key: string): T | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.localStorage.getItem(`${CACHE_PREFIX}${key}`);
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as CachedValue<T>;
    if (!parsed || typeof parsed !== "object" || typeof parsed.expiresAt !== "number") return undefined;
    if (Date.now() > parsed.expiresAt) {
      window.localStorage.removeItem(`${CACHE_PREFIX}${key}`);
      return undefined;
    }
    return parsed.value;
  } catch {
    return undefined;
  }
}

export function writeCachedValue<T>(key: string, value: T, ttlMs: number) {
  if (typeof window === "undefined") return;
  try {
    const payload: CachedValue<T> = {
      value,
      expiresAt: Date.now() + ttlMs,
    };
    window.localStorage.setItem(`${CACHE_PREFIX}${key}`, JSON.stringify(payload));
  } catch {
    // Ignore quota and serialization issues in UI cache.
  }
}

export function clearCachedValue(key: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(`${CACHE_PREFIX}${key}`);
  } catch {
    // noop
  }
}
