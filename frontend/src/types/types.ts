export type UserRole = "me" | "bot";

export type EvalScore = {
  mrr5?: number;
  precision3?: number;
  recall3?: number;
};

export type Message = {
  user: UserRole;
  text: string;
  evalScore?: EvalScore;
};

export type ChatResponse = {
  status: number;
  message: string;
  data: string;
};

export type EmbeddingStatus = "embedded" | "pending" | "failed";