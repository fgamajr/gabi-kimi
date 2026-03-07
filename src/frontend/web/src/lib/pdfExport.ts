function slugify(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
}

function waitForAnimationFrame() {
  return new Promise<void>((resolve) => {
    window.requestAnimationFrame(() => resolve());
  });
}

async function waitForImages(root: HTMLElement) {
  const images = Array.from(root.querySelectorAll("img"));
  await Promise.all(
    images.map(async (img) => {
      try {
        if ("decode" in img) {
          await img.decode();
          return;
        }
      } catch {
        // Ignore decode failures and let html2canvas proceed with the current bitmap state.
      }
      if (img.complete) return;
      await new Promise<void>((resolve) => {
        const done = () => resolve();
        img.addEventListener("load", done, { once: true });
        img.addEventListener("error", done, { once: true });
      });
    })
  );
}

function buildPrintShell(source: HTMLElement, metadata: { title: string; section?: string; pubDate?: string }) {
  const host = document.createElement("div");
  host.setAttribute("data-pdf-render-root", "true");
  host.style.position = "fixed";
  host.style.left = "-20000px";
  host.style.top = "0";
  host.style.width = "980px";
  host.style.padding = "32px";
  host.style.background = "#ffffff";
  host.style.color = "#111111";
  host.style.zIndex = "-1";
  host.style.pointerEvents = "none";

  const shell = document.createElement("div");
  shell.style.fontFamily = "Inter, system-ui, sans-serif";
  shell.style.color = "#111111";
  shell.style.background = "#ffffff";
  shell.style.lineHeight = "1.65";

  const masthead = document.createElement("div");
  masthead.style.borderBottom = "1px solid #d4d8e1";
  masthead.style.paddingBottom = "18px";
  masthead.style.marginBottom = "24px";

  const eyebrow = document.createElement("div");
  eyebrow.textContent = "Diário Oficial da União";
  eyebrow.style.fontSize = "11px";
  eyebrow.style.textTransform = "uppercase";
  eyebrow.style.letterSpacing = "0.2em";
  eyebrow.style.color = "#6b7280";
  eyebrow.style.marginBottom = "12px";

  const title = document.createElement("h1");
  title.textContent = metadata.title || "Documento";
  title.style.fontSize = "28px";
  title.style.lineHeight = "1.2";
  title.style.margin = "0";
  title.style.color = "#111111";

  const meta = document.createElement("p");
  meta.textContent = [metadata.section?.toUpperCase(), metadata.pubDate].filter(Boolean).join(" · ");
  meta.style.margin = "10px 0 0";
  meta.style.fontSize = "13px";
  meta.style.color = "#4b5563";

  masthead.appendChild(eyebrow);
  masthead.appendChild(title);
  if (meta.textContent) masthead.appendChild(meta);

  const clone = source.cloneNode(true) as HTMLElement;

  clone.querySelectorAll<HTMLElement>("button, .document-chrome, .document-mobile-actions, .document-secondary-panels, .reading-progress").forEach((node) => {
    node.remove();
  });

  clone.querySelectorAll<HTMLElement>("*").forEach((node) => {
    node.style.animation = "none";
    node.style.transition = "none";
    node.style.transform = "none";
    node.style.boxShadow = "none";
    node.style.backdropFilter = "none";
  });

  clone.querySelectorAll<HTMLElement>(".publication-body, .prose-doc").forEach((node) => {
    node.style.color = "#111111";
    node.style.background = "#ffffff";
    node.style.fontFamily = "Georgia, serif";
    node.style.fontSize = "15px";
    node.style.lineHeight = "1.7";
  });

  clone.querySelectorAll<HTMLElement>("a").forEach((node) => {
    node.style.color = "#111111";
    node.style.textDecoration = "underline";
  });

  clone.querySelectorAll<HTMLElement>(".image-fallback").forEach((node) => {
    node.style.background = "#f8fafc";
    node.style.border = "1px dashed #cbd5e1";
    node.style.color = "#111111";
  });

  shell.appendChild(masthead);
  shell.appendChild(clone);
  host.appendChild(shell);
  document.body.appendChild(host);
  return host;
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

export async function downloadServerPdf(documentId: string, metadata: { title: string; section?: string; pubDate?: string }) {
  const response = await fetch(`/api/document/${encodeURIComponent(documentId)}/pdf`);
  if (!response.ok) {
    throw new Error(`PDF server error: ${response.status}`);
  }
  const blob = await response.blob();
  const filename = [
    "DOU",
    metadata.section?.toUpperCase() || "DOC",
    metadata.pubDate || new Date().toISOString().slice(0, 10),
    slugify(metadata.title || "documento"),
  ].join("_") + ".pdf";
  await downloadBlob(blob, filename);
}

export async function exportDocumentPdf(
  element: HTMLElement,
  metadata: { title: string; section?: string; pubDate?: string }
) {
  const html2pdf = (await import("html2pdf.js")).default;
  const filename = [
    "DOU",
    metadata.section?.toUpperCase() || "DOC",
    metadata.pubDate || new Date().toISOString().slice(0, 10),
    slugify(metadata.title || "documento"),
  ].join("_") + ".pdf";

  const printRoot = buildPrintShell(element, metadata);

  try {
    if (document.fonts?.ready) {
      await document.fonts.ready;
    }
    await waitForAnimationFrame();
    await waitForImages(printRoot);
    await waitForAnimationFrame();

    return html2pdf()
      .set({
        margin: [10, 10, 12, 10],
        filename,
        image: { type: "jpeg", quality: 0.98 },
        html2canvas: {
          scale: 2,
          useCORS: true,
          backgroundColor: "#ffffff",
          logging: false,
        },
        jsPDF: {
          unit: "mm",
          format: "a4",
          orientation: "portrait",
        },
        pagebreak: { mode: ["css", "legacy"] },
      })
      .from(printRoot)
      .save();
  } finally {
    printRoot.remove();
  }
}
