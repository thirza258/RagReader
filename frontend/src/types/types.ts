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

export type DeepResultContextType = {
  setIds: (ids: { conversationId: string; documentId: string }) => void;
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