import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, ArrowRight, ChevronDown, ChevronUp } from "lucide-react";
import service from "../services/service";

import GroundTruthChunk from "../components/GroundTruthChunk";
import CandidatePool from "../components/CandidatePool";
import GroundTruthResponse from "../components/GroundTruthResponse";
import { CandidatePoolResponse, GroundTruthMode } from "../interface";

const POOL_TOP_N = 10;

const cn = (...classes: (string | undefined | boolean)[]) =>
  classes.filter(Boolean).join(" ");

const ExpandablePanel: React.FC<{
  title: string;
  isOpen: boolean;
  onToggle: () => void;
  statusIndicator?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, isOpen, onToggle, statusIndicator, children }) => (
  <div className="mb-4 border border-border">
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={isOpen}
      className="flex w-full items-center justify-between gap-4 px-5 py-4 text-left transition-colors hover:bg-accent"
    >
      <span className="flex items-baseline gap-3">
        <span className="font-serif text-lg font-semibold">{title}</span>
        {statusIndicator}
      </span>
      {isOpen ? (
        <ChevronUp size={18} className="shrink-0 text-muted-foreground" />
      ) : (
        <ChevronDown size={18} className="shrink-0 text-muted-foreground" />
      )}
    </button>
    {isOpen && <div className="border-t border-border p-5">{children}</div>}
  </div>
);

const MODE_OPTIONS: {
  id: GroundTruthMode;
  label: string;
  blurb: string;
}[] = [
  {
    id: "manual",
    label: "Manual selection",
    blurb: "You decide which chunks are relevant. Precise, but it is your judgement being measured.",
  },
  {
    id: "pooled",
    label: "Candidate pooling (RRF)",
    blurb: "Every retrieval method votes; Reciprocal Rank Fusion merges the rankings. No hand-labelling.",
  },
];

