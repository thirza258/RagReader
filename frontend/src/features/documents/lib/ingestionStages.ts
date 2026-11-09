import type { DocumentStatus, IngestionStage, IngestionStageState } from "../types/index.ts";

/**
 * The ingestion checklist (PRD §9), derived from a document's `status` and
 * `error.stage` with the same rules as the API's IngestionStatus:
 * QUEUED = Uploaded done and the rest pending; an active status marks earlier
 * stages done and itself active; READY marks everything done; FAILED marks
 * `error.stage` failed and earlier stages done.
 */

export const INGESTION_STAGES = [
  { id: "UPLOADING", name: "Upload", label: "Uploaded", activeLabel: "Uploading…", failedLabel: "Upload failed" },
  { id: "EXTRACTING", name: "Text extraction", label: "Text extracted", activeLabel: "Extracting text…", failedLabel: "Text extraction failed" },
  { id: "CLEANING", name: "Cleaning", label: "Content cleaned", activeLabel: "Cleaning content…", failedLabel: "Cleaning failed" },
  { id: "CHUNKING", name: "Chunking", label: "Chunks created", activeLabel: "Creating chunks…", failedLabel: "Chunking failed" },
  { id: "EMBEDDING", name: "Embedding", label: "Embeddings generated", activeLabel: "Generating embeddings…", failedLabel: "Embedding failed" },
  { id: "INDEXING", name: "Indexing", label: "Index built", activeLabel: "Building index…", failedLabel: "Indexing failed" },
] as const;

export const TERMINAL_STATUSES: readonly DocumentStatus[] = ["READY", "FAILED"];

export function isTerminalStatus(status: string): boolean {
  return status === "READY" || status === "FAILED";
}

export interface DerivedStage extends IngestionStage {
  /** What to show for this row: the active wording while it runs. */
  text: string;
}

function stageIndex(id: string | null | undefined): number {
  if (!id) return -1;
  const upper = id.toUpperCase();
  return INGESTION_STAGES.findIndex((stage) => stage.id === upper);
}

export interface StageOptions {
  /** Shown as "384 chunks created" once chunking is done. */
  chunkCount?: number | null;
}

export function deriveIngestionStages(
  status: string,
  errorStage: string | null | undefined,
  options: StageOptions = {},
): DerivedStage[] {
  const upper = (status || "").toUpperCase();
  const states: IngestionStageState[] = INGESTION_STAGES.map(() => "pending");

  if (upper === "READY") {
    states.fill("done");
  } else if (upper === "FAILED") {
    const failedAt = stageIndex(errorStage);
    if (failedAt >= 0) {
      for (let i = 0; i < failedAt; i += 1) states[i] = "done";
      states[failedAt] = "failed";
    } else {
      // No stage (e.g. the job queue was down, or a legacy row was never
      // indexed): the upload itself exists, nothing after it ran.
      states[0] = "done";
    }
  } else if (upper === "QUEUED") {
    states[0] = "done";
  } else {
    const active = stageIndex(upper);
    if (active >= 0) {
      for (let i = 0; i < active; i += 1) states[i] = "done";
      states[active] = "active";
    } else {
      states[0] = "done"; // an unknown in-progress status: be conservative
    }
  }

  return INGESTION_STAGES.map((stage, i) => {
    const state = states[i];
    let text: string = stage.label;
    if (state === "active") text = stage.activeLabel;
    else if (state === "failed") text = stage.failedLabel;
    else if (state === "done" && stage.id === "CHUNKING" && options.chunkCount && options.chunkCount > 0) {
      text = `${options.chunkCount.toLocaleString("en-US")} chunks created`;
    }
    return { id: stage.id, label: stage.label, state, text };
  });
}

const STATUS_LABELS: Record<string, string> = {
  UPLOADING: "Uploading",
  QUEUED: "Queued",
  EXTRACTING: "Extracting text",
  CLEANING: "Cleaning",
  CHUNKING: "Chunking",
  EMBEDDING: "Embedding",
  INDEXING: "Indexing",
  READY: "Ready",
  FAILED: "Failed",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[(status || "").toUpperCase()] ?? status;
}

/** A readable name for an `error.stage`, e.g. "EMBEDDING" -> "Embedding". */
export function stageName(stage: string | null | undefined): string | null {
  const index = stageIndex(stage);
  if (index >= 0) return INGESTION_STAGES[index].name;
  return stage ? stage.charAt(0).toUpperCase() + stage.slice(1).toLowerCase() : null;
}
