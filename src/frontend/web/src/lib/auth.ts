import { resolveApiUrl } from "@/lib/runtimeConfig";

export class ApiAuthError extends Error {
  status: number;

  constructor(message = "Authentication required", status = 401) {
    super(message);
    this.name = "ApiAuthError";
    this.status = status;
  }
}

export interface SessionStatus {
  authenticated: boolean;
  principal?: {
    label?: string;
    source?: string;
  };
  expires_in_sec?: number;
}

export async function apiFetch(input: string, init: RequestInit = {}) {
  const headers = new Headers(init.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetch(input, {
    credentials: "include",
    ...init,
    headers,
  });

  if (response.status === 401) {
    throw new ApiAuthError("Authentication required", 401);
  }

  return response;
}

export async function getSessionStatus(): Promise<SessionStatus> {
  const response = await apiFetch(resolveApiUrl("/api/auth/session"));
  if (!response.ok) {
    throw new Error(`Session status error: ${response.status}`);
  }
  return response.json();
}

export async function createAccessSession(accessKey: string): Promise<SessionStatus> {
  const token = accessKey.trim();
  if (!token) {
    throw new Error("Access key is required");
  }

  const response = await fetch(resolveApiUrl("/api/auth/session"), {
    method: "POST",
    credentials: "include",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
  });

  if (response.status === 401) {
    throw new ApiAuthError("Invalid access key", 401);
  }
  if (!response.ok) {
    throw new Error(`Session bootstrap error: ${response.status}`);
  }

  return response.json();
}

export async function clearAccessSession() {
  await fetch(resolveApiUrl("/api/auth/session"), {
    method: "DELETE",
    credentials: "include",
  });
}
