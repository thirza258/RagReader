import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import SEO from "../components/SEO";
import ErrorNotice from "../components/ui/ErrorNotice";
import { buttonOutline, focusRing } from "../components/ui/classes";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useRequireToken } from "../features/auth/hooks/useRequireToken";
import { ApiRequestError, toApiError } from "../services/api/errors";
import { listWorkspaces } from "../features/workspaces/api/workspaces";
import { useWorkspaces } from "../features/workspaces/hooks/useWorkspaces";
import WorkspaceSwitcher from "../features/workspaces/components/WorkspaceSwitcher";
import { deleteDocument, getDocument, renameDocument, startIngestion } from "../features/documents/api/documents";
import { useDocuments } from "../features/documents/hooks/useDocuments";
import { includedIds } from "../features/documents/lib/scope";
import DocumentLibrary from "../features/documents/components/DocumentLibrary";
import type { WorkspaceDocument } from "../features/documents/types";
import { useConversations } from "../features/chat/hooks/useConversations";
import ChatThread from "../features/chat/components/ChatThread";
import ConversationBar from "../features/chat/components/ConversationBar";
import NewConversation from "../features/chat/components/NewConversation";
import { formatRetrievalSummary } from "../features/chat/lib/retrievalSummary";
import type { ChatMessage, Evidence } from "../features/chat/types";
import DocumentReader from "../features/reader/components/DocumentReader";
import RunsPanel from "../features/runs/components/RunsPanel";

const DESKTOP_QUERY = "(min-width: 1024px)";

type Pane = "documents" | "reader" | "chat" | "runs";
/** What the right-hand column shows on wide screens. */
type SidePane = "chat" | "runs";

const PANES: { id: Pane; label: string }[] = [
  { id: "documents", label: "Documents" },
  { id: "reader", label: "Reader" },
  { id: "chat", label: "Chat" },
  { id: "runs", label: "Runs" },
];

const SIDE_PANES: { id: SidePane; label: string }[] = [
  { id: "chat", label: "Chat" },
  { id: "runs", label: "Runs" },
];

function parseId(value: string | null | undefined): number | null {
  return value && /^\d+$/.test(value) ? Number(value) : null;
}

/**
 * The research workspace (PRD §37): documents | reader | chat side by side
 * on wide screens and as tabs on narrow ones, with the latest answer's
 * retrieval summary in the status bar. Routes: /workspace (picks the default
 * workspace), /workspace/:workspaceId and /workspace/:workspaceId/c/:conversationId.
 */
const WorkspacePage: React.FC = () => {
  const token = useRequireToken();
  const { workspaceId } = useParams();
  const id = parseId(workspaceId);

  return (
    <>
      <SEO
        title="Workspace — RAGReader"
        description="Your documents, a reader with highlighted evidence, and chat answers with citations in one workspace."
        canonicalUrl="https://rag.nevatal.id/workspace"
      />
      {!token ? (
        <p role="status" className="p-6 text-sm text-muted-foreground">
          Redirecting to sign in…
        </p>
      ) : workspaceId == null ? (
        <WorkspaceIndex />
      ) : id == null ? (
        <MissingWorkspace />
      ) : (
        <WorkspaceView key={id} workspaceId={id} />
      )}
    </>
  );
};

/** `/workspace`: open the workspace of `?document=`, else the default one. */
function WorkspaceIndex() {
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState<ApiRequestError | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const documentId = parseId(new URLSearchParams(location.search).get("document"));
    const resolve = async () => {
      let target: number | null = null;
      if (documentId != null) {
        try {
          target = (await getDocument(documentId, controller.signal)).workspace_id ?? null;
        } catch {
          target = null; // fall back to the default workspace
        }
      }
      if (target == null) {
        const list = await listWorkspaces(controller.signal);
        target = (list.find((workspace) => workspace.is_default) ?? list[0])?.id ?? null;
      }
      if (controller.signal.aborted) return;
      if (target == null) {
        setError(new ApiRequestError({ status: null, code: "no_workspace", message: "No workspace is available yet.", retryable: true }));
        return;
      }
      navigate(`/workspace/${target}${location.search}`, { replace: true });
    };
    resolve().catch((caught) => {
      if (!controller.signal.aborted) setError(toApiError(caught));
    });
    return () => controller.abort();
  }, [attempt, location.search, navigate]);

  if (error) {
    return (
      <div className="mx-auto w-full max-w-md p-6">
        <ErrorNotice
          title="Could not open your workspace"
          code={error.code}
          message={error.message}
          actions={
            <button
              type="button"
              className={buttonOutline}
              onClick={() => {
                setError(null);
                setAttempt((value) => value + 1);
              }}
            >
              Try again
            </button>
          }
        />
      </div>
    );
  }
  return (
    <p role="status" className="p-6 text-sm text-muted-foreground">
      Opening your workspace…
    </p>
  );
}

