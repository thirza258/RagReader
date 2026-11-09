import React from "react";
import { focusRing } from "../../../components/ui/classes";
import { formatDuration, formatScore } from "../lib/retrievalSummary";
import type { ChatMessage } from "../types";

interface WhyThisAnswerProps {
  message: ChatMessage;
  /** Title for a document id, for candidates that were not passed to the model. */
  documentTitle: (documentId: number) => string | null;
}

const TIMING_LABELS: [keyof NonNullable<NonNullable<ChatMessage["retrieval"]>["timings_ms"]>, string][] = [
  ["rewrite", "Query rewrite"],
  ["embed_query", "Query embedding"],
  ["search", "Vector search"],
  ["first_token", "First token"],
  ["generation", "Generation"],
  ["total", "Total"],
];

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-2 py-1">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

/**
 * "Why this answer?" (PRD §21) from the Phase 1 retrieval metadata: how the
 * question was searched, how many passages survived each step, the scores of
 * the sources, timings, token usage and the model and prompt that answered.
 */
const WhyThisAnswer: React.FC<WhyThisAnswerProps> = ({ message, documentTitle }) => {
  const retrieval = message.retrieval;
  if (!retrieval) return null;
  const query = retrieval.query ?? {};
  const pipeline = retrieval.pipeline ?? {};
  const timings = retrieval.timings_ms ?? {};
  const usage = message.token_usage;
  const sources = [...message.citations].sort((a, b) => a.citation_id - b.citation_id);
  const titleFor = (id: number) => sources.find((source) => source.document_id === id)?.document_title || documentTitle(id) || `Document ${id}`;
  const funnel = [
    retrieval.candidate_count != null ? `${retrieval.candidate_count} candidates` : null,
    retrieval.context_count != null ? `${retrieval.context_count} in context` : null,
    retrieval.cited_count != null ? `${retrieval.cited_count} cited` : null,
  ].filter(Boolean);

  return (
    <details className="mt-3 border-t border-border pt-2 text-xs">
      <summary className={`cursor-pointer select-none font-medium text-muted-foreground hover:text-foreground ${focusRing}`}>Why this answer?</summary>
      <div className="mt-2 space-y-3">
        <dl className="divide-y divide-border border-y border-border">
          <Row label="Question">{query.original || "—"}</Row>
          <Row label="Searched for">
            {query.rewrite_applied && query.rewritten ? (
              <>
                “{query.rewritten}” <span className="text-muted-foreground">(rewritten using the conversation)</span>
              </>
            ) : (
              <span className="text-muted-foreground">The question as asked (no rewrite)</span>
            )}
          </Row>
          {funnel.length > 0 && <Row label="Retrieval">{funnel.join(" → ")}</Row>}
          <Row label="Strategy">
            {pipeline.strategy ?? "dense"}
            {pipeline.candidate_k != null && pipeline.top_k != null ? ` · top ${pipeline.top_k} of ${pipeline.candidate_k}` : ""}
          </Row>
          {pipeline.embedding_model && <Row label="Embedding model">{pipeline.embedding_model}</Row>}
          {pipeline.generation_model && (
            <Row label="Answered by">
              {pipeline.generation_model}
              {pipeline.temperature != null ? ` · temperature ${pipeline.temperature}` : ""}
            </Row>
          )}
          {pipeline.prompt_version && <Row label="Prompt version">{pipeline.prompt_version}</Row>}
        </dl>

        {sources.length > 0 && (
          <div>
            <p className="font-medium">Passages given to the model</p>
            <div className="mt-1 overflow-x-auto">
              <table className="w-full border-collapse text-left tabular">
                <thead className="text-muted-foreground">
                  <tr className="border-b border-border">
                    <th scope="col" className="py-1 pr-2 font-normal">#</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Document</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Page</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Retrieval</th>
                    <th scope="col" className="py-1 pr-2 font-normal">Rerank</th>
                    <th scope="col" className="py-1 font-normal">Cited</th>
                  </tr>
                </thead>
                <tbody>
                  {sources.map((source) => (
                    <tr key={source.citation_id} className="border-b border-border">
                      <td className="py-1 pr-2 font-mono">[{source.citation_id}]</td>
                      <td className="max-w-[12rem] truncate py-1 pr-2" title={source.document_title}>
                        {source.document_title}
                      </td>
                      <td className="py-1 pr-2">{source.page_number ?? "—"}</td>
                      <td className="py-1 pr-2 font-mono">{formatScore(source.retrieval_score) ?? "—"}</td>
                      <td className="py-1 pr-2 font-mono">{formatScore(source.rerank_score) ?? "—"}</td>
                      <td className="py-1">{source.cited ? "Yes" : "No"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {Array.isArray(retrieval.candidates) && retrieval.candidates.length > 0 && (
          <details>
            <summary className={`cursor-pointer select-none text-muted-foreground hover:text-foreground ${focusRing}`}>
              All {retrieval.candidates.length} candidates
            </summary>
            <ol className="mt-1 space-y-0.5 tabular">
              {retrieval.candidates.map((candidate) => (
                <li key={`${candidate.document_id}-${candidate.chunk_id}-${candidate.rank}`} className="flex gap-2">
                  <span className="w-6 shrink-0 text-right font-mono text-muted-foreground">{candidate.rank}.</span>
                  <span className="min-w-0 flex-1 truncate">
                    {titleFor(candidate.document_id)} <span className="text-muted-foreground">· chunk {String(candidate.chunk_id)}</span>
                  </span>
                  <span className="font-mono text-muted-foreground">{formatScore(candidate.retrieval_score) ?? "—"}</span>
                </li>
              ))}
            </ol>
          </details>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <p className="font-medium">Timings</p>
            <dl className="mt-1 tabular">
              {TIMING_LABELS.filter(([key]) => timings[key] != null).map(([key, label]) => (
                <div key={key} className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="font-mono">{formatDuration(timings[key], { precise: true })}</dd>
                </div>
              ))}
              {TIMING_LABELS.every(([key]) => timings[key] == null) && message.latency_ms != null && (
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Total</dt>
                  <dd className="font-mono">{formatDuration(message.latency_ms, { precise: true })}</dd>
                </div>
              )}
            </dl>
          </div>
          {usage && (
            <div>
              <p className="font-medium">Tokens</p>
              <dl className="mt-1 tabular">
                {(
                  [
                    ["Prompt", usage.prompt_tokens],
                    ["Completion", usage.completion_tokens],
                    ["Total", usage.total_tokens],
                  ] as const
                )
                  .filter(([, value]) => value != null)
                  .map(([label, value]) => (
                    <div key={label} className="flex justify-between gap-2">
                      <dt className="text-muted-foreground">{label}</dt>
                      <dd className="font-mono">{Number(value).toLocaleString("en-US")}</dd>
                    </div>
                  ))}
              </dl>
            </div>
          )}
        </div>
      </div>
    </details>
  );
};

export default WhyThisAnswer;
