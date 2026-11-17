import React from "react";
import { progressFraction, progressText } from "../lib/experiments";
import type { ExperimentProgress } from "../types";

/** How far an experiment's run is, as a bar with a text equivalent. */
const ProgressBar: React.FC<{ progress: ExperimentProgress | null | undefined; label?: string; className?: string }> = ({ progress, label, className = "" }) => {
  const fraction = progressFraction(progress);
  const text = progressText(progress);
  return (
    <div className={className}>
      <div
        role="progressbar"
        aria-label={label ?? "Experiment progress"}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(fraction * 100)}
        aria-valuetext={text}
        className="h-1.5 w-full bg-muted"
      >
        <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${Math.round(fraction * 100)}%` }} />
      </div>
      {text && <p className="mt-0.5 font-mono text-[11px] text-muted-foreground tabular">{text}</p>}
    </div>
  );
};

export default ProgressBar;
