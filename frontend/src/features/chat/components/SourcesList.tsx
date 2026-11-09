import React from "react";
import { focusRing } from "../../../components/ui/classes";
import { formatScore } from "../lib/retrievalSummary";
import { orderSources } from "../lib/citations";
import type { Evidence } from "../types";

function snippet(text: string, limit = 220): string {
  const flat = (text || "").replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit).trimEnd()}…` : flat;
}

function pageLabel(source: Evidence): string | null {
  if (source.page_number == null) return null;
  return source.page_end != null && source.page_end !== source.page_number ? `pp. ${source.page_number}–${source.page_end}` : `p. ${source.page_number}`;
}

function SourceItem({ source, onOpen }: { source: Evidence; onOpen: (source: Evidence) => void }) {
  const page = pageLabel(source);
  const score = formatScore(source.retrieval_score);
  return (
    <li>
      <button
        type="button"
        onClick={() => onOpen(source)}
        className={`group block w-full border-l-2 py-1.5 pl-2.5 pr-1 text-left transition-colors hover:bg-accent ${
          source.cited ? "border-primary/60" : "border-border"
        } ${focusRing}`}
      >
        <span className="flex items-baseline gap-2 text-xs">
          <span className="font-mono font-medium text-primary">[{source.citation_id}]</span>
          <span className="min-w-0 flex-1 truncate font-medium text-foreground group-hover:underline">{source.document_title || "Untitled document"}</span>
          {page && <span className="shrink-0 text-muted-foreground">{page}</span>}
          {score && (
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground tabular" title="Retrieval score (cosine similarity)">
              {score}
            </span>
          )}
        </span>
        <span className="mt-0.5 line-clamp-2 block text-xs text-muted-foreground">“{snippet(source.text)}”</span>
        <span className="sr-only">Open this passage in the reader.</span>
      </button>
    </li>
  );
}

interface SourcesListProps {
  citations: readonly Evidence[];
  onOpen: (source: Evidence) => void;
  /** While streaming nothing is cited yet: list the context passages instead. */
  streaming?: boolean;
}

/** The sources under an answer (PRD §13): cited first, then the rest of the context. */
const SourcesList: React.FC<SourcesListProps> = ({ citations, onOpen, streaming = false }) => {
  if (citations.length === 0) return null;
  if (streaming) {
    return (
      <details className="mt-3 text-xs">
        <summary className={`cursor-pointer select-none text-muted-foreground hover:text-foreground ${focusRing}`}>
          Context passages ({citations.length})
        </summary>
        <ul className="mt-1.5 space-y-1">
          {[...citations]
            .sort((a, b) => a.citation_id - b.citation_id)
            .map((source) => (
              <SourceItem key={source.citation_id} source={source} onOpen={onOpen} />
            ))}
        </ul>
      </details>
    );
  }
  const { cited, uncited } = orderSources(citations);
  return (
    <div className="mt-3">
      <h4 className="font-sans text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Sources {cited.length > 0 ? `(${cited.length} cited)` : ""}
      </h4>
      {cited.length > 0 ? (
        <ul className="mt-1.5 space-y-1">
          {cited.map((source) => (
            <SourceItem key={source.citation_id} source={source} onOpen={onOpen} />
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">The answer does not cite any of the passages it was given.</p>
      )}
      {uncited.length > 0 && (
        <details className="mt-2 text-xs">
          <summary className={`cursor-pointer select-none text-muted-foreground hover:text-foreground ${focusRing}`}>
            Also given to the model, not cited ({uncited.length})
          </summary>
          <ul className="mt-1.5 space-y-1">
            {uncited.map((source) => (
              <SourceItem key={source.citation_id} source={source} onOpen={onOpen} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};

export default SourcesList;
