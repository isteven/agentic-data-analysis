import { jsPDF } from "jspdf";
import type { Analysis, Cell } from "@/lib/types";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function csvCell(value: Cell): string {
  const s = value === null ? "" : String(value);
  // Quote whenever the value could be misread as a separate field or a new row.
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** The query result table as a downloadable CSV. */
export function exportTableAsCsv(analysis: Analysis, filename: string) {
  const lines = [
    analysis.columns.map(csvCell).join(","),
    ...analysis.rows.map((row) => row.map(csvCell).join(",")),
  ];
  // Leading BOM so Excel opens it as UTF-8 instead of guessing the system codepage.
  downloadBlob(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" }), filename);
}

/**
 * Renders an SVG element to a PDF page, sized to fit the page with a margin.
 * Recharts renders the chart as plain SVG, so this rasterizes that SVG onto a canvas
 * (crisper than a DOM screenshot of the whole card) and drops the bitmap into the PDF.
 */
export async function exportSvgAsPdf(svg: SVGSVGElement, filename: string, caption?: string) {
  const { width, height } = svg.getBoundingClientRect();
  const scale = 2; // for a print-quality raster, not a blurry screen-res one

  const canvas = document.createElement("canvas");
  canvas.width = width * scale;
  canvas.height = height * scale;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context is unavailable");
  ctx.scale(scale, scale);
  // White background: chart strokes are theme-aware and can be near-invisible on a
  // transparent PDF page in dark mode otherwise.
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, width, height);

  const svgData = new XMLSerializer().serializeToString(svg);
  const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgData)}`;
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to rasterize the chart"));
    img.src = svgUrl;
  });
  ctx.drawImage(image, 0, 0, width, height);

  const pdf = new jsPDF({ orientation: width > height ? "landscape" : "portrait", unit: "pt" });
  const margin = 40;
  const pageWidth = pdf.internal.pageSize.getWidth() - margin * 2;
  const pageHeight = pdf.internal.pageSize.getHeight() - margin * 2;
  const fit = Math.min(pageWidth / width, pageHeight / height);

  pdf.addImage(canvas.toDataURL("image/png"), "PNG", margin, margin, width * fit, height * fit);
  if (caption) {
    pdf.setFontSize(9);
    pdf.text(caption, margin, margin + height * fit + 16, { maxWidth: pageWidth });
  }
  pdf.save(filename);
}