function MissingWorkspace() {
  return (
    <div className="mx-auto w-full max-w-md p-6">
      <h1 className="text-xl font-semibold">Workspace not found</h1>
      <p className="mt-2 text-sm text-muted-foreground">It may have been deleted, or it belongs to another account.</p>
      <Link to="/workspace" className={`${buttonOutline} mt-4`}>
        Open my workspace
      </Link>
    </div>
  );
}

function WorkspaceView({ workspaceId }: { workspaceId: number }) {
  const navigate = useNavigate();
  const { conversationId: conversationParam } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const isDesktop = useMediaQuery(DESKTOP_QUERY);

  const workspaces = useWorkspaces();
  const {
    documents,
    loaded: documentsLoaded,
    error: documentsError,
    announcement: documentsAnnouncement,
    refresh: refreshDocuments,
    upsert: upsertDocument,
    removeLocal: removeDocument,
  } = useDocuments(workspaceId);
  const conversations = useConversations(workspaceId);
  const { refresh: refreshConversations } = conversations;

  const conversationId = parseId(conversationParam);
  const activeConversation = conversations.list.find((conversation) => conversation.id === conversationId) ?? null;
  const readerDocumentId = parseId(searchParams.get("document"));
  const readerDocument = documents.find((document) => document.id === readerDocumentId) ?? null;

  const [pane, setPane] = useState<Pane>(conversationId != null ? "chat" : "documents");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const [draftScope, setDraftScope] = useState<number[]>([]);
  const [scopeBusy, setScopeBusy] = useState(false);
  const [scopeError, setScopeError] = useState<ApiRequestError | null>(null);
  const [pending, setPending] = useState<{ conversationId: number; content: string } | null>(null);
  const [latestAnswer, setLatestAnswer] = useState<ChatMessage | null>(null);
  const [sidePane, setSidePane] = useState<SidePane>("chat");
  const [selectedRunId, setSelectedRunId] = useState<number | null>(null);
  const [runsVersion, setRunsVersion] = useState(0);

  /** Chat or Runs: a mobile tab, or the right-hand column on wide screens. */
  const showPane = useCallback((id: Pane) => {
    setPane(id);
    if (id === "chat" || id === "runs") setSidePane(id);
  }, []);

  const search = searchParams.toString();
  const pathFor = useCallback(
    (targetConversation: number | null) => `/workspace/${workspaceId}${targetConversation != null ? `/c/${targetConversation}` : ""}${search ? `?${search}` : ""}`,
    [workspaceId, search],
  );

  const showDocument = useCallback(
    (documentId: number | null) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current);
          if (documentId == null) next.delete("document");
          else next.set("document", String(documentId));
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const openSource = useCallback(
    (source: Evidence) => {
      setEvidence(source);
      setFocusRequest((value) => value + 1);
      showDocument(source.document_id);
      setPane("reader");
    },
    [showDocument],
  );

  const openDocument = (document: WorkspaceDocument) => {
    setEvidence(null);
    showDocument(document.id);
    setPane("reader");
  };

  const documentTitle = useCallback((documentId: number) => documents.find((document) => document.id === documentId)?.title ?? null, [documents]);

  // ---- chat scope ("Use in chat") --------------------------------------
  // The open conversation's scope is unknown until the list arrives; a
  // conversation that is not in the list (deleted) falls back to the draft.
  const waitingForConversation = conversationId != null && !activeConversation && !conversations.loaded;
  const activeScope = activeConversation?.document_ids;
  const scopeIds = useMemo(() => activeScope ?? (waitingForConversation ? [] : draftScope), [activeScope, waitingForConversation, draftScope]);
  const changeScope = async (ids: number[]) => {
    setScopeError(null);
    if (!activeConversation) {
      setDraftScope(ids);
      return;
    }
    setScopeBusy(true);
    try {
      await conversations.setScope(activeConversation.id, ids, activeConversation.document_ids);
    } catch (caught) {
      setScopeError(toApiError(caught));
    } finally {
      setScopeBusy(false);
    }
  };
  const readyInScope = useMemo(() => {
    const included = includedIds(scopeIds, documents);
    return documents.filter((document) => included.has(document.id) && document.status === "READY").length;
  }, [scopeIds, documents]);
  const composerDisabledReason =
    documentsLoaded && readyInScope === 0
      ? documents.length === 0
        ? "Add a document and wait until it is ready to ask questions."
        : "No document in this conversation's scope is ready yet."
      : null;

  // ---- conversations ---------------------------------------------------
  const selectConversation = (id: number | null) => {
    setScopeError(null);
    navigate(pathFor(id));
    showPane("chat");
  };

  const createEmptyConversation = async () => {
    const conversation = await conversations.create(activeConversation ? [] : draftScope);
    refreshWorkspaces();
    setDraftScope([]);
    navigate(pathFor(conversation.id));
    setPane("chat");
  };

  const startConversation = async (question: string) => {
    const conversation = await conversations.create(draftScope);
    refreshWorkspaces();
    setPending({ conversationId: conversation.id, content: question });
    setDraftScope([]);
    navigate(pathFor(conversation.id));
  };

  const deleteConversation = async (id: number) => {
    await conversations.remove(id);
    refreshWorkspaces();
    if (id === conversationId) navigate(pathFor(null));
  };

  const onInitialQuestionSent = useCallback(() => setPending(null), []);
  const { refresh: refreshWorkspaces } = workspaces;
  const onTurnFinished = useCallback(() => {
    refreshConversations();
    setRunsVersion((value) => value + 1);
  }, [refreshConversations]);
  const onDeepAnalysis = useCallback((legacyConversationId: number, documentId: number) => navigate(`/ground-truth/${legacyConversationId}/${documentId}`), [navigate]);

  // ---- documents -------------------------------------------------------
  const onCreated = (document: WorkspaceDocument) => {
    upsertDocument(document);
    refreshWorkspaces();
  };
  const onRename = async (document: WorkspaceDocument, title: string) => {
    upsertDocument(await renameDocument(document.id, title));
  };
  const onDelete = async (document: WorkspaceDocument) => {
    await deleteDocument(document.id);
    removeDocument(document.id);
    refreshWorkspaces();
    setDraftScope((ids) => ids.filter((id) => id !== document.id));
    if (readerDocumentId === document.id) {
      setEvidence(null);
      showDocument(null);
    }
    refreshConversations();
  };
  const onReindex = async (document: WorkspaceDocument) => {
    await startIngestion(document.id);
    refreshDocuments();
  };

  // ---- workspaces ------------------------------------------------------
  const switchWorkspace = (id: number) => navigate(`/workspace/${id}`);
  const createWorkspace = async (name: string) => {
    const workspace = await workspaces.create(name);
    navigate(`/workspace/${workspace.id}`);
  };
  const renameWorkspace = async (id: number, name: string) => {
    await workspaces.rename(id, name);
  };
  const deleteWorkspace = async (id: number) => {
    const fallback = workspaces.list.find((workspace) => workspace.id !== id && workspace.is_default) ?? workspaces.list.find((workspace) => workspace.id !== id);
    await workspaces.remove(id);
    navigate(fallback ? `/workspace/${fallback.id}` : "/workspace", { replace: true });
  };

  const activeWorkspace = workspaces.list.find((workspace) => workspace.id === workspaceId) ?? null;
  const missing = documentsError?.status === 404 || (workspaces.loaded && !workspaces.error && !activeWorkspace);
  if (missing) return <MissingWorkspace />;

  const summary = formatRetrievalSummary(latestAnswer?.retrieval, latestAnswer?.latency_ms);
  const paneClass = (id: Pane) => `${isDesktop || pane === id ? "flex" : "hidden"} min-h-0 min-w-0 flex-col overflow-hidden`;
  // The chat stays mounted (only hidden) while Runs is shown: unmounting it
  // would abort an answer that is still streaming.
  const side: SidePane = isDesktop ? sidePane : pane === "runs" ? "runs" : "chat";
  const sideVisible = isDesktop || pane === "chat" || pane === "runs";
  const sideLabelledBy = (id: SidePane) => (isDesktop ? `side-tab-${id}` : `tab-${id}`);
  const paneProps = (id: Pane, label: string) =>
    isDesktop
      ? { id: `pane-${id}`, "aria-label": label }
      : { id: `pane-${id}`, role: "tabpanel", "aria-labelledby": `tab-${id}` };

  const onTabKeyDown = (event: React.KeyboardEvent) => {
    const index = PANES.findIndex((item) => item.id === pane);
    const targets: Record<string, number> = {
      ArrowRight: (index + 1) % PANES.length,
      ArrowLeft: (index - 1 + PANES.length) % PANES.length,
      Home: 0,
      End: PANES.length - 1,
    };
    const next = targets[event.key];
    if (next === undefined) return;
    event.preventDefault();
    showPane(PANES[next].id);
    window.document.getElementById(`tab-${PANES[next].id}`)?.focus();
  };

  const onSideTabKeyDown = (event: React.KeyboardEvent) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = SIDE_PANES.findIndex((item) => item.id === sidePane);
    const next = event.key === "Home" ? 0 : event.key === "End" ? SIDE_PANES.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + SIDE_PANES.length) % SIDE_PANES.length;
    showPane(SIDE_PANES[next].id);
    window.document.getElementById(`side-tab-${SIDE_PANES[next].id}`)?.focus();
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h1 className="sr-only">Workspace{activeWorkspace ? `: ${activeWorkspace.name}` : ""}</h1>
      <header className="border-b border-border px-4 py-2">
        <WorkspaceSwitcher
          workspaces={workspaces.list}
          loaded={workspaces.loaded}
          activeId={workspaceId}
          onSwitch={switchWorkspace}
          onCreate={createWorkspace}
          onRename={renameWorkspace}
          onDelete={deleteWorkspace}
        />
      </header>

      {!isDesktop && (
        <div role="tablist" aria-label="Workspace panes" className="flex shrink-0 border-b border-border" onKeyDown={onTabKeyDown}>
          {PANES.map((item) => (
            <button
              key={item.id}
              id={`tab-${item.id}`}
              type="button"
              role="tab"
              aria-selected={pane === item.id}
              aria-controls={`pane-${item.id}`}
              tabIndex={pane === item.id ? 0 : -1}
              onClick={() => showPane(item.id)}
              className={`flex-1 border-b-2 px-3 py-2 text-sm transition-colors ${focusRing} ${
                pane === item.id ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}

      {/* One row that fills the height, so each pane scrolls inside itself. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)] overflow-hidden lg:grid-cols-[minmax(250px,300px)_minmax(0,1fr)_minmax(330px,420px)] xl:grid-cols-[320px_minmax(0,1fr)_460px]">
        <section {...paneProps("documents", "Documents")} className={`${paneClass("documents")} border-border lg:border-r`}>
          <DocumentLibrary
            workspaceId={workspaceId}
            documents={documents}
            loaded={documentsLoaded}
            error={documentsError}
            announcement={documentsAnnouncement}
            activeDocumentId={readerDocumentId}
            scope={{ ids: scopeIds, busy: scopeBusy, loading: waitingForConversation, error: scopeError }}
            scopeTarget={activeConversation || waitingForConversation ? "conversation" : "new"}
            onOpen={openDocument}
            onScopeChange={(ids) => void changeScope(ids)}
            onRefresh={refreshDocuments}
            onCreated={onCreated}
            onRename={onRename}
            onDelete={onDelete}
            onReindex={onReindex}
            onDismissScopeError={() => setScopeError(null)}
          />
        </section>

        <section {...paneProps("reader", "Reader")} className={`${paneClass("reader")} bg-background`}>
          <DocumentReader
            documentId={readerDocumentId}
            document={readerDocument}
            documentsLoaded={documentsLoaded}
            evidence={evidence}
            focusRequest={focusRequest}
            onClearEvidence={() => setEvidence(null)}
          />
        </section>

        <section
          aria-label={isDesktop ? "Chat and runs" : undefined}
          className={`${sideVisible ? "flex" : "hidden"} min-h-0 min-w-0 flex-col overflow-hidden border-border lg:border-l`}
        >
          {isDesktop && (
            <div role="tablist" aria-label="Chat or runs" className="flex shrink-0 border-b border-border" onKeyDown={onSideTabKeyDown}>
              {SIDE_PANES.map((item) => (
                <button
                  key={item.id}
                  id={`side-tab-${item.id}`}
                  type="button"
                  role="tab"
                  aria-selected={sidePane === item.id}
                  aria-controls={`pane-${item.id}`}
                  tabIndex={sidePane === item.id ? 0 : -1}
                  onClick={() => showPane(item.id)}
                  className={`flex-1 border-b-2 px-3 py-1.5 text-sm transition-colors ${focusRing} ${
                    sidePane === item.id ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {item.label}
                </button>
              ))}
            </div>
          )}
          <div id="pane-chat" role="tabpanel" aria-labelledby={sideLabelledBy("chat")} className={`${side === "chat" ? "flex" : "hidden"} min-h-0 flex-1 flex-col`}>
            <ConversationBar
              conversations={conversations.list}
              loaded={conversations.loaded}
              activeId={conversationId}
              onSelect={selectConversation}
              onCreate={createEmptyConversation}
              onRename={async (id, title) => {
                await conversations.update(id, { title });
              }}
              onDelete={deleteConversation}
            />
            {conversations.error && (
              <div className="border-b border-border p-3">
                <ErrorNotice
                  title="Could not load the conversations"
                  code={conversations.error.code}
                  message={conversations.error.message}
                  actions={
                    <button type="button" className={buttonOutline} onClick={refreshConversations}>
                      Try again
                    </button>
                  }
                />
              </div>
            )}
            {conversationId != null ? (
              <ChatThread
                key={conversationId}
                conversationId={conversationId}
                initialQuestion={pending?.conversationId === conversationId ? pending.content : null}
                onInitialQuestionSent={onInitialQuestionSent}
                onOpenSource={openSource}
                onTurnFinished={onTurnFinished}
                onLatestAnswer={setLatestAnswer}
                onMissing={() => selectConversation(null)}
                onDeepAnalysis={onDeepAnalysis}
                documentTitle={documentTitle}
                composerDisabledReason={composerDisabledReason}
              />
            ) : (
              <NewConversation
                conversations={conversations.list}
                onSelect={(id) => selectConversation(id)}
                onStart={startConversation}
                composerDisabledReason={composerDisabledReason}
              />
            )}
          </div>
          <div id="pane-runs" role="tabpanel" aria-labelledby={sideLabelledBy("runs")} className={`${side === "runs" ? "flex" : "hidden"} min-h-0 flex-1 flex-col`}>
            {side === "runs" && sideVisible && (
              <RunsPanel
                workspaceId={workspaceId}
                version={runsVersion}
                selectedRunId={selectedRunId}
                onSelectRun={setSelectedRunId}
                onOpenCandidate={openSource}
                onOpenConversation={(id) => selectConversation(id)}
              />
            )}
          </div>
        </section>
      </div>

      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-x-4 gap-y-0.5 border-t border-border bg-muted px-4 py-1.5 font-mono text-[11px] text-muted-foreground">
        <span>{summary ?? "Retrieval: no answer yet in this conversation"}</span>
        {latestAnswer?.retrieval?.pipeline?.generation_model && <span className="truncate">{latestAnswer.retrieval.pipeline.generation_model}</span>}
      </footer>
    </div>
  );
}

export default WorkspacePage;
