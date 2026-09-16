import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import service from "../services/service";
import type { JobStatus } from "../types/types";
import { errorMessage } from "../lib/utils";

interface InitializationJob {
  job_id: string;
  status: JobStatus;
  progress: number;
  error?: string;
  error_code?: string;
}

function describeProgress(status: JobStatus, progress: number): string {
  if (status === "FAILED") return "Initialization failed";
  if (status === "READY") return "Ready";
  if (progress < 10) return "Queueing the job";
  if (progress < 30) return "Reading the document";
  if (progress < 60) return "Chunking and embedding";
  if (progress < 90) return "Building the indexes";
  return "Finishing up";
}

const LoadingPage: React.FC = () => {
  const navigate = useNavigate();
  const username = localStorage.getItem("username");
  const [job, setJob] = useState<InitializationJob | null>(null);
  const jobRef = useRef<InitializationJob | null>(null);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [attempt, setAttempt] = useState(0);
  const retryInitialization = useRef(false);
  const initializationRequest = useRef<{ attempt: number; username: string; promise: ReturnType<typeof service.openChat> } | null>(null);

  useEffect(() => {
    if (!username) {
      navigate("/error", { state: { status: 401, error: "Unauthorized", message: "Please login to continue." } });
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let failures = 0;
    const startingJob = jobRef.current;
    const retry = retryInitialization.current;
    retryInitialization.current = false;

    function acceptJob(next: InitializationJob) {
      if (!next?.job_id || !["PENDING", "PROCESSING", "READY", "FAILED"].includes(next.status)) {
        throw new Error("The server returned an invalid initialization status. Try checking again.");
      }
      if (cancelled) return;
      jobRef.current = next;
      setJob(next);
      if (next.status === "FAILED") {
        setError(next.error || "Document initialization failed. Try again.");
        setErrorCode(next.error_code || "initialization_failed");
      } else if (next.status === "READY") {
        timer = setTimeout(() => { if (!cancelled) navigate("/chat"); }, 500);
      } else {
        timer = setTimeout(() => { void poll(next.job_id); }, 2000);
      }
    }

    async function poll(jobId: string) {
      try {
        const response = await service.getJobStatus(jobId);
        if (cancelled) return;
        if (response?.data?.job_id !== jobId) throw new Error("The server returned a different job ID. Try checking again.");
        failures = 0;
        acceptJob(response.data);
      } catch (err) {
        if (cancelled) return;
        const code = (err as { response?: { status?: number } })?.response?.status;
        if ((!code || code >= 500 || code === 429) && ++failures < 3) {
          timer = setTimeout(() => { void poll(jobId); }, 2000 * failures);
          return;
        }
        setError(errorMessage(err, "Could not check initialization. Check the connection and try again."));
      }
    }

    async function start() {
      try {
        if (startingJob && !retry) {
          await poll(startingJob.job_id);
          return;
        }
        // React remounts effects during development. Both effect instances
        // follow the same request, so the accepted job cannot be lost.
        if (initializationRequest.current?.attempt !== attempt || initializationRequest.current.username !== username) {
          initializationRequest.current = { attempt, username: username!, promise: service.openChat(username!, retry) };
        }
        const response = await initializationRequest.current.promise;
        if (!cancelled) acceptJob(response?.data);
      } catch (err) {
        if (cancelled) return;
        const payload = (err as { response?: { data?: { data?: InitializationJob; error_code?: string } } })?.response?.data;
        if (payload?.data?.job_id) {
          jobRef.current = payload.data;
          setJob(payload.data);
        }
        setError(errorMessage(err, "Failed to start document initialization."));
        setErrorCode(payload?.error_code || "");
      }
    }
    void start();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [username, navigate, attempt]);

  const status = job?.status ?? "PENDING";
  const progress = Math.max(0, Math.min(100, job?.progress ?? 0));
  const message = error && status !== "FAILED" ? "Initialization needs attention" : describeProgress(status, progress);

  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center bg-background px-6 text-foreground">
      <div className="w-full max-w-md border border-border p-8">
        <div className="flex items-baseline gap-3">
          {!error && (status === "PENDING" || status === "PROCESSING") && <Loader2 aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin text-muted-foreground" />}
          <h1 className="text-xl font-semibold">{message}</h1>
        </div>
        <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{job ? `Job ${job.job_id}` : "Job pending"}</p>
        {!error && (
          <div className="mt-6">
            <div role="progressbar" aria-label="Document initialization" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} className="h-[3px] w-full overflow-hidden bg-muted">
              <div className="h-full bg-foreground/60 transition-all duration-700 ease-out" style={{ width: `${progress}%` }} />
            </div>
            <div className="mt-2 flex justify-between text-xs text-muted-foreground"><span>Indexing the document</span><span className="font-mono tabular">{progress}%</span></div>
          </div>
        )}
        {error && (
          <>
            <div role="alert" className="mt-6 border border-destructive/30 bg-destructive/5 p-3">
              <p className="text-sm text-destructive">{error}</p>
              {errorCode && <p className="mt-2 break-all font-mono text-xs text-muted-foreground">Error code: {errorCode}</p>}
            </div>
            <button onClick={() => {
              retryInitialization.current = jobRef.current?.status === "FAILED";
              setError("");
              setErrorCode("");
              setAttempt((value) => value + 1);
            }} className="mt-4 w-full bg-primary px-4 py-2.5 text-sm text-primary-foreground">
              {status === "FAILED" ? "Retry initialization" : "Check again"}
            </button>
            <button onClick={() => navigate(-1)} className="mt-3 w-full border border-input px-4 py-2.5 text-sm transition-colors hover:bg-accent">Go back</button>
          </>
        )}
      </div>
    </div>
  );
};

export default LoadingPage;
