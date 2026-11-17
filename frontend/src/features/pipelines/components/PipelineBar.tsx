import React from "react";
import { SlidersHorizontal } from "lucide-react";
import { buttonQuiet, inputSmall } from "../../../components/ui/classes";
import { describeConfig, pipelineVersionLabel } from "../lib/pipelineConfig";
import type { Pipeline } from "../types";

interface PipelineBarProps {
  pipelines: Pipeline[];
  loaded: boolean;
  selectedId: number | null;
  busy: boolean;
  onSelect: (id: number) => void;
  onConfigure: () => void;
}

/** The chat header's pipeline line: which pipeline (and version) answers, switchable in place. */
const PipelineBar: React.FC<PipelineBarProps> = ({ pipelines, loaded, selectedId, busy, onSelect, onConfigure }) => {
  const selected = pipelines.find((pipeline) => pipeline.id === selectedId) ?? pipelines.find((pipeline) => pipeline.is_default) ?? null;
  return (
    <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-xs">
      <label htmlFor="chat-pipeline" className="shrink-0 text-muted-foreground">
        Pipeline
      </label>
      <select
        id="chat-pipeline"
        className={`${inputSmall} min-w-0 flex-1 py-0.5 text-xs`}
        value={selected?.id ?? ""}
        disabled={!loaded || busy || pipelines.length === 0}
        title={selected ? describeConfig(selected.version.config) : undefined}
        onChange={(event) => onSelect(Number(event.target.value))}
      >
        {!loaded && <option value="">Loading…</option>}
        {pipelines.map((pipeline) => (
          <option key={pipeline.id} value={pipeline.id}>
            {pipelineVersionLabel({ name: pipeline.name, number: pipeline.version.number })}
          </option>
        ))}
      </select>
      <button type="button" className={buttonQuiet} onClick={onConfigure}>
        <SlidersHorizontal aria-hidden="true" className="h-3.5 w-3.5" />
        Configure
      </button>
    </div>
  );
};

export default PipelineBar;
