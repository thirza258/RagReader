import { Loader2, Microscope, RotateCcw } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline } from "../../../components/ui/classes";
import { isTurnFinished, type StreamingTurn } from "../lib/chatStream";
import { formatRetrievalSummary } from "../lib/retrievalSummary";
import { runIdOf } from "../../runs/lib/runMetrics";
import type { ChatMessage, Evidence, MessageError } from "../types";
import AnswerMarkdown from "./AnswerMarkdown";
import SourcesList from "./SourcesList";
import StreamProgress from "./StreamProgress";
import WhyThisAnswer from "./WhyThisAnswer";

export function UserBubble({ content, pending = false }: { content: string; pending?: boolean }) {
  return (
    <div className="flex justify-end">
      <div className={`max-w-[85%] whitespace-pre-wrap break-words border border-border bg-muted px-3 py-2 text-sm ${pending ? "opacity-80" : ""}`}>
        <span className="sr-only">You asked: </span>
        {content}
      </div>
    </div>
  );
}

function TurnError({ error, onRetry }: { error: MessageError; onRetry?: () => void }) {
  return (
    <ErrorNotice
      className="mt-2"
      title="The answer could not be completed"
      code={error.code}
      message={error.message}
      actions={
        onRetry ? (
          <button type="button" className={buttonOutline} onClick={onRetry}>
            <RotateCcw aria-hidden="true" className="h-3.5 w-3.5" />
            Retry
          </button>
        ) : undefined
      }
    />
  );
}

interface AssistantMessageProps {
  message: ChatMessage;
  onOpenSource: (source: Evidence) => void;
  documentTitle: (documentId: number) => string | null;
  /** Offered on the latest failed answer: asks the same question again. */
  onRetry?: () => void;
  onDeepAnalysis: (conversationId: number, documentId: number) => void;
}

/** A stored answer: markdown with citations, sources, "Why this answer?". */
export function AssistantMessage({ message, onOpenSource, documentTitle, onRetry, onDeepAnalysis }: AssistantMessageProps) {
  const summary = formatRetrievalSummary(message.retrieval, message.latency_ms);
  return (
    <article className="border-l-2 border-border pl-3" aria-label="Answer">
      {message.content && <AnswerMarkdown content={message.content} citations={message.citations} onOpenSource={onOpenSource} />}
      {message.status === "streaming" && (
        <p role="status" className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 aria-hidden="true" className="h-3.5 w-3.5 animate-spin" />
          Still being written on the server — this updates when it finishes.
        </p>
      )}
      {message.status === "failed" && (
        <TurnError error={message.error ?? { code: "answer_failed", message: "The answer could not be generated." }} onRetry={onRetry} />
      )}
      {message.status === "complete" && <SourcesList citations={message.citations} onOpen={onOpenSource} />}
      {message.status === "complete" && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
          {summary && <p className="font-mono text-[11px] text-muted-foreground">{summary}</p>}
          {message.analysis_turn && (
            <button
              type="button"
              className={`${buttonOutline} px-2 py-1 text-xs`}
              onClick={() => onDeepAnalysis(message.analysis_turn!.conversation_id, message.analysis_turn!.document_id)}
            >
              <Microscope aria-hidden="true" className="h-3.5 w-3.5" />
              Deep analysis
            </button>
          )}
        </div>
      )}
      {(message.status === "complete" || (message.status === "failed" && runIdOf(message) != null)) && (
        <WhyThisAnswer message={message} documentTitle={documentTitle} onOpenSource={onOpenSource} />
      )}
    </article>
  );
}

interface TurnViewProps {
  turn: StreamingTurn;
  /** False when the question is already shown as a stored message. */
  showQuestion: boolean;
  onOpenSource: (source: Evidence) => void;
  onRetry: () => void;
}

/** The answer being streamed right now, or a question that failed to send. */
export function TurnView({ turn, showQuestion, onOpenSource, onRetry }: TurnViewProps) {
  const finished = isTurnFinished(turn);
  return (
    <>
      {showQuestion && <UserBubble content={turn.question} pending={!turn.userMessage} />}
      <article className="border-l-2 border-primary/40 pl-3" aria-label="Answer in progress" aria-busy={!finished}>
        {!finished && <StreamProgress turn={turn} />}
        {turn.content && <AnswerMarkdown content={turn.content} citations={turn.citations} onOpenSource={onOpenSource} />}
        {!finished && turn.content && <span aria-hidden="true" className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 bg-foreground/50 motion-safe:animate-pulse" />}
        {!finished && <SourcesList citations={turn.citations} onOpen={onOpenSource} streaming />}
        {turn.error && <TurnError error={turn.error} onRetry={onRetry} />}
      </article>
    </>
  );
}
