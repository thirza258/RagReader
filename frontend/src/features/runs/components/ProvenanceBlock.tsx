import React from "react";
import { formatDateTime } from "../../documents/lib/format";
import { describeConfig } from "../../pipelines/lib/pipelineConfig";
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
  if (parameters.fusion === "rrf") parts.push(`reciprocal rank fusion, k ${String(parameters.rrf_k)}`);
  else if (parameters.fusion === "weighted") parts.push(`weighted fusion, hybrid weight ${String(parameters.hybrid_weight)}`);
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

function Reranker({ reranker }: { reranker: RunProvenance["reranker"] }) {
  if (reranker == null) return <span className="text-muted-foreground">None</span>;
  if (typeof reranker === "string") return <>{reranker}</>;
  return (
    <>
      {reranker.provider ?? "—"} · <span className="font-mono">{reranker.model ?? "—"}</span>
      {reranker.fallback ? (
        <span className="block text-status-warning">
          Failed{reranker.error_code ? ` (${reranker.error_code})` : ""}: the fused order was kept.
        </span>
      ) : reranker.applied ? (
        <span className="block text-muted-foreground">Reordered the candidates before the top passages were chosen.</span>
      ) : null}
    </>
  );
}

/** What produced the answer (PRD §20): pipeline version, models, prompt and index versions. */
const ProvenanceBlock: React.FC<{ provenance: RunProvenance }> = ({ provenance }) => {
  const indexes = provenance.index_versions ?? [];
  const hidden = (provenance.index_version_count ?? indexes.length) - indexes.length;
  const answeredBy = provenance.generation_model;
  const configured = provenance.configured_generation_model;
  return (
    <dl className="divide-y divide-border border-y border-border">
      <Row label="Pipeline">
        {provenance.pipeline?.name ? (
          <>
            {provenance.pipeline.name}
            {provenance.pipeline.version != null && <span className="font-mono"> v{provenance.pipeline.version}</span>}
            {provenance.pipeline.config && <span className="block text-muted-foreground">{describeConfig(provenance.pipeline.config)}</span>}
            {provenance.pipeline.config_hash && (
              <span className="block font-mono text-[10px] text-muted-foreground" title="Configuration hash">
                {provenance.pipeline.config_hash.slice(0, 12)}
              </span>
            )}
          </>
        ) : (
          <span className="text-muted-foreground">Recorded before pipelines (Phase 1 dense chat)</span>
        )}
      </Row>
      <Row label="Strategy">{provenance.strategy ?? "—"}</Row>
      <Row label="Retrieval">{retrievalParameters(provenance.retrieval_parameters)}</Row>
      <Row label="Embedding model">{provenance.embedding_model ?? "—"}</Row>
      <Row label="Reranker">
        <Reranker reranker={provenance.reranker} />
      </Row>
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
