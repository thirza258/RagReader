import React, { useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom"; // Assuming React Router
import { Loader2, CheckCircle2, XCircle, Terminal } from "lucide-react";

// Types matching your Django Job model
type JobStatus = "PENDING" | "PROCESSING" | "READY" | "FAILED";

interface JobResponse {
  job_id: string;
  status: JobStatus;
  progress: number;
  error?: string;
}

const LoadingPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  
  // Retrieve job_id passed from the previous page (OpenChatView response)
  // Fallback is for testing purposes
  const jobId = location.state?.job_id || "no-job-id"; 

  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<JobStatus>("PENDING");
  const [message, setMessage] = useState("Initializing connection...");
  const [error, setError] = useState<string | null>(null);

  // Dynamic message based on progress/status
  useEffect(() => {
    if (status === "FAILED") {
      setMessage("Initialization Failed");
      return;
    }
    if (status === "READY") {
      setMessage("System Ready");
      return;
    }

    if (progress < 10) setMessage("Queuing job...");
    else if (progress < 30) setMessage("Reading documents...");
    else if (progress < 60) setMessage("Chunking and Embedding text...");
    else if (progress < 90) setMessage("Saving to Vector Store...");
    else setMessage("Finalizing setup...");
  }, [progress, status]);

  // Polling Logic
  useEffect(() => {
    if (!jobId) return;

    const pollInterval = setInterval(async () => {
      try {
        // Replace with your actual API endpoint
        // const response = await fetch(`/api/job-status/${jobId}/`); 
        
        // --- MOCK RESPONSE FOR DEMO (Remove this in production) ---
        // Simulating the backend moving from 0 to 100
        const mockResponse: JobResponse = await new Promise((resolve) => {
            // This logic just simulates the Celery task progress
            resolve({
                job_id: jobId,
                status: progress >= 100 ? "READY" : "PROCESSING",
                progress: Math.min(progress + 15, 100),
            });
        });
        const data = mockResponse;
        // -----------------------------------------------------------

        // UNCOMMENT REAL LOGIC:
        /*
        const res = await fetch(`http://localhost:8000/api/job-status/${jobId}`);
        if (!res.ok) throw new Error("Network response was not ok");
        const data = await res.json();
        */

        setStatus(data.status);
        setProgress(data.progress);

        if (data.status === "READY") {
          clearInterval(pollInterval);
          // Wait a moment for the user to see 100% before redirecting
          setTimeout(() => {
             // Navigate to your Chat UI
             console.log("Redirecting to chat...");
             // navigate("/chat"); 
          }, 800);
        } else if (data.status === "FAILED") {
          clearInterval(pollInterval);
          setError(data.error || "An unknown error occurred.");
        }

      } catch (err) {
        console.error("Polling error:", err);
        // Don't clear interval immediately on network blip, 
        // but maybe after X retries. For now, we just log.
      }
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(pollInterval);
  }, [jobId, progress, navigate]); // Added progress to dep array for the mock logic to work

  return (
    <div className="min-h-screen w-full flex flex-col items-center justify-center bg-background text-foreground p-4">
      
      {/* Main Card */}
      <div className="w-full max-w-md bg-card border border-border rounded-xl shadow-2xl overflow-hidden relative">
        
        {/* Glow Effect behind the card */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-3/4 h-2 bg-primary blur-[20px] opacity-50"></div>

        <div className="p-8 flex flex-col items-center text-center space-y-6">
          
          {/* Icon State */}
          <div className="relative">
            {status === "FAILED" ? (
              <div className="h-20 w-20 rounded-full bg-destructive/10 flex items-center justify-center border-2 border-destructive animate-in zoom-in duration-300">
                <XCircle className="h-10 w-10 text-destructive" />
              </div>
            ) : status === "READY" ? (
              <div className="h-20 w-20 rounded-full bg-green-500/10 flex items-center justify-center border-2 border-green-500 animate-in zoom-in duration-300">
                <CheckCircle2 className="h-10 w-10 text-green-500" />
              </div>
            ) : (
              <div className="h-20 w-20 rounded-full bg-muted flex items-center justify-center border border-primary/30 relative">
                <Loader2 className="h-10 w-10 text-primary animate-spin" />
                {/* Pulse ring */}
                <div className="absolute inset-0 rounded-full border border-primary opacity-0 animate-ping"></div>
              </div>
            )}
          </div>

          {/* Text Content */}
          <div className="space-y-2 z-10">
            <h2 className="text-2xl font-bold tracking-tight text-foreground">
              {message}
            </h2>
            <p className="text-sm text-muted-foreground">
              {status === "FAILED" 
                ? "Please check the logs or try again later."
                : `Job ID: ${jobId.slice(0, 8)}...`}
            </p>
          </div>

          {/* Progress Bar Container */}
          {status !== "FAILED" && (
            <div className="w-full space-y-2">
              <div className="h-3 w-full bg-muted/50 rounded-full overflow-hidden border border-border">
                <div
                  className="h-full bg-primary shadow-[0_0_10px_theme(colors.cyan.500)] transition-all duration-700 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
              <div className="flex justify-between text-xs text-muted-foreground font-mono">
                <span>RAG Initialization</span>
                <span>{progress}%</span>
              </div>
            </div>
          )}

          {/* Error Display */}
          {status === "FAILED" && error && (
            <div className="w-full bg-destructive/10 border border-destructive/20 rounded p-3 text-left">
                <p className="text-xs text-destructive font-mono break-all">
                  Error: {error}
                </p>
            </div>
          )}

          {/* Action Buttons (Only if failed or stuck) */}
          {status === "FAILED" && (
             <button 
               onClick={() => navigate(-1)}
               className="mt-4 px-4 py-2 bg-secondary hover:bg-blue-600 text-white text-sm font-medium rounded transition-colors w-full"
             >
               Go Back
             </button>
          )}
        </div>

        {/* Footer decoration */}
        <div className="bg-muted/30 p-3 border-t border-border flex items-center justify-center gap-2">
            <Terminal className="h-3 w-3 text-primary" />
            <span className="text-[10px] uppercase tracking-widest text-muted-foreground">
                System Processing
            </span>
        </div>
      </div>
    </div>
  );
};

export default LoadingPage;