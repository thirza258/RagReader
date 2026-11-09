import React, { useState } from "react";
import { Plus } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonPrimary, buttonQuiet, buttonQuietDanger, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatDate } from "../../documents/lib/format";
import type { Conversation } from "../types";

interface ConversationBarProps {
  conversations: Conversation[];
  loaded: boolean;
  activeId: number | null;
  onSelect: (id: number | null) => void;
  onCreate: () => Promise<void>;
  onRename: (id: number, title: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

type Mode = "view" | "rename" | "confirm-delete";

/** Switch, create, rename and delete conversations (PRD §15). */
const ConversationBar: React.FC<ConversationBarProps> = ({ conversations, loaded, activeId, onSelect, onCreate, onRename, onDelete }) => {
  const active = conversations.find((conversation) => conversation.id === activeId) ?? null;
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; error: ApiRequestError } | null>(null);

  const run = async (title: string, work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await work();
      setMode("view");
    } catch (caught) {
      setError({ title, error: toApiError(caught) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-border px-3 py-2">
      <div className="flex items-center gap-2">
        <label htmlFor="conversation-select" className="sr-only">
          Conversation
        </label>
        <select
          id="conversation-select"
          className={`${inputSmall} min-w-0 flex-1 truncate`}
          value={activeId ?? ""}
          disabled={!loaded}
          onChange={(event) => {
            setMode("view");
            onSelect(event.target.value ? Number(event.target.value) : null);
          }}
        >
          <option value="">{loaded ? "New conversation" : "Loading conversations…"}</option>
          {conversations.map((conversation) => (
            <option key={conversation.id} value={conversation.id}>
              {conversation.title || "Untitled conversation"}
              {conversation.updated_at ? ` — ${formatDate(conversation.updated_at)}` : ""}
            </option>
          ))}
          {activeId != null && !active && loaded && <option value={activeId}>Conversation {activeId}</option>}
        </select>
        <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} disabled={busy} onClick={() => void run("Could not start a conversation", onCreate)}>
          <Plus aria-hidden="true" className="h-3.5 w-3.5" />
          New
        </button>
      </div>

      {active && mode === "view" && (
        <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground">
          <span className="mr-1 tabular">
            {active.message_count} message{active.message_count === 1 ? "" : "s"}
          </span>
          <button
            type="button"
            className={buttonQuiet}
            onClick={() => {
              setDraft(active.title);
              setError(null);
              setMode("rename");
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className={buttonQuietDanger}
            onClick={() => {
              setError(null);
              setMode("confirm-delete");
            }}
          >
            Delete
          </button>
        </div>
      )}

      {active && mode === "rename" && (
        <form
          className="mt-1.5 flex items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            const title = draft.trim();
            if (!title || title === active.title) {
              setMode("view");
              return;
            }
            void run("Rename failed", () => onRename(active.id, title));
          }}
        >
          <label htmlFor="rename-conversation" className="sr-only">
            New conversation title
          </label>
          <input
            id="rename-conversation"
            className={`${inputSmall} min-w-0 flex-1`}
            value={draft}
            maxLength={200}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                setMode("view");
              }
            }}
          />
          <button type="submit" className={`${buttonPrimary} px-2 py-1 text-xs`} disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
          <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
            Cancel
          </button>
        </form>
      )}

      {active && mode === "confirm-delete" && (
        <div role="group" aria-label="Confirm deleting this conversation" className="mt-1.5 border border-destructive/30 bg-destructive/5 p-2.5 text-xs">
          <p>
            Delete <span className="font-medium">“{active.title}”</span> and its {active.message_count} message{active.message_count === 1 ? "" : "s"}? Documents are
            kept.
          </p>
          <div className="mt-2 flex gap-2">
            <button type="button" className={`${buttonDanger} px-2 py-1 text-xs`} disabled={busy} onClick={() => void run("Delete failed", () => onDelete(active.id))}>
              {busy ? "Deleting…" : "Delete conversation"}
            </button>
            <button type="button" autoFocus className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <ErrorNotice
          className="mt-2 text-xs"
          title={error.title}
          code={error.error.code}
          message={error.error.message}
          actions={
            <button type="button" className={buttonQuiet} onClick={() => setError(null)}>
              Dismiss
            </button>
          }
        />
      )}
    </div>
  );
};

export default ConversationBar;
