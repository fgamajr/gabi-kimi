/**
 * Admin upload API: upload file to POST /api/admin/upload with progress.
 * Uses XHR so we can report upload progress; sends credentials for auth.
 */
import { resolveApiUrl } from "@/lib/runtimeConfig";

const UPLOAD_PATH = "/api/admin/upload";

export interface UploadResult {
  job_id: string;
  status: string;
}

/**
 * Upload a file to the admin upload endpoint with optional progress callback.
 * Uses XMLHttpRequest for upload progress; credentials included for admin auth.
 */
export function uploadAdminFile(
  file: File,
  onProgress?: (percent: number) => void
): Promise<UploadResult> {
  const url = resolveApiUrl(UPLOAD_PATH);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);

    xhr.withCredentials = true;

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable && onProgress) {
        const percent = Math.round((e.loaded / e.total) * 100);
        onProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText) as UploadResult;
          resolve(data);
        } catch {
          reject(new Error("Resposta inválida do servidor"));
        }
      } else {
        let message = `Upload falhou (${xhr.status})`;
        try {
          const body = JSON.parse(xhr.responseText);
          if (body.detail) {
            message = typeof body.detail === "string" ? body.detail : body.detail.message || message;
          }
        } catch {
          if (xhr.responseText) message = xhr.responseText.slice(0, 200);
        }
        reject(new Error(message));
      }
    });

    xhr.addEventListener("error", () => reject(new Error("Erro de rede")));
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelado")));

    xhr.open("POST", url);
    xhr.send(formData);
  });
}
