import React, { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  ArrowLeft,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowRight,
  Hand,
  Layers,
} from "lucide-react";
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
  <div className="border border-border rounded-lg bg-card overflow-hidden shadow-sm mb-4 transition-all">
    <div
      onClick={onToggle}
      className="flex items-center justify-between p-4 cursor-pointer bg-muted/20 hover:bg-muted/40 transition-colors"
    >
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
        {statusIndicator}
      </div>
      {isOpen ? <ChevronUp size={20} /> : <ChevronDown size={20} />}
    </div>
    {isOpen && <div className="p-4 border-t border-border">{children}</div>}
  </div>
);

const MODE_OPTIONS: {
  id: GroundTruthMode;
  label: string;
  blurb: string;
  icon: React.ReactNode;
}[] = [
  {
    id: "manual",
    label: "Manual selection",
    blurb: "You decide which chunks are relevant. Precise, but it is your judgement being measured.",
    icon: <Hand size={16} />,
  },
  {
    id: "pooled",
    label: "Candidate pooling (RRF)",
    blurb: "Every retrieval method votes; Reciprocal Rank Fusion merges the rankings. No hand-labelling.",
    icon: <Layers size={16} />,
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
      <div className="p-10 text-center text-red-500 font-medium">
        Missing Document ID or Conversation ID.
      </div>
    );
  }

  return (
    <div className="min-h-screen pt-16 bg-background text-foreground font-sans selection:bg-primary selection:text-primary-foreground pb-20">
      <main className="container mx-auto px-4 py-8 max-w-5xl">
        {submitError && (
          <div className="mb-6 p-4 rounded-md bg-destructive/10 text-destructive border border-destructive/20 flex items-center gap-2">
            <AlertCircle size={18} />
            {submitError}
          </div>
        )}

        <section className="mb-10">
          <h1 className="text-2xl font-bold tracking-tight">Ground Truth Setup</h1>
          <p className="mt-2 text-muted-foreground">
            Provide expected answers and relevant document chunks to evaluate the RAG method.
          </p>
          <div className="mt-5">
            <p>Current Conversation ID : {conversationId}</p>
            <p>Current Document ID : {documentId}</p>
          </div>
        </section>

        {/* Mode switch: who decides what counts as relevant */}
        <section className="mb-6">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            How should relevant chunks be decided?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {MODE_OPTIONS.map((option) => (
              <button
                key={option.id}
                onClick={() => setMode(option.id)}
                className={cn(
                  "text-left rounded-lg border p-4 transition-all",
                  mode === option.id
                    ? "border-primary bg-primary/5 shadow-[0_0_0_1px_hsl(var(--primary))]"
                    : "border-border bg-card hover:border-muted-foreground/50"
                )}
              >
                <div className="flex items-center gap-2 mb-1.5 font-medium">
                  {option.icon}
                  {option.label}
                  {mode === option.id && (
                    <CheckCircle2 size={14} className="ml-auto text-primary" />
                  )}
                </div>
                <p className="text-sm text-muted-foreground">{option.blurb}</p>
              </button>
            ))}
          </div>
        </section>

        {/* Panel 1: Chunk selection or candidate pooling */}
        <ExpandablePanel
          title={
            mode === "manual"
              ? "Step 1: Select Ground Truth Chunks"
              : "Step 1: Build the Candidate Pool"
          }
          isOpen={openPanels.chunks}
          onToggle={() => togglePanel("chunks")}
          statusIndicator={
            hasChunks ? (
              <span className="bg-primary/10 text-primary text-xs px-2 py-1 rounded-full flex items-center gap-1 font-medium">
                <CheckCircle2 size={12} />{" "}
                {mode === "manual"
                  ? `${selectedIds.size} Selected`
                  : `${pool?.chunks.length} Pooled`}
              </span>
            ) : (
              <span className="bg-muted text-muted-foreground text-xs px-2 py-1 rounded-full font-medium">
                Required
              </span>
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
          title="Step 2: Provide Ground Truth Response"
          isOpen={openPanels.response}
          onToggle={() => togglePanel("response")}
          statusIndicator={
            groundTruth.trim().length > 0 ? (
              <span className="bg-primary/10 text-primary text-xs px-2 py-1 rounded-full flex items-center gap-1 font-medium">
                <CheckCircle2 size={12} /> Written
              </span>
            ) : (
              <span className="bg-muted text-muted-foreground text-xs px-2 py-1 rounded-full font-medium">
                Required
              </span>
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
          <p className="text-center mt-6 text-sm text-muted-foreground flex items-center justify-center gap-2">
            <AlertCircle size={16} />
            {mode === "manual"
              ? "Both chunk selection and text response are required to save."
              : "Run candidate pooling and write the expected response to continue."}
          </p>
        )}

        <section className="mt-10 flex justify-between items-center">
          <div>
            <button
              onClick={() => navigate(-1)}
              className="mt-10 px-4 py-2 rounded-md border border-border text-sm hover:bg-muted transition-colors flex items-center gap-2"
            >
              <ArrowLeft size={16} />
              Back to Chat
            </button>
          </div>

          <div>
            <button
              onClick={handleSubmit}
              disabled={!isFormValid || isSubmitting}
              className={cn(
                "px-4 py-2 rounded-md border border-border text-sm transition-colors flex items-center gap-2",
                !isFormValid || isSubmitting
                  ? "opacity-50 cursor-not-allowed"
                  : "hover:bg-muted"
              )}
            >
              {isSubmitting ? "Starting…" : "Start Analysis"}
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
      </main>
    </div>
  );
};

export default GroundTruthSelector;
