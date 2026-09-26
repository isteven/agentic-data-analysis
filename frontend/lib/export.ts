import { toPng } from "html-to-image";
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

/** The query result table as CSV text (header row first, CRLF line ends). */
export function toCsv(analysis: Analysis): string {
  const lines = [
    analysis.columns.map(csvCell).join(","),
    ...analysis.rows.map((row) => row.map(csvCell).join(",")),
  ];
  return lines.join("\r\n");
}

/** The query result table as a downloadable CSV. */
export function exportTableAsCsv(analysis: Analysis, filename: string) {
  // Leading BOM so Excel opens it as UTF-8 instead of guessing the system codepage.
  downloadBlob(new Blob(["﻿" + toCsv(analysis)], { type: "text/csv;charset=utf-8" }), filename);
}

/**
 * The chart exactly as displayed - bars, axes, HTML legend and theme colours - as a
 * PNG. Captures the rendered DOM rather than serializing Recharts' <svg>: the legend
 * is HTML outside the chart svg, legend icons are separate small svgs, and text
 * colours come from CSS that a bare svg export loses.
 */
async function captureChart(node: HTMLElement): Promise<{ dataUrl: string; width: number; height: number }> {
  const { width, height } = node.getBoundingClientRect();
  // The page background, so light/dark text stays readable in the image.
  const backgroundColor = getComputedStyle(document.body).backgroundColor;
  const dataUrl = await toPng(node, { backgroundColor, pixelRatio: 2 });
  return { dataUrl, width, height };
}

export async function exportChartAsPng(node: HTMLElement, filename: string) {
  const { dataUrl } = await captureChart(node);
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename;
  a.click();
}

/** The same image as exportChartAsPng on a PDF page, with the question as a caption. */
export async function exportChartAsPdf(node: HTMLElement, filename: string, caption?: string) {
  const { dataUrl, width, height } = await captureChart(node);
  const pdf = new jsPDF({ orientation: width > height ? "landscape" : "portrait", unit: "pt" });
  const margin = 40;
  const pageWidth = pdf.internal.pageSize.getWidth() - margin * 2;
  const pageHeight = pdf.internal.pageSize.getHeight() - margin * 2;
  const fit = Math.min(pageWidth / width, pageHeight / height);

  pdf.addImage(dataUrl, "PNG", margin, margin, width * fit, height * fit);
  if (caption) {
    pdf.setFontSize(9);
    pdf.text(caption, margin, margin + height * fit + 16, { maxWidth: pageWidth });
  }
  pdf.save(filename);
}
