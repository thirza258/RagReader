import type { WorkspaceDocument } from "../types/index.ts";
import { statusLabel } from "./ingestionStages.ts";

const SOURCE_LABELS: Record<string, string> = {
  pdf: "PDF",
  docx: "Word",
  txt: "Text file",
  md: "Markdown",
  markdown: "Markdown",
  url: "Web page",
  text: "Pasted text",
};

export function sourceLabel(sourceType: string): string {
  return SOURCE_LABELS[(sourceType || "").toLowerCase()] ?? sourceType ?? "Document";
}

function count(value: number | null | undefined, singular: string, pluralForm = `${singular}s`): string | null {
  if (value == null || !Number.isFinite(value) || value <= 0) return null;
  return `${value.toLocaleString("en-US")} ${value === 1 ? singular : pluralForm}`;
}

/** "PDF · 15 pages · 384 chunks · Ready" (PRD §11). */
export function documentMetaLine(document: Pick<WorkspaceDocument, "source_type" | "page_count" | "chunk_count" | "status" | "progress">): string {
  const status = document.status === "READY" || document.status === "FAILED" ? statusLabel(document.status) : `${statusLabel(document.status)} ${Math.max(0, Math.min(100, Math.round(document.progress || 0)))}%`;
  return [sourceLabel(document.source_type), count(document.page_count, "page"), count(document.chunk_count, "chunk"), status]
    .filter(Boolean)
    .join(" · ");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString(undefined, { dateStyle: "medium" });
}
