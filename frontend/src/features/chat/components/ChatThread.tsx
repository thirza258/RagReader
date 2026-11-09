import React, { useEffect, useMemo, useRef } from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline } from "../../../components/ui/classes";
import { useChatThread } from "../hooks/useChatThread";
import type { ChatMessage, Evidence } from "../types";
import Composer from "./Composer";
import { AssistantMessage, TurnView, UserBubble } from "./MessageView";

interface ChatThreadProps {
  conversationId: number;
  /** A question typed before the conversation existed; sent once on mount. */
  initialQuestion: string | null;
  onInitialQuestionSent: () => void;
  onOpenSource: (source: Evidence) => void;
  /** After every turn (answer or failure), e.g. to refresh titles. */
  onTurnFinished: (message: ChatMessage | null) => void;
  /** The newest complete answer, for the workspace status bar. */
  onLatestAnswer: (message: ChatMessage | null) => void;
  onMissing: () => void;
  onDeepAnalysis: (conversationId: number, documentId: number) => void;
  documentTitle: (documentId: number) => string | null;
  composerDisabledReason: string | null;
}

/**
 * One conversation: stored messages, the answer streaming now, and the
 * composer. Mounted per conversation id, so switching aborts the stream.
 */
const ChatThread: React.FC<ChatThreadProps> = ({
  conversationId,
  initialQuestion,
  onInitialQuestionSent,
  onOpenSource,
  onTurnFinished,
  onLatestAnswer,
  onMissing,
  onDeepAnalysis,
  documentTitle,
  composerDisabledReason,
}) => {
  const { messages, loaded, error, turn, streaming, announcement, send, reload } = useChatThread(conversationId, onTurnFinished);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  useEffect(() => {
    if (!initialQuestion) return;
    // Deferred so React's development double-mount sends it only once.
    const timer = setTimeout(() => {
      if (send(initialQuestion)) onInitialQuestionSent();
    }, 0);
    return () => clearTimeout(timer);
  }, [initialQuestion, send, onInitialQuestionSent]);

  const latestAnswer = useMemo(() => {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      const message = messages[i];
      if (message.role === "assistant" && message.status === "complete" && message.retrieval) return message;
    }
    return null;
  }, [messages]);

  useEffect(() => {
    onLatestAnswer(latestAnswer);
  }, [latestAnswer, onLatestAnswer]);

  useEffect(() => () => onLatestAnswer(null), [onLatestAnswer]);

  useEffect(() => {
    const element = scrollRef.current;
    if (element && stickToBottom.current) element.scrollTop = element.scrollHeight;
  }, [messages, turn, loaded]);

  const ask = (content: string) => {
    stickToBottom.current = true;
    return send(content);
  };

  const last = messages[messages.length - 1];
  const retryLastFailed =
    !turn && last && last.role === "assistant" && last.status === "failed"
      ? () => {
          const question = [...messages].reverse().find((message) => message.role === "user");
          if (question) ask(question.content);
        }
      : undefined;
  const showTurnQuestion = !!turn && (!turn.userMessage || !messages.some((message) => message.id === turn.userMessage?.id));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        ref={scrollRef}
        onScroll={() => {
          const element = scrollRef.current;
          if (element) stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
        }}
        className="custom-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-4"
        role="log"
        aria-label="Conversation"
        aria-live="off"
      >
        {!loaded && !error && (
          <p role="status" className="text-sm text-muted-foreground">
            Loading messages…
          </p>
        )}
        {error && (
          <ErrorNotice
            title={error.status === 404 ? "This conversation was not found" : "Could not load the messages"}
            code={error.code}
            message={error.status === 404 ? "It may have been deleted." : error.message}
            actions={
              error.status === 404 ? (
                <button type="button" className={buttonOutline} onClick={onMissing}>
                  Start a new conversation
                </button>
              ) : (
                <button type="button" className={buttonOutline} onClick={reload}>
                  Try again
                </button>
              )
            }
          />
        )}
        {loaded && !error && messages.length === 0 && !turn && (
          <p className="text-sm text-muted-foreground">Ask a question to start. Answers cite the passages they use; click a citation to read it in context.</p>
        )}
        {messages.map((message, index) =>
          message.role === "user" ? (
            <UserBubble key={message.id} content={message.content} />
          ) : (
            <AssistantMessage
              key={message.id}
              message={message}
              onOpenSource={onOpenSource}
              documentTitle={documentTitle}
              onRetry={index === messages.length - 1 ? retryLastFailed : undefined}
              onDeepAnalysis={onDeepAnalysis}
            />
          ),
        )}
        {turn && <TurnView turn={turn} showQuestion={showTurnQuestion} onOpenSource={onOpenSource} onRetry={() => ask(turn.question)} />}
      </div>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      <Composer id={`composer-${conversationId}`} onSend={ask} busy={streaming} disabledReason={error?.status === 404 ? "This conversation no longer exists." : composerDisabledReason} />
    </div>
  );
};

export default ChatThread;
