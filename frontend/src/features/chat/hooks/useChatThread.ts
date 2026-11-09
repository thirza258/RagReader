import { useCallback, useEffect, useRef, useState } from "react";
import { ApiRequestError, toApiError } from "../../../services/api/errors";
import { listMessages, streamMessage } from "../api/conversations";
import { applyChatStreamEvent, interruptTurn, isTurnFinished, startTurn, type StreamingTurn } from "../lib/chatStream";
import type { ChatMessage, MessageError } from "../types";

interface ThreadState {
  messages: ChatMessage[];
  loaded: boolean;
  error: ApiRequestError | null;
}

/** While the server is still writing an answer, re-read the thread this often… */
const STREAMING_POLL_MS = 3000;
/** …but not forever. */
const MAX_STREAMING_POLLS = 60;

function replaceOrAppend(messages: ChatMessage[], additions: ChatMessage[]): ChatMessage[] {
  const ids = new Set(additions.map((message) => message.id));
  return [...messages.filter((message) => !ids.has(message.id)), ...additions];
}

function messageError(error: ApiRequestError): MessageError {
  return { code: error.code, message: error.message, retryable: error.retryable, stage: error.stage };
}

/**
 * One conversation's messages plus the answer being streamed (PRD §15–16).
 * Mount it per conversation (key by id): unmounting aborts the stream, and
 * the server still finishes and stores the answer.
 */
export function useChatThread(conversationId: number, onTurnFinished?: (message: ChatMessage | null) => void) {
  const [thread, setThread] = useState<ThreadState>({ messages: [], loaded: false, error: null });
  const [turn, setTurn] = useState<StreamingTurn | null>(null);
  const [version, setVersion] = useState(0);
  /** Said once per finished turn, for screen readers (the log itself is not live). */
  const [announcement, setAnnouncement] = useState("");
  const controllerRef = useRef<AbortController | null>(null);
  const busyRef = useRef(false);
  const pollsRef = useRef(0);
  const finishedRef = useRef(onTurnFinished);

  useEffect(() => {
    finishedRef.current = onTurnFinished;
  }, [onTurnFinished]);

  useEffect(() => {
    const controller = new AbortController();
    listMessages(conversationId, controller.signal).then(
      (messages) => setThread({ messages, loaded: true, error: null }),
      (error) => {
        if (!controller.signal.aborted) setThread((current) => ({ ...current, loaded: true, error: toApiError(error) }));
      },
    );
    return () => controller.abort();
  }, [conversationId, version]);

  // An answer stored as "streaming" is still being written by the server
  // (e.g. the page was reloaded mid-answer): re-read until it settles.
  const serverStreaming = thread.loaded && thread.messages.some((message) => message.role === "assistant" && message.status === "streaming");
  const waitingForServer = serverStreaming && !(turn && !isTurnFinished(turn));
  useEffect(() => {
    if (!waitingForServer) {
      pollsRef.current = 0;
      return;
    }
    if (pollsRef.current >= MAX_STREAMING_POLLS) return;
    const timer = setTimeout(() => {
      pollsRef.current += 1;
      setVersion((value) => value + 1);
    }, STREAMING_POLL_MS);
    return () => clearTimeout(timer);
  }, [waitingForServer, thread.messages]);

  useEffect(
    () => () => {
      controllerRef.current?.abort();
    },
    [],
  );

  const reload = useCallback(() => setVersion((value) => value + 1), []);

  const dismissTurn = useCallback(() => setTurn(null), []);

  /** Starts a turn; false when another answer is still streaming. */
  const send = useCallback(
    (rawContent: string): boolean => {
      const content = rawContent.trim();
      if (!content || busyRef.current) return false;
      busyRef.current = true;
      const controller = new AbortController();
      controllerRef.current = controller;
      let local = startTurn(content);
      setTurn(local);

      // Token events arrive faster than the screen refreshes: render at most
      // once per frame.
      let frame = 0;
      const flush = () => {
        frame = 0;
        setTurn(local);
      };
      const cancelFrame = () => {
        if (frame) cancelAnimationFrame(frame);
        frame = 0;
      };

      const run = async () => {
        try {
          await streamMessage(conversationId, { content }, {
            signal: controller.signal,
            onEvent: (event) => {
              local = applyChatStreamEvent(local, event);
              if (event.type === "token") {
                if (!frame) frame = requestAnimationFrame(flush);
              } else {
                cancelFrame();
                setTurn(local);
              }
            },
          });
          cancelFrame();
          if (!isTurnFinished(local)) {
            local = interruptTurn(local, {
              code: "stream_interrupted",
              message: "The connection closed before the answer finished.",
              retryable: true,
            });
          }
        } catch (error) {
          cancelFrame();
          if (controller.signal.aborted) return; // switched away or unmounted
          const apiError = toApiError(error);
          local = local.userMessage ? interruptTurn(local, messageError(apiError)) : { ...local, phase: "failed", error: messageError(apiError) };
        } finally {
          busyRef.current = false;
          if (controllerRef.current === controller) controllerRef.current = null;
        }

        const settled = local;
        setAnnouncement(
          settled.phase === "completed"
            ? "The answer is complete."
            : settled.phase === "interrupted"
              ? "The connection closed; reloading the answer."
              : `The answer failed: ${settled.error?.message ?? "unknown error"}`,
        );
        if (settled.phase === "completed" && settled.userMessage && settled.assistantMessage) {
          const pair = [settled.userMessage, settled.assistantMessage];
          setThread((current) => ({ ...current, messages: replaceOrAppend(current.messages, pair) }));
          setTurn(null);
        } else if (settled.phase === "failed" && settled.userMessage) {
          // Stored on the server as a failed pair: show it in the thread.
          const assistant = settled.assistantMessage
            ? { ...settled.assistantMessage, status: "failed" as const, error: settled.assistantMessage.error ?? settled.error }
            : null;
          const pair = assistant ? [settled.userMessage, assistant] : [settled.userMessage];
          setThread((current) => ({ ...current, messages: replaceOrAppend(current.messages, pair) }));
          setTurn(assistant ? null : settled);
        } else if (settled.phase === "interrupted") {
          // The server keeps generating after a disconnect; read what it has.
          setTurn(null);
          setVersion((value) => value + 1);
        } else {
          setTurn(settled); // nothing stored: keep the question with its error
        }
        finishedRef.current?.(settled.phase === "completed" ? settled.assistantMessage : null);
      };
      void run();
      return true;
    },
    [conversationId],
  );

  return {
    messages: thread.messages,
    loaded: thread.loaded,
    error: thread.error,
    turn,
    streaming: !!turn && !isTurnFinished(turn),
    waitingForServer,
    announcement,
    send,
    reload,
    dismissTurn,
  };
}
