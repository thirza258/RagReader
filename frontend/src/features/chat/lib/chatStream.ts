import type {
  ChatMessage,
  ChatStreamEvent,
  Evidence,
  MessageError,
  StreamStage,
  StreamStageStatus,
} from "../types/index.ts";

/**
 * The chat turn as the SSE stream builds it (PRD §16). Parsing and state
 * changes are pure so the stream's ordering rules are covered by tests; the
 * React hook only feeds events in and renders the result.
 */

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asMessage(value: unknown): ChatMessage | null {
  if (!isRecord(value) || typeof value.id !== "number" || typeof value.role !== "string") return null;
  return {
    ...(value as unknown as ChatMessage),
    content: typeof value.content === "string" ? value.content : "",
    citations: Array.isArray(value.citations) ? (value.citations as Evidence[]) : [],
  };
}

function asError(value: unknown): MessageError {
  if (isRecord(value)) {
    return {
      code: typeof value.code === "string" && value.code ? value.code : "stream_error",
      message: typeof value.message === "string" && value.message ? value.message : "The answer could not be generated.",
      retryable: typeof value.retryable === "boolean" ? value.retryable : true,
      stage: typeof value.stage === "string" ? value.stage : null,
    };
  }
  return { code: "stream_error", message: "The answer could not be generated.", retryable: true, stage: null };
}

const STAGE_STATUSES: readonly StreamStageStatus[] = ["running", "completed", "skipped", "failed"];

/** Maps one raw SSE frame to a typed event; unknown or malformed frames give null. */
export function parseChatStreamEvent(frame: { event: string; data: string }): ChatStreamEvent | null {
  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    return null;
  }
  if (!isRecord(payload)) return null;
  switch (frame.event) {
    case "message.created":
      return {
        type: "message.created",
        userMessage: asMessage(payload.user_message),
        assistantMessage: asMessage(payload.assistant_message),
      };
    case "stage": {
      if (typeof payload.id !== "string") return null;
      const status = STAGE_STATUSES.includes(payload.status as StreamStageStatus) ? (payload.status as StreamStageStatus) : "running";
      return {
        type: "stage",
        stage: {
          id: payload.id,
          status,
          detail: typeof payload.detail === "string" ? payload.detail : "",
          duration_ms: asNumber(payload.duration_ms),
        },
      };
    }
    case "retrieval":
      return {
        type: "retrieval",
        candidateCount: asNumber(payload.candidate_count),
        contextCount: asNumber(payload.context_count),
        citations: Array.isArray(payload.citations) ? (payload.citations as Evidence[]) : [],
      };
    case "token":
      return typeof payload.delta === "string" ? { type: "token", delta: payload.delta } : null;
    case "message.completed": {
      const message = asMessage(payload.message);
      return message ? { type: "message.completed", message } : null;
    }
    case "error":
      return { type: "error", error: asError(payload.error), message: asMessage(payload.message) };
    default:
      return null;
  }
}

export type TurnPhase = "connecting" | "streaming" | "completed" | "failed" | "interrupted";

export interface StreamingTurn {
  question: string;
  phase: TurnPhase;
  userMessage: ChatMessage | null;
  assistantMessage: ChatMessage | null;
  stages: StreamStage[];
  candidateCount: number | null;
  contextCount: number | null;
  citations: Evidence[];
  content: string;
  error: MessageError | null;
}

export function startTurn(question: string): StreamingTurn {
  return {
    question,
    phase: "connecting",
    userMessage: null,
    assistantMessage: null,
    stages: [],
    candidateCount: null,
    contextCount: null,
    citations: [],
    content: "",
    error: null,
  };
}

export function isTurnFinished(turn: StreamingTurn): boolean {
  return turn.phase === "completed" || turn.phase === "failed" || turn.phase === "interrupted";
}

