import type { AnalysisProgressEvent, AnalysisProgressMessage } from "../interface";
import { variantKey } from "./analysisFlow.ts";

export interface LiveVariantProgress {
  attemptId: string;
  retiredAttempts: string[];
  sequence: number;
  interrupted: boolean;
  stages: Record<string, AnalysisProgressEvent>;
  modules: Record<string, AnalysisProgressEvent>;
  metrics: Record<string, AnalysisProgressEvent>;
  queries: string[];
  route?: string;
  activity: AnalysisProgressEvent;
}
export type LiveAnalysisProgress = Record<string, LiveVariantProgress>;

export function isAnalysisProgressMessage(value: unknown): value is AnalysisProgressMessage {
  if (!value || typeof value !== "object") return false;
  const message = value as Partial<AnalysisProgressMessage>;
  const event = message.event;
  return message.status === "STAGE_PROGRESS"
    && [message.batch_id, message.method, message.aiModel, message.attempt_id].every((value) => typeof value === "string" && value.length > 0)
    && Number.isSafeInteger(message.sequence) && (message.sequence ?? 0) > 0
    && !!event && ["stage", "module", "metric", "route", "activity"].includes(event.kind)
    && typeof event.id === "string" && typeof event.detail === "string"
    && ["running", "completed", "skipped", "fallback", "unavailable", "failed"].includes(event.status)
    && (event.kind !== "stage" || ["question", "search", "evidence", "answer", "evaluate"].includes(event.id))
    && (event.queries === undefined || (Array.isArray(event.queries) && event.queries.every((query) => typeof query === "string")))
    && (event.score == null || (typeof event.score === "number" && Number.isFinite(event.score) && event.score >= 0 && event.score <= 1));
}

/** Socket epochs protect connections; batch/attempt/sequence protect events.
 * An incomplete attempt never contributes steps to a later retry. */
export function updateLiveProgress(previous: LiveAnalysisProgress, message: AnalysisProgressMessage, batchId: string): LiveAnalysisProgress {
  if (!isAnalysisProgressMessage(message) || message.batch_id !== batchId) return previous;
  const key = variantKey(message.method, message.aiModel);
  const old = previous[key];
  const sameAttempt = old?.attemptId === message.attempt_id;
  if (sameAttempt && message.sequence <= old.sequence) return previous;
  if (old && !sameAttempt && (message.sequence !== 1 || old.retiredAttempts.includes(message.attempt_id))) return previous;
  const current: LiveVariantProgress = sameAttempt ? old : {
    attemptId: message.attempt_id, retiredAttempts: old ? [...old.retiredAttempts, old.attemptId] : [],
    sequence: 0, interrupted: false, stages: {}, modules: {}, metrics: {}, queries: [], activity: message.event,
  };
  const event = message.event;
  const next = { ...current, sequence: message.sequence, interrupted: false, activity: event };
  if (event.kind === "stage") next.stages = { ...current.stages, [event.id]: event };
  if (event.kind === "module") next.modules = { ...current.modules, [event.id]: event };
  if (event.kind === "metric") next.metrics = { ...current.metrics, [event.id]: event };
  if (event.kind === "route") next.route = event.id;
  // Module questions may be proposed but never retrieved; list actual searches.
  if (event.kind === "activity" && event.queries) next.queries = [...new Set([...current.queries, ...event.queries])];
  return { ...previous, [key]: next };
}

export function interruptLiveProgress(previous: LiveAnalysisProgress): LiveAnalysisProgress {
  return Object.fromEntries(Object.entries(previous).map(([key, value]) => [key, { ...value, interrupted: true }]));
}
