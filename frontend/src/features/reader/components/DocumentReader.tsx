import React, { Fragment, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonIcon, buttonOutline, buttonQuiet, focusRing, inputSmall } from "../../../components/ui/classes";
import IngestionChecklist from "../../documents/components/IngestionChecklist";
import { documentMetaLine } from "../../documents/lib/format";
import { stageName } from "../../documents/lib/ingestionStages";
import type { DocumentText, WorkspaceDocument } from "../../documents/types";
import type { Evidence } from "../../chat/types";
import { describeSource } from "../../chat/lib/citations";
import { useDocumentText } from "../hooks/useDocumentText";
import { buildReaderBlocks, findMatches, locateEvidenceRange, pageAtOffset, resolvePages, type ReaderSegment } from "../lib/segments";
import PdfOriginalView from "./PdfOriginalView";

interface DocumentReaderProps {
  documentId: number | null;
  /** The library row for `documentId`, once the list has loaded. */
  document: WorkspaceDocument | null;
  documentsLoaded: boolean;
  /** Evidence to highlight, when the reader was opened from a citation. */
  evidence: Evidence | null;
  /** Changes on every citation click, so clicking the same one scrolls again. */
  focusRequest: number;
  onClearEvidence: () => void;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

function pageAnchorId(documentId: number, page: number): string {
  return `reader-${documentId}-page-${page}`;
}

/**
 * Scrolls `container` (only) so `element` is in view. `scrollIntoView` would
 * also scroll every clipped ancestor, shifting the whole workspace layout.
 */
function scrollWithin(container: HTMLElement | null, element: Element | null, align: "center" | "start" = "center") {
  if (!container || !element) return;
  const box = container.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  const offset = rect.top - box.top + container.scrollTop;
  const top = align === "center" ? offset - container.clientHeight / 2 + rect.height / 2 : offset - 8;
  container.scrollTo({ top: Math.max(0, top), behavior: prefersReducedMotion() ? "auto" : "smooth" });
}

/**
 * The reader pane (PRD §12): the document's extracted text with page
 * dividers, the cited passage highlighted and scrolled into view, search with
 * next/previous, page jump, and — for PDFs — the original file.
 */
const DocumentReader: React.FC<DocumentReaderProps> = ({ documentId, document, documentsLoaded, evidence, focusRequest, onClearEvidence }) => {
  if (documentId == null) {
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <p className="measure text-center text-sm text-muted-foreground">
          Open a document from the library to read it here, or click a citation such as <span className="font-mono">[1]</span> in an answer to
          jump to the passage it came from.
        </p>
      </div>
    );
  }
  if (!document) {
    return (
      <p role="status" className="p-4 text-sm text-muted-foreground">
        {documentsLoaded ? "This document is no longer in the workspace." : "Loading document…"}
      </p>
    );
  }
  return <ReaderForDocument key={document.id} document={document} evidence={evidence?.document_id === document.id ? evidence : null} focusRequest={focusRequest} onClearEvidence={onClearEvidence} />;
};

interface ReaderForDocumentProps {
  document: WorkspaceDocument;
  evidence: Evidence | null;
  focusRequest: number;
  onClearEvidence: () => void;
}

