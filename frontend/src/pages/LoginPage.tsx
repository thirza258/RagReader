import React, { useState } from "react";
import service from "../services/service";
import { useNavigate, useSearchParams } from "react-router-dom";
import SEO from "../components/SEO";
import { sanitizeNextPath } from "../features/auth/lib/redirect";
import { saveSession } from "../features/auth/lib/session";

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [formError, setFormError] = useState("");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Only a path on this site is followed; anything else falls back to home.
  const next = sanitizeNextPath(searchParams.get("next"));

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !email) {
      setFormError("Enter both a username and an email.");
      return;
    }
    setFormError("");
    service
      .signUp(email, username)
      .then((response) => {
        if (response.status !== 200 && response.status !== 201) {
          throw new Error(response.message);
        }
        const { username, email, token } = response.data;

        saveSession({ username, email, token });
        if (!token) {
          setFormError("Signed in, but the server did not issue an access token, so the workspace cannot be opened. Try again later.");
          return;
        }

        navigate(next ?? "/", { replace: true });
      })
      .catch((error) => {
        navigate("/error", {
          state: {
            status: error?.response?.status || 500,
            error: "Sign up failed",
            message:
              error?.response?.data?.message || error.message || "Sign up failed.",
          },
        });
      });
  };

  const field =
    "w-full border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-primary";

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <SEO
        title="Sign In — RAGReader"
        description="Sign in or register your workspace to benchmark RAG retrieval pipelines."
        canonicalUrl="https://rag.nevatal.id/login"
      />

      <form
        className="w-full max-w-sm border border-border p-8"
        onSubmit={handleSubmit}
      >
        <h1 className="font-serif text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A username and email is all it takes — no password.
        </p>
        {next && next !== "/" && (
          <p className="mt-3 border-l-2 border-primary/50 pl-3 text-sm">
            Sign in to continue where you were.
          </p>
        )}

        <div className="mt-8 space-y-5">
          <div>
            <label
              className="mb-1.5 block text-sm font-medium"
              htmlFor="username"
            >
              Username
            </label>
            <input
              id="username"
              type="text"
              className={field}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              placeholder="e.g. alex"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-sm font-medium" htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              className={field}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="alex@example.com"
            />
          </div>
        </div>

        {formError && (
          <p role="alert" className="mt-6 border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            {formError}
          </p>
        )}

        <button
          type="submit"
          className="mt-8 w-full border border-primary bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
        >
          Continue
        </button>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mt-2 w-full border border-input px-4 py-2.5 text-sm transition-colors hover:bg-accent"
        >
          Go back
        </button>
      </form>
    </div>
  );
};

export default LoginPage;
