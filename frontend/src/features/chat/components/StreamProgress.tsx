import React from "react";
import { progressLines, type ProgressState, type StreamingTurn } from "../lib/chatStream";

const GLYPH: Record<ProgressState, string> = { done: "✓", active: "●", skipped: "–", failed: "✕" };
const GLYPH_CLASS: Record<ProgressState, string> = {
  done: "text-status-success",
  active: "text-primary motion-safe:animate-pulse",
  skipped: "text-muted-foreground",
  failed: "text-destructive",
};

/**
 * The live retrieval/generation steps of a streaming answer (PRD §16), e.g.
 * "✓ Retrieved 20 candidates ✓ Selected 5 passages ● Generating answer…".
 * Announced politely, so screen readers hear each step once.
 */
const StreamProgress: React.FC<{ turn: StreamingTurn }> = ({ turn }) => {
  const lines = progressLines(turn);
  if (lines.length === 0) return null;
  return (
    <div role="status" aria-live="polite" className="mb-2">
      <ul className="space-y-0.5 text-xs">
        {lines.map((line) => (
          <li key={line.key} className={`flex gap-2 ${line.state === "active" ? "font-medium text-foreground" : "text-muted-foreground"}`}>
            <span aria-hidden="true" className={`w-3 shrink-0 text-center ${GLYPH_CLASS[line.state]}`}>
              {GLYPH[line.state]}
            </span>
            <span>{line.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default StreamProgress;
