import { apiFetch } from "@/lib/auth";
import { resolveApiUrl } from "@/lib/runtimeConfig";

function slugify(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

export function prefersPrintPdfFallback() {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const platform = navigator.platform || "";
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/.test(ua);
  return isIOS || isAndroid;
}

async function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function extractFilename(response: Response, fallback: string) {
  const disposition = response.headers.get("content-disposition") || "";
  const utf8Match = disposition.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
  const plainMatch = disposition.match(/filename\s*=\s*"?([^";]+)"?/i);
  const raw = utf8Match?.[1] || plainMatch?.[1] || fallback;
  const decoded = decodeURIComponent(raw).trim();
  return decoded.toLowerCase().endsWith(".pdf") ? decoded : `${decoded}.pdf`;
}

export async function downloadServerPdf(
  documentId: string,
  metadata: { title: string; section?: string; pubDate?: string }
) {
  const response = await apiFetch(resolveApiUrl(`/api/document/${encodeURIComponent(documentId)}/pdf`), {
    headers: { Accept: "application/pdf" },
  });
  if (!response.ok) {
    throw new Error(`PDF server error: ${response.status}`);
  }
  const blob = await response.blob();
  if (!blob.size) {
    throw new Error("PDF server error: empty response");
  }
  const fallbackFilename = [
    "DOU",
    metadata.section?.toUpperCase() || "DOC",
    metadata.pubDate || new Date().toISOString().slice(0, 10),
    slugify(metadata.title || "documento"),
  ].join("_") + ".pdf";
  const filename = extractFilename(response, fallbackFilename);
  await downloadBlob(blob, filename);
}
