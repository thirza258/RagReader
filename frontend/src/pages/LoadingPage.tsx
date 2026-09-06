import React, { useEffect, useState, useRef } from "react";
import { useNavigate } from "react-router-dom"; 
import { Loader2 } from "lucide-react";
import service from "../services/service";
import  type { JobStatus } from "../types/types";
import { errorMessage } from "../lib/utils";


/** What to show above the progress bar, derived from the job's own state. */
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

  const [jobId, setJobId] = useState<string | null>(null);

  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<JobStatus>("PENDING");
  const [error, setError] = useState<string | null>(null);

  const message = describeProgress(status, progress);

  
  const username = localStorage.getItem("username");

  useEffect(() => {
    if (!username) {
      navigate("/error", {
        state: {
          status: 401,
          error: "Unauthorized",
          message: "Please login to continue.",
        },
      });
    }
  }, [username, navigate]);

    const startedRef = useRef(false);

    useEffect(() => {
      if (!username || startedRef.current) return;
      startedRef.current = true;
    
      const startChat = async () => {
        try {
          const response = await service.openChat(username);
          if (response?.status !== 202 && response?.status !== 200) {
            throw new Error(response?.message || "Failed to start chat initialization");
          }

          const job = response?.data;
          if (!job?.job_id) {
            throw new Error(response?.message || "Invalid open-chat response: Job ID missing");
          }
    
          setJobId(job.job_id);
          setStatus(job.status || "PENDING");
          setProgress(job.progress || 0);

        } catch (err) {
          console.error("Open chat failed:", err);
          setError(errorMessage(err, "Failed to start chat initialization"));
          // `message` is derived from status, so setting FAILED is enough.
          setStatus("FAILED");
        }
      };
    
      startChat();
    }, [username]);
  

  useEffect(() => {
    if (!jobId) return;
  
    const pollInterval = setInterval(async () => {
      try {
        const response = await service.getJobStatus(jobId);
  
        const job = response?.data;
        if (!job) throw new Error("Invalid job status payload");
  
        setStatus(job.status);
        setProgress(job.progress);
  
        if (job.status === "READY") {
          clearInterval(pollInterval);
  
          setTimeout(() => {
            console.log("Redirecting to chat...");
            navigate("/chat");
          }, 800);
  
        } else if (job.status === "FAILED") {
          clearInterval(pollInterval);
          setStatus("FAILED");
          setError(job.error || "Initialization failed");
        }
  
      } catch (err) {
        console.error("Polling error:", err);
      }
    }, 2000);
  
    return () => clearInterval(pollInterval);
  }, [jobId, navigate]);

  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center bg-background px-6 text-foreground">
      <div className="w-full max-w-md border border-border p-8">
        <div className="flex items-baseline gap-3">
          {status === "PENDING" || status === "PROCESSING" ? (
            <Loader2
              aria-hidden="true"
              className="h-4 w-4 shrink-0 animate-spin text-muted-foreground"
            />
          ) : null}
          <h1 className="text-xl font-semibold">{message}</h1>
        </div>

        <p className="mt-2 font-mono text-xs text-muted-foreground">
          {jobId ? `Job ${jobId.slice(0, 8)}` : "Job pending"}
        </p>

        {status !== "FAILED" && (
          <div className="mt-6">
            <div className="h-[3px] w-full overflow-hidden bg-muted">
              <div
                className="h-full bg-foreground/60 transition-all duration-700 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="mt-2 flex justify-between text-xs text-muted-foreground">
              <span>Indexing the document</span>
              <span className="font-mono tabular">{progress}%</span>
            </div>
          </div>
        )}

        {status === "FAILED" && (
          <>
            {error && (
              <div className="mt-6 border border-destructive/30 bg-destructive/5 p-3">
                <p className="break-all font-mono text-xs text-destructive">
                  {error}
                </p>
              </div>
            )}
            <p className="mt-4 text-sm text-muted-foreground">
              Check the logs, or try again.
            </p>
            <button
              onClick={() => navigate(-1)}
              className="mt-4 w-full border border-input px-4 py-2.5 text-sm transition-colors hover:bg-accent"
            >
              Go back
            </button>
          </>
        )}
      </div>
    </div>
  );
};

export default LoadingPage;