const ReaderForDocument: React.FC<ReaderForDocumentProps> = ({ document, evidence, focusRequest, onClearEvidence }) => {
  const ready = document.status === "READY";
  // Failed documents may still have text (e.g. indexing failed after cleaning).
  const wantText = ready || document.status === "FAILED";
  const { text, error, loading, retry } = useDocumentText(document.id, wantText);
  const canShowPdf = document.has_original_file && document.source_type === "pdf";
  const [view, setView] = useState<"text" | "pdf">("text");
  const [pdfPage, setPdfPage] = useState<number>(evidence?.page_number ?? 1);
  const [lastEvidencePage, setLastEvidencePage] = useState<number | null>(evidence?.page_number ?? null);

  // A new citation for this document moves the PDF view to its page.
  const evidencePage = evidence?.page_number ?? null;
  if (evidencePage !== lastEvidencePage) {
    setLastEvidencePage(evidencePage);
    if (evidencePage != null) setPdfPage(evidencePage);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-2">
        <div className="min-w-0">
          <h2 className="truncate font-serif text-base font-semibold" title={document.title}>
            {document.title || "Untitled document"}
          </h2>
          <p className="text-xs text-muted-foreground">{documentMetaLine(document)}</p>
        </div>
        {canShowPdf && (
          <div role="group" aria-label="Reader view" className="flex border border-border text-xs">
            {(["text", "pdf"] as const).map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={view === option}
                onClick={() => setView(option)}
                className={`px-2.5 py-1 transition-colors ${focusRing} ${view === option ? "bg-foreground text-background" : "text-muted-foreground hover:bg-accent hover:text-foreground"}`}
              >
                {option === "text" ? "Text" : "Original PDF"}
              </button>
            ))}
          </div>
        )}
      </div>

      {evidence && (
        <div className="flex items-start justify-between gap-2 border-b border-border bg-primary/5 px-4 py-2 text-xs" role="status">
          <p className="min-w-0">
            <span className="font-medium text-primary">Evidence [{evidence.citation_id}]</span> · {describeSource(evidence)}
          </p>
          <button type="button" className={buttonQuiet} onClick={onClearEvidence}>
            Clear highlight
          </button>
        </div>
      )}

      {!wantText && (
        <div className="p-4">
          <p className="text-sm text-muted-foreground">The text appears here once the document is ready.</p>
          <IngestionChecklist document={document} />
        </div>
      )}

      {wantText && view === "pdf" && canShowPdf && (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-border px-4 py-2">
            <PageJump pageCount={document.page_count} current={pdfPage} onJump={setPdfPage} idPrefix={`pdf-${document.id}`} />
          </div>
          <PdfOriginalView documentId={document.id} title={document.title} page={pdfPage} />
        </div>
      )}

      {wantText && view === "text" && (
        <>
          {loading && (
            <p role="status" className="p-4 text-sm text-muted-foreground">
              Loading text…
            </p>
          )}
          {error && (
            <div className="p-4">
              <ErrorNotice
                title={document.status === "FAILED" ? "This document failed to ingest" : "The text could not be loaded"}
                code={document.status === "FAILED" ? document.error?.code ?? error.code : error.code}
                message={document.status === "FAILED" ? document.error?.message ?? error.message : error.message}
                actions={
                  <button type="button" className={buttonOutline} onClick={retry}>
                    Try again
                  </button>
                }
              >
                {document.status === "FAILED" && document.error?.stage && <p className="mt-1 text-xs">Stage: {stageName(document.error.stage)}</p>}
              </ErrorNotice>
            </div>
          )}
          {text && (
            <TextView
              key={text.document_id}
              documentId={document.id}
              data={text}
              evidence={evidence}
              focusRequest={focusRequest}
              onShowPdfPage={
                canShowPdf
                  ? (page) => {
                      setPdfPage(page);
                      setView("pdf");
                    }
                  : null
              }
            />
          )}
        </>
      )}
    </div>
  );
};

interface PageJumpProps {
  pageCount: number | null;
  current: number;
  onJump: (page: number) => void;
  idPrefix: string;
}

function PageJump({ pageCount, current, onJump, idPrefix }: PageJumpProps) {
  const [value, setValue] = useState(String(current));
  const [shown, setShown] = useState(current);
  if (shown !== current) {
    setShown(current);
    setValue(String(current));
  }
  const max = pageCount && pageCount > 0 ? pageCount : undefined;
  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const page = Number(value);
    if (!Number.isInteger(page) || page < 1 || (max && page > max)) return;
    onJump(page);
  };
  return (
    <form onSubmit={submit} className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-xs">
      <label htmlFor={`${idPrefix}-page`} className="text-muted-foreground">
        Page
      </label>
      <input
        id={`${idPrefix}-page`}
        type="number"
        inputMode="numeric"
        min={1}
        max={max}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className={`${inputSmall} w-16 py-0.5 tabular`}
      />
      {max && <span className="text-muted-foreground tabular">of {max}</span>}
      <button type="submit" className={`${buttonOutline} px-2 py-0.5 text-xs`}>
        Go
      </button>
    </form>
  );
}

interface TextViewProps {
  documentId: number;
  data: DocumentText;
  evidence: Evidence | null;
  focusRequest: number;
  onShowPdfPage: ((page: number) => void) | null;
}

const MATCH_LIMIT = 1000;

