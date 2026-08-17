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
    service.signUp(email, username)
      .then(response => {
        if (response.status !== 200 && response.status !== 201) {
          throw new Error(response.message);
        }
        const { username, email } = response.data;

        localStorage.setItem("username", username);
        localStorage.setItem("email", email);

        navigate("/");
      })
      .catch(error => {
        navigate("/error", {
          state: {
            status: error?.response?.status || 500,
            error: "Sign Up Failed",
            message: error?.response?.data?.message || error.message || "Sign up failed."
          }
        });
      });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-950 px-4">
      <SEO
        title="Sign In — RAGReader"
        description="Sign in or register your workspace to benchmark RAG retrieval pipelines."
        canonicalUrl="https://rag.nevatal.tech/login"
      />

      <form
        className="bg-slate-900 p-8 rounded-2xl shadow-2xl w-full max-w-sm space-y-4 border border-slate-800"
        onSubmit={handleSubmit}
      >
        <h1 className="text-2xl font-bold text-center text-white">Welcome Back!</h1>
        <p className="text-xs text-center text-slate-400 font-mono">RAGReader workspace sign in</p>
        <div className="w-full h-px bg-slate-800 my-4"></div>
        <div>
          <label className="block mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300" htmlFor="username">
            Username
          </label>
          <input
            id="username"
            type="text"
            className="w-full border border-slate-700 rounded-xl p-2.5 bg-slate-800 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="username"
            placeholder="e.g. alex"
          />
        </div>
        <div>
          <label className="block mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            className="w-full border border-slate-700 rounded-xl p-2.5 bg-slate-800 text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-cyan-500 text-sm"
            value={email}
            onChange={e => setEmail(e.target.value)}
            autoComplete="email"
            placeholder="alex@example.com"
          />
        </div>
        <button
          type="submit"
          className="w-full bg-cyan-600 hover:bg-cyan-500 text-white py-2.5 rounded-xl font-medium transition-colors text-sm shadow-md shadow-cyan-600/20"
        >
          Sign In
        </button>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="w-full bg-slate-800 hover:bg-slate-700 text-slate-300 py-2.5 rounded-xl transition-colors text-sm"
        >
          Go Back
        </button>
      </form>
    </div>
  );
};

export default LoginPage;
