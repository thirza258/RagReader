/**
 * Layout of a run's latency waterfall (PRD §32): one row per span, in tree
 * order, each bar placed by its start and sized by its duration relative to
 * the scale. The scale is the larger of the run's total and the latest span
 * end — the stored answer is saved after `total` is measured, so the last
 * span may end after it. Pure, so the arithmetic is tested.
 */

export interface WaterfallSpan {
  name: string;
  label?: string | null;
  status?: string | null;
  start_ms?: number | null;
  duration_ms?: number | null;
  detail?: string | null;
  error_code?: string | null;
  children?: readonly WaterfallSpan[] | null;
}

export interface WaterfallRow {
  key: string;
  name: string;
  label: string;
  depth: number;
  status: string;
  startMs: number;
  durationMs: number;
  endMs: number;
  /** Left edge of the bar, 0–100. */
  offsetPct: number;
  /** Width of the bar, 0–100; offset + width never exceeds 100. */
  widthPct: number;
  detail: string;
  errorCode: string | null;
}

export interface WaterfallLayout {
  scaleMs: number;
  rows: WaterfallRow[];
}

export interface WaterfallOptions {
  /** The run's total latency, if known. */
  totalMs?: number | null;
  /** Smallest visible bar, so a 0.2 ms step is still drawn. */
  minWidthPct?: number;
}

function finite(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function round(value: number): number {
  return Math.round(value * 1000) / 1000;
}

/** Spans in pre-order (children by start time), with their depth. */
export function flattenSpans(spans: readonly WaterfallSpan[] | null | undefined): { span: WaterfallSpan; depth: number; key: string }[] {
  const out: { span: WaterfallSpan; depth: number; key: string }[] = [];
  const visit = (list: readonly WaterfallSpan[], depth: number, prefix: string) => {
    const ordered = list.map((span, index) => ({ span, index })).sort((a, b) => finite(a.span.start_ms) - finite(b.span.start_ms) || a.index - b.index);
    for (const { span, index } of ordered) {
      const key = prefix ? `${prefix}.${index}` : String(index);
      out.push({ span, depth, key });
      if (span.children && span.children.length > 0) visit(span.children, depth + 1, key);
    }
  };
  visit(spans ?? [], 0, "");
  return out;
}

export function layoutWaterfall(spans: readonly WaterfallSpan[] | null | undefined, options: WaterfallOptions = {}): WaterfallLayout {
  const minWidth = Math.max(0, Math.min(100, options.minWidthPct ?? 0.5));
  const flat = flattenSpans(spans);
  const latestEnd = flat.reduce((max, { span }) => Math.max(max, finite(span.start_ms) + finite(span.duration_ms)), 0);
  const scaleMs = Math.max(finite(options.totalMs), latestEnd);
  const rows = flat.map(({ span, depth, key }) => {
    const startMs = finite(span.start_ms);
    const durationMs = finite(span.duration_ms);
    let offsetPct = scaleMs > 0 ? Math.min(100, (startMs / scaleMs) * 100) : 0;
    const widthPct = Math.min(100, Math.max(minWidth, scaleMs > 0 ? (durationMs / scaleMs) * 100 : 0));
    if (offsetPct + widthPct > 100) offsetPct = Math.max(0, 100 - widthPct);
    return {
      key,
      name: span.name,
      label: span.label || span.name,
      depth,
      status: span.status || "completed",
      startMs,
      durationMs,
      endMs: startMs + durationMs,
      offsetPct: round(offsetPct),
      widthPct: round(widthPct),
      detail: span.detail || "",
      errorCode: span.error_code || null,
    };
  });
  return { scaleMs, rows };
}
