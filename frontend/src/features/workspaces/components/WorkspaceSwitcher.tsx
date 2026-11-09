import React, { useState } from "react";
import { Plus } from "lucide-react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonDanger, buttonOutline, buttonPrimary, buttonQuiet, buttonQuietDanger, inputSmall } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import type { Workspace } from "../types";

interface WorkspaceSwitcherProps {
  workspaces: Workspace[];
  loaded: boolean;
  activeId: number;
  onSwitch: (id: number) => void;
  onCreate: (name: string) => Promise<void>;
  onRename: (id: number, name: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}

type Mode = "view" | "create" | "rename" | "confirm-delete";

function plural(count: number, word: string) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/** Switch, create, rename and delete workspaces, inline in the page header. */
const WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps> = ({ workspaces, loaded, activeId, onSwitch, onCreate, onRename, onDelete }) => {
  const active = workspaces.find((workspace) => workspace.id === activeId) ?? null;
  const [mode, setMode] = useState<Mode>("view");
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<{ title: string; error: ApiRequestError } | null>(null);
  const isLast = workspaces.length <= 1;

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

  const nameForm = (submitLabel: string, onSubmit: (name: string) => Promise<void>, errorTitle: string, inputLabel: string) => (
    <form
      className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5"
      onSubmit={(event) => {
        event.preventDefault();
        const name = draft.trim();
        if (!name) return;
        void run(errorTitle, () => onSubmit(name));
      }}
    >
      <label htmlFor="workspace-name" className="sr-only">
        {inputLabel}
      </label>
      <input
        id="workspace-name"
        className={`${inputSmall} w-56 max-w-full`}
        value={draft}
        maxLength={120}
        autoFocus
        placeholder="Workspace name"
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            setMode("view");
          }
        }}
      />
      <button type="submit" className={`${buttonPrimary} px-2 py-1 text-xs`} disabled={busy || !draft.trim()}>
        {busy ? "Saving…" : submitLabel}
      </button>
      <button type="button" className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
        Cancel
      </button>
    </form>
  );

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        {mode === "create" ? (
          nameForm("Create", onCreate, "Could not create the workspace", "Name of the new workspace")
        ) : mode === "rename" && active ? (
          nameForm("Rename", (name) => onRename(active.id, name), "Could not rename the workspace", "New name for this workspace")
        ) : (
          <>
            <label htmlFor="workspace-select" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Workspace
            </label>
            <select
              id="workspace-select"
              className={`${inputSmall} w-auto max-w-[16rem] font-serif text-base font-semibold`}
              value={activeId}
              disabled={!loaded}
              onChange={(event) => onSwitch(Number(event.target.value))}
            >
              {!active && <option value={activeId}>{loaded ? `Workspace ${activeId}` : "Loading…"}</option>}
              {workspaces.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                </option>
              ))}
            </select>
            {active && (
              <span className="text-xs text-muted-foreground tabular">
                {plural(active.document_count, "document")} · {plural(active.conversation_count, "conversation")}
              </span>
            )}
            <span className="flex items-center gap-0.5">
              <button
                type="button"
                className={buttonQuiet}
                onClick={() => {
                  setDraft("");
                  setError(null);
                  setMode("create");
                }}
              >
                <Plus aria-hidden="true" className="h-3.5 w-3.5" />
                New workspace
              </button>
              {active && (
                <button
                  type="button"
                  className={buttonQuiet}
                  onClick={() => {
                    setDraft(active.name);
                    setError(null);
                    setMode("rename");
                  }}
                >
                  Rename
                </button>
              )}
              {active && (
                <button
                  type="button"
                  className={buttonQuietDanger}
                  disabled={isLast}
                  title={isLast ? "The last workspace cannot be deleted" : undefined}
                  onClick={() => {
                    setError(null);
                    setMode("confirm-delete");
                  }}
                >
                  Delete
                </button>
              )}
            </span>
          </>
        )}
      </div>

      {mode === "confirm-delete" && active && (
        <div role="group" aria-label={`Confirm deleting the workspace ${active.name}`} className="mt-2 max-w-xl border border-destructive/30 bg-destructive/5 p-2.5 text-xs">
          <p>
            Delete the workspace <span className="font-medium">“{active.name}”</span> with its {plural(active.document_count, "document")} and{" "}
            {plural(active.conversation_count, "conversation")}? This cannot be undone.
          </p>
          <div className="mt-2 flex gap-2">
            <button type="button" className={`${buttonDanger} px-2 py-1 text-xs`} disabled={busy} onClick={() => void run("Could not delete the workspace", () => onDelete(active.id))}>
              {busy ? "Deleting…" : "Delete workspace"}
            </button>
            <button type="button" autoFocus className={`${buttonOutline} px-2 py-1 text-xs`} onClick={() => setMode("view")}>
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <ErrorNotice
          className="mt-2 max-w-xl text-xs"
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

export default WorkspaceSwitcher;
