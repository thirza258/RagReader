import React, { useState } from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonQuiet, eyebrow, focusRing } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatDate } from "../../documents/lib/format";
import type { Conversation } from "../types";
import Composer from "./Composer";

interface NewConversationProps {
  conversations: Conversation[];
  onSelect: (id: number) => void;
  /** Creates the conversation and opens it with this first question. */
  onStart: (question: string) => Promise<void>;
  composerDisabledReason: string | null;
}

/**
 * The chat pane before a conversation is open: ask the first question (the
 * conversation is created with the library's current "Use in chat" scope),
 * or continue a recent one.
 */
const NewConversation: React.FC<NewConversationProps> = ({ conversations, onSelect, onStart, composerDisabledReason }) => {
  const [error, setError] = useState<ApiRequestError | null>(null);

  const start = async (question: string) => {
    setError(null);
    try {
      await onStart(question);
      return true;
    } catch (caught) {
      setError(toApiError(caught));
      return false;
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="custom-scrollbar min-h-0 flex-1 overflow-y-auto px-3 py-4">
        <h3 className="text-base font-semibold">New conversation</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Ask about the documents ticked “Use in chat”. Answers stream in with numbered citations; click one to open the passage in the reader.
        </p>
        {error && (
          <ErrorNotice
            className="mt-3"
            title="The conversation could not be started"
            code={error.code}
            message={error.message}
            actions={
              <button type="button" className={buttonQuiet} onClick={() => setError(null)}>
                Dismiss
              </button>
            }
          />
        )}
        {conversations.length > 0 && (
          <section className="mt-6" aria-labelledby="recent-conversations">
            <h4 id="recent-conversations" className={eyebrow}>
              Recent conversations
            </h4>
            <ul className="mt-2 border-t border-border">
              {conversations.slice(0, 12).map((conversation) => (
                <li key={conversation.id} className="border-b border-border">
                  <button type="button" onClick={() => onSelect(conversation.id)} className={`block w-full px-1 py-2 text-left transition-colors hover:bg-accent ${focusRing}`}>
                    <span className="block truncate text-sm font-medium">{conversation.title || "Untitled conversation"}</span>
                    <span className="mt-0.5 block truncate text-xs text-muted-foreground">
                      {formatDate(conversation.updated_at)}
                      {conversation.last_message_preview ? ` · ${conversation.last_message_preview}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
      <Composer id="composer-new" onSend={start} busy={false} disabledReason={composerDisabledReason} />
    </div>
  );
};

export default NewConversation;
