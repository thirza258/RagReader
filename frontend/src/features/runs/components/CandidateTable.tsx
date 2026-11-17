import React from "react";
import { focusRing } from "../../../components/ui/classes";
import type { Evidence } from "../../chat/types";
import { candidateScoreColumns, candidateToEvidence, formatCandidateScore, hasRankChanges, rankMovement } from "../lib/runMetrics";
import type { RunCandidate } from "../types";

function pageLabel(candidate: RunCandidate): string {
  if (candidate.page_number == null) return "—";
  return candidate.page_end != null && candidate.page_end !== candidate.page_number ? `${candidate.page_number}–${candidate.page_end}` : String(candidate.page_number);
}

function snippet(text: string, limit = 160): string {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit).trimEnd()}…` : flat;
}

/** "4 → 1 ▲": where reranking moved the passage; just the rank when it did not move. */
function RankCell({ candidate }: { candidate: RunCandidate }) {
  const movement = rankMovement(candidate);
  if (movement.delta === 0) return <>{movement.after}</>;
  return (
    <span title={movement.text}>
      <span className="text-muted-foreground">{movement.before}</span>
      <span aria-hidden="true"> → </span>
      <span className="sr-only"> moved to </span>
      {movement.after}
      <span aria-hidden="true" className={movement.delta > 0 ? "ml-0.5 text-status-success" : "ml-0.5 text-status-warning"}>
        {movement.delta > 0 ? "▲" : "▼"}
      </span>
    </span>
  );
}

interface CandidateTableProps {
  candidates: readonly RunCandidate[];
  onOpen: (evidence: Evidence) => void;
}

/**
 * Every passage retrieval returned (PRD §21), in final rank order: the
 * scores that placed it (dense, BM25, fused and rerank — whichever the
 * pipeline computed), how reranking moved it, whether it was given to the
 * model and whether the answer cited it. Opening a row shows the passage in
 * the reader, like a citation.
 */
const CandidateTable: React.FC<CandidateTableProps> = ({ candidates, onOpen }) => {
  if (candidates.length === 0) return <p className="text-muted-foreground">No passages were retrieved.</p>;
  const columns = candidateScoreColumns(candidates);
  const moved = hasRankChanges(candidates);
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left tabular">
        <caption className="sr-only">Retrieved candidates in rank order. Open a document to read the passage.</caption>
        <thead className="text-muted-foreground">
          <tr className="border-b border-border">
            <th scope="col" className="py-1 pr-2 font-normal" title={moved ? "Rank before reranking → final rank" : "Rank"}>
              {moved ? "Rank (before → after)" : "#"}
            </th>
            <th scope="col" className="py-1 pr-2 font-normal">Document</th>
            <th scope="col" className="py-1 pr-2 font-normal">Page</th>
            {columns.map((column) => (
              <th key={column.key} scope="col" className="py-1 pr-2 font-normal" title={column.title}>
                {column.label}
              </th>
            ))}
            <th scope="col" className="py-1 pr-2 font-normal">Context</th>
            <th scope="col" className="py-1 font-normal">Cited</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((candidate) => {
            const evidence = candidateToEvidence(candidate);
            return (
              <tr
                key={`${candidate.rank}-${candidate.chunk_id ?? "x"}`}
                className={`border-b border-border align-top ${evidence ? "cursor-pointer hover:bg-accent" : ""} ${candidate.selected_for_context ? "" : "text-muted-foreground"}`}
                onClick={evidence ? () => onOpen(evidence) : undefined}
              >
                <td className="whitespace-nowrap py-1 pr-2 font-mono">
                  <RankCell candidate={candidate} />
                </td>
                <td className="min-w-[10rem] max-w-[16rem] py-1 pr-2">
                  {evidence ? (
                    <button
                      type="button"
                      className={`block max-w-full truncate text-left font-medium text-foreground hover:underline ${focusRing}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        onOpen(evidence);
                      }}
                      title={`Open “${candidate.document_title}” at this passage`}
                    >
                      {candidate.document_title || "Untitled document"}
                    </button>
                  ) : (
                    <span className="block truncate" title="The document has been deleted">
                      {candidate.document_title || "Deleted document"} <span className="text-[11px]">(deleted)</span>
                    </span>
                  )}
                  <span className="mt-0.5 line-clamp-2 block text-[11px] text-muted-foreground">{snippet(candidate.text)}</span>
                </td>
                <td className="py-1 pr-2">{pageLabel(candidate)}</td>
                {columns.map((column) => (
                  <td key={column.key} className="py-1 pr-2 font-mono">
                    {formatCandidateScore(candidate[column.key])}
                  </td>
                ))}
                <td className="py-1 pr-2 font-mono">
                  {candidate.selected_for_context ? (
                    <>
                      <span aria-hidden="true">✓ </span>[{candidate.citation_id}]
                      <span className="sr-only"> given to the model</span>
                    </>
                  ) : (
                    <>
                      <span aria-hidden="true">—</span>
                      <span className="sr-only">not given to the model</span>
                    </>
                  )}
                </td>
                <td className="py-1">
                  {candidate.cited ? (
                    <span className="font-medium text-primary">Yes</span>
                  ) : (
                    <span>No</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

export default CandidateTable;
