function slugify(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 60);
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

  return html2pdf()
    .set({
      margin: [12, 12, 14, 12],
      filename,
      image: { type: "jpeg", quality: 0.95 },
      html2canvas: {
        scale: 2,
        useCORS: true,
        backgroundColor: "#121520",
      },
      jsPDF: {
        unit: "mm",
        format: "a4",
        orientation: "portrait",
      },
      pagebreak: { mode: ["css", "legacy"] },
    })
    .from(element)
    .save();
}
