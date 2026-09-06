import React, { useState } from "react";
import service from "../services/service";
import { useNavigate } from "react-router-dom";
import SEO from "../components/SEO";

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const navigate = useNavigate();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !email) {
      alert("Please enter both username and email.");
      return;
    }
    service
      .signUp(email, username)
      .then((response) => {
        if (response.status !== 200 && response.status !== 201) {
          throw new Error(response.message);
        }
        const { username, email } = response.data;

        localStorage.setItem("username", username);
        localStorage.setItem("email", email);

        navigate("/");
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
        canonicalUrl="https://rag.nevatal.tech/login"
      />

      <form
        className="w-full max-w-sm border border-border p-8"
        onSubmit={handleSubmit}
      >
        <h1 className="font-serif text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          A username and email is all it takes — no password.
        </p>

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
