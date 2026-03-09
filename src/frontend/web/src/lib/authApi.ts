import { resolveApiUrl } from "@/lib/runtimeConfig";
import type { SessionStatus } from "@/lib/auth";

export interface AuthErrorResponse {
  detail: string;
}

export class AuthApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "AuthApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function handleAuthResponse(response: Response): Promise<SessionStatus> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "Erro desconhecido" }));
    throw new AuthApiError(response.status, body.detail || `Erro ${response.status}`);
  }
  const payload = await response.json();
  window.dispatchEvent(new Event("gabi-auth-changed"));
  return payload;
}

export async function registerUser(data: {
  email: string;
  password: string;
  display_name: string;
}): Promise<SessionStatus> {
  const response = await fetch(resolveApiUrl("/api/auth/register"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(data),
  });
  return handleAuthResponse(response);
}

export async function loginWithPassword(
  email: string,
  password: string,
): Promise<SessionStatus> {
  const response = await fetch(resolveApiUrl("/api/auth/login"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleAuthResponse(response);
}

export interface MeResponse {
  id: string;
  email: string;
  display_name: string;
  roles: string[];
  login_method: string;
}

export async function getCurrentUser(): Promise<MeResponse> {
  const response = await fetch(resolveApiUrl("/api/auth/me"), {
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new AuthApiError(response.status, "Nao autenticado");
  return response.json();
}
