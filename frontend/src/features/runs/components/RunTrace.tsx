import React from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import type { Evidence } from "../../chat/types";
import { describeRewrite, formatCount, formatMs, funnelText, runFunnel, stageName } from "../lib/runMetrics";
import type { RetrievalRunDetail } from "../types";
import CandidateTable from "./CandidateTable";
import LatencyWaterfall from "./LatencyWaterfall";
import ProvenanceBlock from "./ProvenanceBlock";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="font-medium">{title}</h4>
      <div className="mt-1">{children}</div>
    </section>
  );
}

function Figures({ items }: { items: [string, string][] }) {
  return (
    <dl className="tabular">
      {items.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-2">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="font-mono">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

interface RunTraceProps {
  run: RetrievalRunDetail;
  /** Opens a retrieved passage in the reader. */
  onOpenCandidate: (evidence: Evidence) => void;
}

/**
 * One run, inspected (PRD §20–21, §32): what was searched, how many passages
 * survived each step, every candidate with its scores, where the time went,
 * what it cost, and the exact pipeline that produced it.
 */
const RunTrace: React.FC<RunTraceProps> = ({ run, onOpenCandidate }) => {
  const rewrite = describeRewrite(run.query);
  const latency = run.latency_ms ?? ({} as RetrievalRunDetail["latency_ms"]);
  const usage = run.token_usage;
  return (
    <div className="space-y-3 text-xs">
      {run.status === "failed" && run.error && (
        <ErrorNotice title={`This run failed during ${stageName(run.error.stage)}`} code={run.error.code} message={run.error.message} />
      )}

      <dl className="divide-y divide-border border-y border-border">
        <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1">
          <dt className="text-muted-foreground">Question</dt>
          <dd className="min-w-0 break-words">{run.query?.original || "—"}</dd>
        </div>
        <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1">
          <dt className="text-muted-foreground">Searched for</dt>
          <dd className="min-w-0 break-words">
            {rewrite.applied ? (
              <>
                “{rewrite.text}” <span className="text-muted-foreground">(rewritten using the conversation)</span>
              </>
            ) : (
              <>
                The question as asked. <span className="text-muted-foreground">{rewrite.text}</span>
              </>
            )}
          </dd>
        </div>
        <div className="grid grid-cols-[8.5rem_1fr] gap-2 py-1">
          <dt className="text-muted-foreground">Retrieval funnel</dt>
          <dd className="min-w-0 font-mono">{funnelText(runFunnel(run))}</dd>
        </div>
      </dl>

      <Section title={`Retrieved candidates (${run.candidates.length})`}>
        <CandidateTable candidates={run.candidates} onOpen={onOpenCandidate} />
      </Section>

      <Section title="Latency">
        <LatencyWaterfall spans={run.spans} totalMs={latency.total} />
      </Section>

      <div className="grid gap-3 sm:grid-cols-2">
        <Section title="Timings">
          <Figures
            items={[
              ["Total", formatMs(latency.total)],
              ["First token", formatMs(latency.first_token)],
              ["Query rewrite", formatMs(latency.rewrite)],
              ["Retrieval", formatMs(latency.retrieval)],
              ["Reranking", formatMs(latency.rerank)],
              ["Generation", formatMs(latency.generation)],
            ]}
          />
        </Section>
        <Section title="Tokens">
          {usage ? (
            <Figures
              items={[
                ["Prompt", formatCount(usage.prompt_tokens)],
                ["Completion", formatCount(usage.completion_tokens)],
                ["Total", formatCount(usage.total_tokens)],
              ]}
            />
          ) : (
            <p className="text-muted-foreground">No token usage was reported.</p>
          )}
        </Section>
      </div>

      <Section title="Pipeline">
        <ProvenanceBlock provenance={run.provenance ?? {}} />
      </Section>
    </div>
  );
};

export default RunTrace;
