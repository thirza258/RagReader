import React, { useContext, useMemo } from "react";
import Markdown, { type Components, type Options } from "react-markdown";
import { focusRing } from "../../../components/ui/classes";
import { CitationContext } from "../lib/citationContext";
import { CITATION_IDS_PROPERTY, describeSource, parseCitationIds, remarkCitationMarkers } from "../lib/citations";
import type { Evidence } from "../types";

type CitationElementProps = React.ComponentPropsWithoutRef<"cite"> & { node?: { properties?: Record<string, unknown> } };

/** Renders one `[1]` / `[1, 2]` marker as one button per source. */
function CitationMarker({ node, children }: CitationElementProps) {
  const context = useContext(CitationContext);
  const ids = parseCitationIds(node?.properties?.[CITATION_IDS_PROPERTY]);
  if (!context || ids.length === 0) return <>{children}</>;
  return (
    <>
      {ids.map((id) => {
        const source = context.sources.get(id);
        return (
          <button
            key={id}
            type="button"
            disabled={!source}
            onClick={() => source && context.onOpen(source)}
            aria-label={source ? `Source ${id}: ${describeSource(source)}. Open in the reader.` : `Source ${id}`}
            title={source ? describeSource(source) : undefined}
            className={`mx-[1px] inline-flex items-baseline px-0.5 align-baseline font-sans text-[0.8em] font-medium text-primary underline decoration-primary/30 underline-offset-2 transition-colors hover:bg-primary/10 hover:decoration-primary ${focusRing}`}
          >
            [{id}]
          </button>
        );
      })}
    </>
  );
}

function ExternalLink({ href, children }: React.ComponentPropsWithoutRef<"a">) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="link">
      {children}
    </a>
  );
}

const COMPONENTS: Components = {
  cite: CitationMarker as Components["cite"],
  a: ExternalLink as Components["a"],
};

interface AnswerMarkdownProps {
  content: string;
  citations: readonly Evidence[];
  onOpenSource: (source: Evidence) => void;
}

/**
 * An answer's markdown with its `[n]` markers turned into buttons that open
 * the cited passage. Markers in code, links or out of range stay as text.
 */
const AnswerMarkdown: React.FC<AnswerMarkdownProps> = ({ content, citations, onOpenSource }) => {
  const validIds = useMemo(() => new Set(citations.map((source) => source.citation_id)), [citations]);
  const plugins = useMemo<NonNullable<Options["remarkPlugins"]>>(() => [[remarkCitationMarkers, { validIds }]], [validIds]);
  const context = useMemo(
    () => ({ sources: new Map(citations.map((source) => [source.citation_id, source] as const)), onOpen: onOpenSource }),
    [citations, onOpenSource],
  );
  return (
    <CitationContext.Provider value={context}>
      <div className="answer-markdown">
        <Markdown remarkPlugins={plugins} components={COMPONENTS}>
          {content}
        </Markdown>
      </div>
    </CitationContext.Provider>
  );
};

export default AnswerMarkdown;