export function applyChatStreamEvent(turn: StreamingTurn, event: ChatStreamEvent): StreamingTurn {
  // The stream ends after `message.completed` or `error`; ignore stragglers.
  if (turn.phase === "completed" || turn.phase === "failed") return turn;
  switch (event.type) {
    case "message.created":
      return {
        ...turn,
        phase: "streaming",
        userMessage: event.userMessage ?? turn.userMessage,
        assistantMessage: event.assistantMessage ?? turn.assistantMessage,
      };
    case "stage": {
      const index = turn.stages.findIndex((stage) => stage.id === event.stage.id);
      const stages = index === -1 ? [...turn.stages, event.stage] : turn.stages.map((stage, i) => (i === index ? event.stage : stage));
      return { ...turn, phase: "streaming", stages };
    }
    case "retrieval":
      return {
        ...turn,
        phase: "streaming",
        candidateCount: event.candidateCount,
        contextCount: event.contextCount,
        citations: event.citations,
      };
    case "token":
      return { ...turn, phase: "streaming", content: turn.content + event.delta };
    case "message.completed":
      return {
        ...turn,
        phase: "completed",
        assistantMessage: event.message,
        content: event.message.content,
        citations: event.message.citations.length > 0 ? event.message.citations : turn.citations,
        error: null,
      };
    case "error":
      return {
        ...turn,
        phase: "failed",
        assistantMessage: event.message ?? turn.assistantMessage,
        content: event.message?.content || turn.content,
        error: event.error,
      };
    default:
      return turn;
  }
}

/** The connection closed (or failed) before `message.completed`/`error`. */
export function interruptTurn(turn: StreamingTurn, error: MessageError): StreamingTurn {
  if (turn.phase === "completed" || turn.phase === "failed") return turn;
  // Nothing was persisted yet when no `message.created` arrived, so the
  // question can simply be sent again; otherwise the server is still
  // producing the answer and the thread should re-read it.
  return { ...turn, phase: turn.userMessage ? "interrupted" : "failed", error };
}

export type ProgressState = "done" | "active" | "skipped" | "failed";

export interface ProgressLine {
  key: string;
  state: ProgressState;
  text: string;
}

const RUNNING_TEXT: Record<string, string> = {
  rewrite: "Rewriting the question for search…",
  retrieve: "Searching documents…",
  generate: "Generating answer…",
};

const DONE_TEXT: Record<string, string> = {
  rewrite: "Question rewritten for search",
  retrieve: "Documents searched",
  generate: "Answer generated",
};

const SKIPPED_TEXT: Record<string, string> = {
  rewrite: "Searched with the question as asked",
};

const FAILED_TEXT: Record<string, string> = {
  rewrite: "Query rewrite failed",
  retrieve: "Search failed",
  generate: "Answer generation failed",
};

function plural(count: number, word: string): string {
  return `${count.toLocaleString("en-US")} ${word}${count === 1 ? "" : "s"}`;
}

/**
 * The live status lines under a streaming answer, e.g.
 * "✓ Retrieved 20 candidates", "✓ Selected 5 passages", "● Generating answer…".
 */
export function progressLines(turn: StreamingTurn): ProgressLine[] {
  const lines: ProgressLine[] = [];
  if (turn.phase === "connecting" && turn.stages.length === 0) {
    return [{ key: "connecting", state: "active", text: "Sending question…" }];
  }
  for (const stage of turn.stages) {
    if (stage.id === "generate" && turn.contextCount != null) {
      lines.push({ key: "context", state: "done", text: `Selected ${plural(turn.contextCount, "passage")}` });
    }
    if (stage.status === "running") {
      lines.push({ key: stage.id, state: "active", text: RUNNING_TEXT[stage.id] ?? (stage.detail || `${stage.id}…`) });
    } else if (stage.status === "completed") {
      let text = stage.detail || DONE_TEXT[stage.id] || stage.id;
      if (!stage.detail && stage.id === "retrieve" && turn.candidateCount != null) {
        text = `Retrieved ${plural(turn.candidateCount, "candidate")}`;
      }
      lines.push({ key: stage.id, state: "done", text });
    } else if (stage.status === "skipped") {
      lines.push({ key: stage.id, state: "skipped", text: stage.detail || SKIPPED_TEXT[stage.id] || `${stage.id} skipped` });
    } else {
      lines.push({ key: stage.id, state: "failed", text: stage.detail || FAILED_TEXT[stage.id] || `${stage.id} failed` });
    }
  }
  const hasGenerate = turn.stages.some((stage) => stage.id === "generate");
  if (!hasGenerate && turn.contextCount != null) {
    lines.push({ key: "context", state: "done", text: `Selected ${plural(turn.contextCount, "passage")}` });
  }
  return lines;
}