function TextView({ documentId, data, evidence, focusRequest, onShowPdfPage }: TextViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState({ query: "", index: 0 });
  const deferredQuery = useDeferredValue(search.query);
  const fullText = data.text ?? "";

  const pages = useMemo(() => resolvePages(fullText, data.pages), [fullText, data.pages]);
  const { matches, truncated: tooManyMatches } = useMemo(() => findMatches(fullText, deferredQuery, MATCH_LIMIT), [fullText, deferredQuery]);
  const highlight = useMemo(() => locateEvidenceRange(fullText, evidence), [fullText, evidence]);
  const blocks = useMemo(
    () => buildReaderBlocks({ textLength: fullText.length, pages, highlight, matches }),
    [fullText.length, pages, highlight, matches],
  );
  const activeMatch = matches.length > 0 ? ((search.index % matches.length) + matches.length) % matches.length : -1;
  const evidencePage = evidence?.page_number ?? (highlight ? pageAtOffset(pages, highlight.start) : null);

  // Scroll to the evidence on every citation click (or to its page when the
  // passage itself could not be located).
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !evidence) return;
    const passage = container.querySelector("[data-evidence-start]");
    if (passage) scrollWithin(container, passage);
    else if (evidence.page_number != null) scrollWithin(container, window.document.getElementById(pageAnchorId(documentId, evidence.page_number)), "start");
  }, [evidence, focusRequest, highlight, documentId]);

  useEffect(() => {
    if (activeMatch < 0) return;
    scrollWithin(containerRef.current, containerRef.current?.querySelector("[data-match-active]") ?? null);
  }, [activeMatch, matches]);

  const step = (delta: number) => setSearch((current) => ({ ...current, index: current.index + delta }));

  const jumpToPage = (page: number) => {
    scrollWithin(containerRef.current, window.document.getElementById(pageAnchorId(documentId, page)), "start");
  };

  const renderSegment = (segment: ReaderSegment) => {
    const value = fullText.slice(segment.start, segment.end);
    if (!segment.highlight && segment.match === -1) return <Fragment key={segment.start}>{value}</Fragment>;
    const isActive = segment.match !== -1 && segment.match === activeMatch;
    // One background per mark: a search match shows over the evidence tint,
    // and the evidence keeps its underline either way.
    const background =
      segment.match !== -1
        ? isActive
          ? "bg-status-warning/40 outline outline-1 outline-status-warning"
          : "bg-status-warning/20"
        : "bg-primary/15";
    const classes = `text-foreground ${background} ${segment.highlight ? "underline decoration-primary/60 decoration-2 underline-offset-4" : ""}`;
    return (
      <mark
        key={segment.start}
        className={classes}
        data-evidence-start={segment.highlight && highlight && segment.start === highlight.start ? "" : undefined}
        data-match-active={isActive ? "" : undefined}
      >
        {value}
      </mark>
    );
  };

  const matchStatus = !deferredQuery.trim()
    ? ""
    : matches.length === 0
      ? "No matches"
      : `${activeMatch + 1} of ${matches.length}${tooManyMatches ? "+" : ""}`;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-border px-4 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <label htmlFor={`reader-search-${documentId}`} className="sr-only">
            Search in this document
          </label>
          <Search aria-hidden="true" className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <input
            id={`reader-search-${documentId}`}
            type="search"
            placeholder="Search in document"
            className={`${inputSmall} min-w-[8rem] flex-1 py-0.5`}
            value={search.query}
            onChange={(event) => setSearch({ query: event.target.value, index: 0 })}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                step(event.shiftKey ? -1 : 1);
              } else if (event.key === "Escape" && search.query) {
                event.preventDefault();
                setSearch({ query: "", index: 0 });
              }
            }}
          />
          <span className="min-w-[4.5rem] text-right text-xs text-muted-foreground tabular" aria-live="polite">
            {matchStatus}
          </span>
          <button type="button" className={buttonIcon} aria-label="Previous match" disabled={matches.length === 0} onClick={() => step(-1)}>
            <ChevronUp aria-hidden="true" className="h-4 w-4" />
          </button>
          <button type="button" className={buttonIcon} aria-label="Next match" disabled={matches.length === 0} onClick={() => step(1)}>
            <ChevronDown aria-hidden="true" className="h-4 w-4" />
          </button>
          {search.query && (
            <button type="button" className={buttonIcon} aria-label="Clear search" onClick={() => setSearch({ query: "", index: 0 })}>
              <X aria-hidden="true" className="h-4 w-4" />
            </button>
          )}
        </div>
        {pages.length > 0 && (
          <PageJump
            pageCount={pages.length}
            current={evidencePage ?? pages[0].number}
            onJump={(page) => {
              jumpToPage(page);
            }}
            idPrefix={`text-${documentId}`}
          />
        )}
        {onShowPdfPage && evidencePage != null && (
          <button type="button" className={buttonQuiet} onClick={() => onShowPdfPage(evidencePage)}>
            See page {evidencePage} in the PDF
          </button>
        )}
      </div>

      {data.truncated && (
        <p className="border-b border-border bg-muted px-4 py-1.5 text-xs text-muted-foreground">
          This document is long: the reader shows the first {fullText.length.toLocaleString("en-US")}
          {data.char_count ? ` of ${data.char_count.toLocaleString("en-US")}` : ""} characters.
        </p>
      )}
      {evidence && !highlight && (
        <p className="border-b border-border bg-muted px-4 py-1.5 text-xs text-muted-foreground">
          The cited passage could not be located in the text shown here{evidence.page_number != null ? `; showing page ${evidence.page_number}` : ""}.
          It reads: “{evidence.text.slice(0, 280)}
          {evidence.text.length > 280 ? "…" : ""}”
        </p>
      )}

      <div ref={containerRef} className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6" tabIndex={0} aria-label="Document text">
        {fullText.length === 0 && <p className="text-sm text-muted-foreground">This document has no extracted text.</p>}
        <div className="mx-auto max-w-[70ch]">
          {blocks.map((block) => (
            <section key={block.key} aria-label={block.page != null ? `Page ${block.page}` : undefined}>
              {block.page != null && (
                <div id={pageAnchorId(documentId, block.page)} className="flex scroll-mt-4 items-center gap-3 py-3 text-[11px] uppercase tracking-wide text-muted-foreground">
                  <span aria-hidden="true" className="h-px flex-1 bg-border" />
                  Page {block.page}
                  <span aria-hidden="true" className="h-px flex-1 bg-border" />
                </div>
              )}
              <div className="whitespace-pre-wrap break-words font-serif text-[0.98rem] leading-7 text-foreground/90">{block.segments.map(renderSegment)}</div>
            </section>
          ))}
        </div>
      </div>
    </>
  );
}

export default DocumentReader;