const GroundTruthSelector: React.FC = () => {
  const navigate = useNavigate();

  // Extract IDs
  const { conversationId, documentId } = useParams<{
    conversationId?: string;
    documentId?: string;
  }>();

  // --- Form State ---
  const [mode, setMode] = useState<GroundTruthMode>("manual");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [pool, setPool] = useState<CandidatePoolResponse | null>(null);
  const [groundTruth, setGroundTruth] = useState<string>("");

  // --- UI State ---
  const [openPanels, setOpenPanels] = useState({
    chunks: true,
    response: true,
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const togglePanel = (panel: "chunks" | "response") => {
    setOpenPanels((prev) => ({ ...prev, [panel]: !prev[panel] }));
  };

  const toggleSelection = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelectedIds(next);
  };

  // Chunks come from whichever mode is active; the written response is always
  // required — pooling has no equivalent for the answer.
  const hasChunks = mode === "manual" ? selectedIds.size > 0 : (pool?.chunks.length ?? 0) > 0;
  const isFormValid = hasChunks && groundTruth.trim().length > 0;

  const handleSubmit = async () => {
    if (!isFormValid || !conversationId) return;

    setIsSubmitting(true);
    setSubmitError("");

    try {
      // In pooled mode the chunks were already written server-side by the
      // pooling run, so only the response needs saving.
      const requests = [service.CreateGroundTruthResponse(conversationId, groundTruth)];
      if (mode === "manual") {
        requests.push(
          service.CreateGroundTruthChunk(conversationId, Array.from(selectedIds))
        );
      }
      await Promise.all(requests);

      const { batch_id, query, document_id, expected_count } =
        await service.startDeepAnalysis(conversationId, {
          ground_truth_mode: mode,
          pool_top_n: POOL_TOP_N,
        });

      localStorage.setItem(`batch_id_${conversationId}`, batch_id);
      localStorage.setItem("document_id", String(document_id));
      localStorage.setItem("conversation_id", conversationId);

      navigate(`/deep-result/${conversationId}`, {
        state: { batch_id, query, document_id, expected_count },
      });
    } catch (error) {
      console.error("Submission error:", error);
      setSubmitError("Failed to save the ground truth. Please try again.");
      setIsSubmitting(false);
    }
  };

  if (!conversationId || !documentId) {
    return (
      <div className="p-10 text-center text-sm text-destructive">
        Missing document ID or conversation ID.
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background pb-20 pt-16 text-foreground">
      <main className="container mx-auto px-4 py-8 max-w-5xl">
        {submitError && (
          <div className="mb-6 border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
            {submitError}
          </div>
        )}

        <section className="mb-10 border-b border-border pb-8">
          <h1 className="text-3xl font-semibold">Ground truth</h1>
          <p className="prose-note measure mt-3">
            Set the expected answer and the chunks that count as relevant. Without
            them the analysis has nothing to score against.
          </p>
          <dl className="mt-6 flex flex-wrap gap-x-8 gap-y-1 font-mono text-xs text-muted-foreground">
            <div className="flex gap-2">
              <dt>Conversation</dt>
              <dd className="text-foreground">{conversationId}</dd>
            </div>
            <div className="flex gap-2">
              <dt>Document</dt>
              <dd className="text-foreground">{documentId}</dd>
            </div>
          </dl>
        </section>

        {/* Mode switch: who decides what counts as relevant */}
        <section className="mb-6">
          <h2 className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            How should relevant chunks be decided?
          </h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {MODE_OPTIONS.map((option) => (
              <button
                key={option.id}
                onClick={() => setMode(option.id)}
                aria-pressed={mode === option.id}
                className={cn(
                  "border p-4 text-left transition-colors",
                  mode === option.id
                    ? "border-foreground/40 bg-accent"
                    : "border-border hover:bg-accent"
                )}
              >
                <p className="font-medium">{option.label}</p>
                <p className="mt-1 text-sm text-muted-foreground">{option.blurb}</p>
              </button>
            ))}
          </div>
        </section>

        {/* Panel 1: Chunk selection or candidate pooling */}
        <ExpandablePanel
          title={
            mode === "manual"
              ? "1. Select ground-truth chunks"
              : "1. Build the candidate pool"
          }
          isOpen={openPanels.chunks}
          onToggle={() => togglePanel("chunks")}
          statusIndicator={
            hasChunks ? (
              <span className="text-xs text-muted-foreground">
                {mode === "manual"
                  ? `${selectedIds.size} selected`
                  : `${pool?.chunks.length} pooled`}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">Required</span>
            )
          }
        >
          {mode === "manual" ? (
            <GroundTruthChunk
              documentId={documentId!}
              selectedIds={selectedIds}
              toggleSelection={toggleSelection}
            />
          ) : (
            <CandidatePool
              conversationId={conversationId}
              poolTopN={POOL_TOP_N}
              pool={pool}
              onPooled={setPool}
            />
          )}
        </ExpandablePanel>

        {/* Panel 2: Response Input */}
        <ExpandablePanel
          title="2. Write the expected answer"
          isOpen={openPanels.response}
          onToggle={() => togglePanel("response")}
          statusIndicator={
            groundTruth.trim().length > 0 ? (
              <span className="text-xs text-muted-foreground">Written</span>
            ) : (
              <span className="text-xs text-muted-foreground">Required</span>
            )
          }
        >
          <GroundTruthResponse
            conversationId={conversationId}
            groundTruth={groundTruth}
            setGroundTruth={setGroundTruth}
          />
        </ExpandablePanel>

        {/* Bottom validation hint */}
        {!isFormValid && (
          <p className="mt-6 text-center text-sm text-muted-foreground">
            {mode === "manual"
              ? "Both chunk selection and text response are required to save."
              : "Run candidate pooling and write the expected response to continue."}
          </p>
        )}

        <section className="mt-10 flex items-center justify-between gap-4 border-t border-border pt-8">
          <button
            onClick={() => navigate(-1)}
            className="flex items-center gap-2 border border-input px-4 py-2.5 text-sm transition-colors hover:bg-accent"
          >
            <ArrowLeft size={15} />
            Back to chat
          </button>

          <button
            onClick={handleSubmit}
            disabled={!isFormValid || isSubmitting}
            className={cn(
              "flex items-center gap-2 border px-4 py-2.5 text-sm font-medium transition-colors",
              !isFormValid || isSubmitting
                ? "cursor-not-allowed border-border text-muted-foreground"
                : "border-primary bg-primary text-primary-foreground hover:bg-primary-hover"
            )}
          >
            {isSubmitting ? "Starting…" : "Start analysis"}
            <ArrowRight size={15} />
          </button>
        </section>
      </main>
    </div>
  );
};

export default GroundTruthSelector;
