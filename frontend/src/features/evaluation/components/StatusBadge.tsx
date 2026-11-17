import React from "react";
import { Loader2 } from "lucide-react";
import { isActive, statusLabel } from "../lib/experiments";

const TONES: Record<string, string> = {
  draft: "border-border text-muted-foreground",
  queued: "border-border text-foreground",
  running: "border-primary/40 text-foreground",
  completed: "border-status-success/40 text-status-success",
  failed: "border-destructive/40 text-destructive",
  cancelled: "border-border text-muted-foreground",
};

/** An experiment's status, spinning while the worker owns it. */
const StatusBadge: React.FC<{ status: string }> = ({ status }) => (
  <span className={`inline-flex items-center gap-1 border px-1.5 py-0.5 text-[11px] font-medium ${TONES[status] ?? "border-border"}`}>
    {isActive(status) && <Loader2 aria-hidden="true" className="h-3 w-3 animate-spin" />}
    {statusLabel(status)}
  </span>
);

export default StatusBadge;
