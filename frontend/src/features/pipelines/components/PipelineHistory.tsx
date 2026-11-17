import React, { useEffect, useState } from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import { buttonOutline } from "../../../components/ui/classes";
import { toApiError, type ApiRequestError } from "../../../services/api/errors";
import { formatDateTime } from "../../documents/lib/format";
import { listPipelineVersions } from "../api/pipelines";
import { describeConfig, versionHistory } from "../lib/pipelineConfig";
import type { PipelineVersion } from "../types";

interface PipelineHistoryProps {
  pipelineId: number;
  /** Changes when the pipeline gains a version, so the list is re-read. */
  latestVersionId: number;
}

/**
 * Every version of a pipeline, newest first, each with what changed from
 * the one before it (PRD §19). Versions never change, so an answer's
 * "v2" always means the configuration shown here.
 */
const PipelineHistory: React.FC<PipelineHistoryProps> = ({ pipelineId, latestVersionId }) => {
  const [state, setState] = useState<{ key: string; versions: PipelineVersion[]; error: ApiRequestError | null } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const key = `${pipelineId}:${latestVersionId}:${attempt}`;

  useEffect(() => {
    const controller = new AbortController();
    listPipelineVersions(pipelineId, controller.signal).then(
      (versions) => setState({ key, versions, error: null }),
      (error) => {
        if (!controller.signal.aborted) setState({ key, versions: [], error: toApiError(error) });
      },
    );
    return () => controller.abort();
  }, [pipelineId, key]);

  if (!state || state.key !== key) {
    return (
      <p role="status" className="text-muted-foreground">
        Loading versions…
      </p>
    );
  }
  if (state.error) {
    return (
      <ErrorNotice
        title="Could not load the versions"
        code={state.error.code}
        message={state.error.message}
        actions={
          <button type="button" className={buttonOutline} onClick={() => setAttempt((value) => value + 1)}>
            Try again
          </button>
        }
      />
    );
  }
  return (
    <ol className="space-y-2" aria-label="Versions, newest first">
      {versionHistory(state.versions).map(({ version, changes, initial }) => (
        <li key={version.id} className="border-l-2 border-border pl-2">
          <p className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-medium">v{version.number}</span>
            <span className="text-[11px] text-muted-foreground">{formatDateTime(version.created_at)}</span>
          </p>
          <p className="mt-0.5 text-muted-foreground">{describeConfig(version.config)}</p>
          {initial ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground">First version.</p>
          ) : changes.length === 0 ? (
            <p className="mt-0.5 text-[11px] text-muted-foreground">No setting changed.</p>
          ) : (
            <ul className="mt-0.5 space-y-0.5" aria-label={`Changes in v${version.number}`}>
              {changes.map((change) => (
                <li key={change.key} className="font-mono text-[11px]">
                  <span className="font-sans text-muted-foreground">{change.label}:</span> <del className="text-muted-foreground">{change.from}</del>{" "}
                  <span aria-hidden="true">→</span>
                  <span className="sr-only">changed to</span> <ins className="no-underline">{change.to}</ins>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground" title="Configuration hash">
            {version.config_hash.slice(0, 12)}
          </p>
        </li>
      ))}
    </ol>
  );
};

export default PipelineHistory;
