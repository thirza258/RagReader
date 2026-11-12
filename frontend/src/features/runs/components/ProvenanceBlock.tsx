import React from "react";
import { formatDateTime } from "../../documents/lib/format";
import type { RunProvenance } from "../types";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function retrievalParameters(parameters: Record<string, unknown> | undefined): string {
  if (!parameters) return "—";
  const parts: string[] = [];
  if (parameters.context_k != null && parameters.candidate_k != null) parts.push(`top ${String(parameters.context_k)} of ${String(parameters.candidate_k)} candidates`);
  if (typeof parameters.similarity === "string") parts.push(`${parameters.similarity} similarity`);
  if (parameters.deduplicate) parts.push("duplicates removed");
  if (typeof parameters.history_messages === "number") parts.push(`${parameters.history_messages} history messages`);
  return parts.join(" · ") || "—";
}

function generationParameters(parameters: Record<string, unknown> | undefined): string {
  if (!parameters) return "—";
  const parts: string[] = [];
  if (parameters.temperature != null) parts.push(`temperature ${String(parameters.temperature)}`);
  if (parameters.stream) parts.push("streamed");
  return parts.join(" · ") || "—";
}

/** What produced the answer (PRD §20): pipeline, models, prompt and index versions. */
const ProvenanceBlock: React.FC<{ provenance: RunProvenance }> = ({ provenance }) => {
  const indexes = provenance.index_versions ?? [];
  const hidden = (provenance.index_version_count ?? indexes.length) - indexes.length;
  const answeredBy = provenance.generation_model;
  const configured = provenance.configured_generation_model;
  return (
    <dl className="divide-y divide-border border-y border-border">
      <Row label="Strategy">{provenance.strategy ?? "—"}</Row>
      <Row label="Retrieval">{retrievalParameters(provenance.retrieval_parameters)}</Row>
      <Row label="Embedding model">{provenance.embedding_model ?? "—"}</Row>
      <Row label="Reranker">{provenance.reranker ?? <span className="text-muted-foreground">None</span>}</Row>
      <Row label="Answered by">
        {answeredBy ?? <span className="text-muted-foreground">No model answered</span>}
        {provenance.fallback_used ? (
          <span className="block text-muted-foreground">Free-model fallback: the configured model ({configured ?? "unknown"}) had no credits.</span>
        ) : configured && configured !== answeredBy ? (
          <span className="block text-muted-foreground">Configured: {configured}</span>
        ) : null}
      </Row>
      <Row label="Generation">{generationParameters(provenance.generation_parameters)}</Row>
      <Row label="Prompt version">{provenance.prompt_version ?? "—"}</Row>
      <Row label="Index versions">
        {indexes.length === 0 ? (
          "—"
        ) : (
          <ul className="space-y-0.5">
            {indexes.map((index) => (
              <li key={`${index.document_id}-${index.index_version_id ?? "none"}`}>
                <span className="font-medium">{index.document_title || `Document ${index.document_id}`}</span>{" "}
                <span className="text-muted-foreground">
                  {index.index_version_id != null ? `index #${index.index_version_id}` : "no index"}
                  {index.created_at ? ` · built ${formatDateTime(index.created_at)}` : ""}
                  {index.embedding_model ? ` · ${index.embedding_model}` : ""}
                </span>
                {!index.loaded && <span className="ml-1 text-destructive">(could not be loaded)</span>}
              </li>
            ))}
            {hidden > 0 && <li className="text-muted-foreground">and {hidden} more</li>}
          </ul>
        )}
      </Row>
      {provenance.timestamp && <Row label="Recorded">{formatDateTime(provenance.timestamp)}</Row>}
    </dl>
  );
};

export default ProvenanceBlock;
