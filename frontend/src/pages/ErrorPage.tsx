import React from "react";
import { useNavigate, useLocation } from "react-router-dom";
import type { ErrorState } from "../types/types";

const ErrorPage: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const state = location.state as ErrorState;

  const status = state?.status || 404;
  const error = state?.error || "Page not found";
  const message =
    state?.message || "We couldn't find the page you were looking for.";

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="measure w-full max-w-md border border-border p-8">
        <p className="font-mono text-sm text-muted-foreground tabular">{status}</p>
        <h1 className="mt-2 text-2xl font-semibold">{error}</h1>
        <p className="prose-note mt-3 text-base">{message}</p>
        <button
          className="mt-6 border border-primary bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
          onClick={() => navigate("/")}
        >
          Back to home
        </button>
      </div>
    </div>
  );
};

export default ErrorPage;
