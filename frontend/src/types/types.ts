import type { AnalysisRunState } from "../components/DeepSidebar";
import type { DeepAnalysisConfig } from "../interface";

export type UserRole = "me" | "bot";

export type EvalScore = {
  mrr5?: number;
  precision3?: number;
  recall3?: number;
};

export type Message = {
  user: UserRole;
  text: string;
  conversationId?: string;
  documentId?: string;
};

export type EmbeddingStatus = "embedded" | "pending" | "failed";

export type SubmitPayload =
  | { type: "file"; file: File }
  | { type: "url"; url: string }
  | { type: "text"; text: string };

export interface DocStep {
  id: number;
  title: string;
  description: React.ReactNode;
  icon: React.ReactNode;
  imagePath?: string;
  imageAlt: string;
  imagePlaceholderText: string;
}

/** A "Run Deep Analysis" press. `nonce` makes repeat runs distinguishable. */
export type AnalysisRequest = {
  config: DeepAnalysisConfig;
  nonce: number;
};

export type DeepResultContextType = {
  setIds: (ids: { conversationId: string; documentId: string }) => void;
  /** Set by the sidebar; null until the user runs an analysis themselves. */
  analysisRequest: AnalysisRequest | null;
  /** Incremented each time the user presses Stop. */
  stopSignal: number;
  setRunState: (state: AnalysisRunState) => void;
};

export type ErrorState = {
  error: string;
  status: number;
  message: string;
};

export type JobStatus = "PENDING" | "PROCESSING" | "READY" | "FAILED";

export type ChatbotContextType = {
  username: string | null;
  documentId: string | null;
  setContext: (context: { username: string; documentId: string }) => void;
};