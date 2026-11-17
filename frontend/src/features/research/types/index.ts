import type { Evidence } from "../../chat/types";

/** Research tasks (PRD §22–25, §47; docs/prd-implementation.md, Phase 5). */

export type ResearchKind = "verify_claim" | "ask" | "compare" | "extract" | "contradictions" | "report";
export type ResearchStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type FieldType = "text" | "number" | "list" | "boolean";
export type Verdict = "supported" | "contradicted" | "mixed" | "insufficient_evidence";
export type Confidence = "low" | "moderate" | "high";
export type Stance = "supports" | "contradicts" | "neutral";

export interface FieldSpec {
  name: string;
  type: FieldType;
  description?: string;
}

export interface ClaimResult {
  claim: string;
  verdict: Verdict;
  confidence: Confidence;
  counter_query: string | null;
  conclusion: string | null;
  supporting: number[];
  contradicting: number[];
  neutral: number[];
  assessments: { citation_id: number; stance: Stance; rationale: string | null }[];
}

export interface AskResult {
  question: string;
  per_document: { document_id: number; document_title: string; answer: string | null; found: boolean; citation_ids: number[] }[];
  comparison: string | null;
  synthesis: string | null;
}

export interface CompareResult {
  documents: { id: number; title: string }[];
  dimensions: {
    name: string;
    findings: { document_id: number; finding: string | null; citation_ids: number[]; status: "found" | "not_stated" }[];
    difference: string | null;
  }[];
  summary: string | null;
}

export interface ExtractResult {
  fields: { name: string; type: FieldType; value: unknown; citation_ids: number[]; status: "found" | "not_found" | "uncited" | "invalid" }[];
  data: Record<string, unknown>;
}

export interface ContradictionsResult {
  topic: string;
  contradictions: { a: number; b: number; severity: "direct" | "partial"; explanation: string | null; cross_document: boolean }[];
  summary: string | null;
}

export interface ReportResult {
  question: string;
  title: string;
  summary: string;
  sections: { heading: string; body: string | null }[];
  limitations: string | null;
}

export interface ResearchTask {
  id: number;
  workspace_id: number;
  kind: ResearchKind;
  kind_label: string;
  title: string;
  status: ResearchStatus;
  input: Record<string, unknown>;
  documents: { id: number; title: string | null }[];
  pipeline: { id: number | null; name: string | null; version_id: number | null; version: number | null; strategy: string | null; available: boolean };
  progress: { stage?: string; detail?: string };
  error: { code: string; message: string; retryable: boolean; stage: string | null } | null;
  run_id: number | null;
  latency_ms: number | null;
  notes: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Detail only. */
  result?: unknown;
  evidence?: Evidence[];
}

export interface ResearchOptions {
  kinds: { id: ResearchKind; label: string }[];
  default_dimensions: string[];
  field_types: FieldType[];
  limits: Record<string, number | number[]>;
  max_evidence: number;
}
