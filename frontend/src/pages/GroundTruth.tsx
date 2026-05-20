import React, { useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import {
  ArrowLeft,
  Save,
  CheckCircle2,
  AlertCircle,
  ChevronDown,
  ChevronUp,
  ArrowRight,
} from "lucide-react";
import service from "../services/service";

import GroundTruthChunk from "../components/GroundTruthChunk";

import GroundTruthResponse from "../components/GroundTruthResponse";

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

const GroundTruthSelector: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const params = new URLSearchParams(location.search);

  // Extract IDs
  const { conversationId, documentId } = useParams<{
    conversationId?: string;
    documentId?: string;
  }>();

  // --- Form State ---
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
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

  // Validation constraint: BOTH are required
  const isFormValid = selectedIds.size > 0 && groundTruth.trim().length > 0;

  const handleSubmit = async () => {
  if (!isFormValid || !conversationId) return;

  setIsSubmitting(true);
  setSubmitError("");

  try {
    const [chunkResponse, textResponse] = await Promise.all([
      service.CreateGroundTruthChunk(conversationId, Array.from(selectedIds)),
      service.CreateGroundTruthResponse(conversationId, groundTruth),
    ]);

    if (textResponse.status !== 200) {
      throw new Error(textResponse.message || "Failed to submit response.");
    }

    // ✅ Only called after both ground truth calls succeed
    const { batch_id, query, document_id } = await service.startDeepAnalysis(conversationId);

    // ✅ Persist so DeepResult can recover on refresh
    localStorage.setItem(`batch_id_${conversationId}`, batch_id);
    localStorage.setItem("document_id", document_id);
    localStorage.setItem("conversation_id", conversationId);

    // ✅ Pass analysis data to DeepResult via route state
    navigate(`/deep-result/${conversationId}`, {
      state: { batch_id, query, document_id },
    });
  } catch (error) {
    console.error("Submission error:", error);
    setSubmitError("Failed to save the ground truth. Please try again.");
  } finally {
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
      {/* Sticky Header */}
      

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

        {/* Panel 1: Chunk Selection */}
        <ExpandablePanel
          title="Step 1: Select Ground Truth Chunks"
          isOpen={openPanels.chunks}
          onToggle={() => togglePanel("chunks")}
          statusIndicator={
            selectedIds.size > 0 ? (
              <span className="bg-primary/10 text-primary text-xs px-2 py-1 rounded-full flex items-center gap-1 font-medium">
                <CheckCircle2 size={12} /> {selectedIds.size} Selected
              </span>
            ) : (
              <span className="bg-muted text-muted-foreground text-xs px-2 py-1 rounded-full font-medium">
                Required
              </span>
            )
          }
        >
          <GroundTruthChunk
            documentId={documentId!}
            selectedIds={selectedIds}
            toggleSelection={toggleSelection}
          />
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
            <AlertCircle size={16} /> Both chunk selection and text response are
            required to save.
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
              className="px-4 py-2 rounded-md border border-border text-sm hover:bg-muted transition-colors flex items-center gap-2"
            >
              Start Analysis
              <ArrowRight size={16} />
            </button>
          </div>
        </section>
      </main>
    </div>
  );
};

export default GroundTruthSelector;
