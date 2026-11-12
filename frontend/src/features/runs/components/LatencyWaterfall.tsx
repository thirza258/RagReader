import React, { useMemo } from "react";
import { formatMs } from "../lib/runMetrics";
import { layoutWaterfall } from "../lib/waterfall";
import type { RunSpan } from "../types";

const BAR: Record<string, string> = {
  completed: "bg-primary/70",
  skipped: "bg-muted-foreground/30",
  failed: "bg-destructive",
};

interface LatencyWaterfallProps {
  spans: readonly RunSpan[];
  totalMs: number | null;
}

/**
 * Where the time went (PRD §32): one bar per span, placed by its start and
 * sized by its duration, nested spans indented. Each row also reads as text
 * ("Vector search, 3 ms, starting at 412 ms"), so the chart has a complete
 * non-visual equivalent.
 */
const LatencyWaterfall: React.FC<LatencyWaterfallProps> = ({ spans, totalMs }) => {
  const layout = useMemo(() => layoutWaterfall(spans, { totalMs }), [spans, totalMs]);
  if (layout.rows.length === 0) {
    return <p className="text-muted-foreground">No step timings were recorded for this run.</p>;
  }
  return (
    <ol className="space-y-0.5 tabular" aria-label={`Latency by step, ${formatMs(layout.scaleMs)} in total`}>
      {layout.rows.map((row) => {
        const status = row.status === "failed" ? `, failed${row.errorCode ? ` (${row.errorCode})` : ""}` : row.status === "skipped" ? ", skipped" : "";
        return (
          <li key={row.key} className="grid grid-cols-[minmax(0,10rem)_minmax(3rem,1fr)_3.75rem] items-center gap-2" title={row.detail || undefined}>
            <span className={`truncate ${row.depth === 0 ? "font-medium" : ""}`} style={{ paddingLeft: `${Math.min(row.depth, 4) * 0.75}rem` }}>
              {row.label}
              <span className="sr-only">
                , {formatMs(row.durationMs)}, starting at {formatMs(row.startMs)}
                {status}
                {row.detail ? `. ${row.detail}` : ""}
              </span>
            </span>
            <span aria-hidden="true" className="relative h-2.5 bg-muted">
              <span className={`absolute inset-y-0 ${BAR[row.status] ?? BAR.completed}`} style={{ left: `${row.offsetPct}%`, width: `${row.widthPct}%` }} />
            </span>
            <span aria-hidden="true" className={`text-right font-mono ${row.status === "failed" ? "text-destructive" : "text-muted-foreground"}`}>
              {row.status === "skipped" ? "skip" : formatMs(row.durationMs)}
            </span>
          </li>
        );
      })}
    </ol>
  );
};

export default LatencyWaterfall;
