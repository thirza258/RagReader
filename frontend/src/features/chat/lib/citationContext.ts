import { createContext } from "react";
import type { Evidence } from "../types";

export interface CitationContextValue {
  /** Sources of the answer being rendered, by `[n]`. */
  sources: ReadonlyMap<number, Evidence>;
  onOpen: (source: Evidence) => void;
}

/** Lets the markdown renderer's citation buttons reach the answer's sources. */
export const CitationContext = createContext<CitationContextValue | null>(null);
