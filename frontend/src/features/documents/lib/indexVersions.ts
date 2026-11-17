import type { IndexVersion } from "../../pipelines/types/index.ts";

/**
 * Index versions of a document (PRD §19) as people read them. Pure, for the
 * document row and tests.
 */

/** "paragraph, 512 characters, 50 overlap"; null when not recorded. */
export function chunkConfigText(config: IndexVersion["chunk_config"]): string | null {
  if (!config) return null;
  const parts: string[] = [];
  if (config.strategy) parts.push(config.strategy);
  if (typeof config.chunk_size === "number") parts.push(`${config.chunk_size} characters`);
  if (typeof config.overlap === "number") parts.push(`${config.overlap} overlap`);
  return parts.length > 0 ? parts.join(", ") : null;
}

/** "Index #7 · dense · current"; older versions add "superseded". */
export function indexVersionLabel(index: Pick<IndexVersion, "id" | "method" | "is_current" | "status">): string {
  const parts = [`Index #${index.id}`, index.method];
  if (index.status !== "ready") parts.push(index.status);
  parts.push(index.is_current ? "current" : "superseded");
  return parts.join(" · ");
}

/** The build settings line, or why there is none. */
export function indexBuildText(index: Pick<IndexVersion, "embedding_model" | "chunk_config" | "chunk_count" | "is_current">): string {
  const parts: string[] = [];
  if (index.embedding_model) parts.push(index.embedding_model);
  const chunks = chunkConfigText(index.chunk_config);
  if (chunks) parts.push(chunks);
  if (typeof index.chunk_count === "number") parts.push(`${index.chunk_count.toLocaleString("en-US")} chunks`);
  if (parts.length > 0) return parts.join(" · ");
  return index.is_current ? "Build settings were not recorded." : "Build settings are recorded for the current index only.";
}
