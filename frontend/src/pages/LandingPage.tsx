import React, { useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Braces,
  Database,
  Gauge,
  Github,
  Layers,
  Library,
  Scale,
  Settings2,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Zap,
} from "lucide-react";
import service from "../services/service";
import { Link, useNavigate } from "react-router-dom";
import { SubmitPayload } from "../types/types";
import { AxiosError } from "axios";

import FileSubmit from "../components/FileSubmit";
import SEO from "../components/SEO";
import InteractiveBenchmarkSimulator from "../components/landing/InteractiveBenchmarkSimulator";
import GroundTruthVisualizer from "../components/landing/GroundTruthVisualizer";
import ArchitectureFlow from "../components/landing/ArchitectureFlow";
import ComparisonMatrix from "../components/landing/ComparisonMatrix";
import QuickStartCode from "../components/landing/QuickStartCode";
import BackToTop from "../components/landing/BackToTop";

const REPO_URL = "https://github.com/thirza258/RagReader";

const RETRIEVAL_METHODS = [
  {
    name: "Dense retrieval",
    icon: Database,
    accent: "bg-blue-500/10 text-blue-400 ring-blue-500/20",
    summary: "Semantic vector search over embeddings.",
    detail:
      "Every chunk is embedded with openai/text-embedding-3-small and ranked by cosine similarity against the embedded query. This is also the method that answers in the normal chat.",
  },
  {
    name: "Sparse retrieval",
    icon: Library,
    accent: "bg-purple-500/10 text-purple-400 ring-purple-500/20",
    summary: "BM25 keyword search.",
    detail:
      "BM25Okapi over a corpus that is lowercased, stripped of punctuation and filtered through NLTK's English stopword list. Exact terms, names and numbers survive here even when embeddings blur them.",
  },
  {
    name: "Hybrid retrieval",
    icon: Layers,
    accent: "bg-pink-500/10 text-pink-400 ring-pink-500/20",
    summary: "Dense + sparse candidates, reranked by a cross-encoder.",
    detail:
      "Both engines contribute candidates (at least 10 each), duplicates are dropped, and the cross-encoder/ms-marco-MiniLM-L6-v2 reranker scores every survivor against the query before the top-K is cut.",
  },
];

const MODELS = [
  { label: "GPT-4o mini", id: "openai/gpt-4o-mini", provider: "OpenAI" },
  { label: "Gemini 3 Flash", id: "google/gemini-3-flash-preview", provider: "Google" },
  { label: "Claude Haiku 4.5", id: "anthropic/claude-haiku-4.5", provider: "Anthropic" },
];

const SUPPORTING_MODELS = [
  {
    role: "Embeddings",
    id: "openai/text-embedding-3-small",
    note: "Vectors for dense retrieval and for hybrid's dense half.",
  },
  {
    role: "Reranker",
    id: "cross-encoder/ms-marco-MiniLM-L6-v2",
    note: "The cross-encoder that makes hybrid different from dense + sparse.",
  },
  {
    role: "Evaluation judge",
    id: "mistralai/mistral-nemo",
    note: "Scores faithfulness, answer relevance and answer coverage.",
  },
];

const RETRIEVAL_METRICS = [
  {
    name: "Precision@K",
    body: "Of the chunks this pipeline retrieved, the share that are in the ground-truth set.",
  },
  {
    name: "Recall@K",
    body: "Of the ground-truth chunks, the share this pipeline managed to retrieve.",
  },
  {
    name: "F1@K",
    body: "Harmonic mean of the two — one number for retrieval quality.",
  },
];

const ANSWER_METRICS = [
  {
    name: "ROUGE-L (precision / recall / F1)",
    body: "Longest-common-subsequence overlap between the generated answer and the answer you said you expected.",
  },
  {
    name: "Faithfulness",
    body: "Is every claim in the answer supported by the retrieved chunks, or did the model invent some of it?",
  },
  {
    name: "Answer relevance",
    body: "How well the answer speaks to the context that was actually retrieved.",
  },
  {
    name: "Answer coverage",
    body: "Whether the answer uses the important information in the chunks, or leaves most of it on the floor.",
  },
];

const CONFIGURABLE = [
  { label: "Retrieval methods", value: "Any subset of dense, sparse, hybrid" },
  { label: "Models", value: "Any subset of the three LLMs" },
  { label: "Retrieval depth (Top-K)", value: "1–20, default 5 — the same K as in Precision@K" },
  { label: "Ground truth", value: "Manual selection or candidate pooling" },
  { label: "Pool depth", value: "1–50, default 10 — deeper than Top-K on purpose" },
];

const STACK = [
  { name: "OpenRouter", note: "Every LLM and embedding call, one API key" },
  { name: "Django + DRF", note: "REST API and persistence" },
  { name: "Channels + Daphne", note: "WebSocket streaming of analysis results" },
  { name: "Celery + Redis", note: "Indexing and analysis run as background jobs" },
  { name: "PostgreSQL", note: "Documents, chunks, batches, results" },
  { name: "rank-bm25 + NLTK", note: "Sparse retrieval and tokenization" },
  { name: "sentence-transformers", note: "Cross-encoder reranking" },
  { name: "rouge-score", note: "ROUGE-L scoring" },
  { name: "React + Vite + Tailwind", note: "This interface" },
];

const FAQ = [
  {
    q: "What does RAGReader actually do?",
    a: "You add a document, ask a question, and get an answer from dense retrieval. Clicking that answer opens a deep analysis that re-runs the same question through every combination of retrieval method and LLM you selected — up to nine pipelines — and scores each one against ground truth.",
  },
  {
    q: "What can I upload?",
    a: "A PDF file, a web page URL (the HTML is fetched and reduced to text), or text pasted straight into the form. One source at a time.",
  },
  {
    q: "Do I need my own API keys?",
    a: "Not on the hosted app. If you self-host, one OPENROUTER_API_KEY covers every model — the LLMs, the embeddings and the evaluation judge all go through OpenRouter.",
  },
  {
    q: "Why nine pipelines?",
    a: "Three retrieval methods times three LLMs. Narrow either axis in the deep-analysis sidebar and the run gets smaller; the configuration you used is stored with the batch, so a result always records how it was produced.",
  },
  {
    q: "Is this a benchmark I can cite?",
    a: "It's a comparison on your document with your ground truth, which is exactly what a public benchmark can't give you — and exactly why the numbers aren't transferable. Retrieval metrics are set overlap rather than rank-aware, and three of the answer metrics come from a single judge model.",
  },
  {
    q: "Is it open source?",
    a: "Yes — MIT licensed, on GitHub, and it runs locally with Docker Compose.",
  },
];

const Card = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => (
  <div
    className={`bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6 hover:border-cyan-500/30 transition-all duration-300 group ${className}`}
  >
    {children}
  </div>
);

const SectionHeading = ({
  id,
  eyebrow,
  title,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  children?: React.ReactNode;
}) => (
  <div className="max-w-3xl mb-12">
    <p className="text-xs font-semibold uppercase tracking-[0.2em] text-cyan-400 mb-3">
      {eyebrow}
    </p>
    <h2 id={id} className="text-3xl lg:text-4xl font-bold text-white mb-4 tracking-tight">
      {title}
    </h2>
    {children ? (
      <p className="text-lg text-slate-400 leading-relaxed">{children}</p>
    ) : null}
  </div>
);

const Caveat = ({ children }: { children: React.ReactNode }) => (
  <div className="flex gap-4 rounded-2xl border border-amber-500/20 bg-amber-500/5 p-6">
    <AlertTriangle className="w-5 h-5 shrink-0 text-amber-400 mt-0.5" />
    <p className="text-sm text-amber-100/80 leading-relaxed">{children}</p>
  </div>
);

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0);

  const handleSubmit = async (payload: SubmitPayload) => {
    const username = localStorage.getItem("username");
    if (!username) {
      navigate("/login");
      return;
    }
    try {
      switch (payload.type) {
        case "file":
          await service.submitFile(payload.file, username);
          break;

        case "url":
          await service.submitURL(payload.url, username);
          break;

        case "text":
          await service.submitText(payload.text, username);
          break;
      }
      navigate("/loading");
    } catch (error) {
      navigate("/error", {
        state: {
          status:
            error instanceof AxiosError && error.response?.status
              ? error.response.status
              : 500,
          error: "Failed to submit",
          message:
            error instanceof AxiosError
              ? error.response?.data?.message ||
                error.message ||
                "Failed to submit."
              : (error as Error)?.message || "Failed to submit.",
        },
      });
    }
  };

  const toggleFaq = (idx: number) => {
    setOpenFaqIndex(openFaqIndex === idx ? null : idx);
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-cyan-500/30 overflow-x-hidden">
      {/* SEO Metadata */}
      <SEO
        title="RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines"
        description="Ask questions about your own PDF, URL, or pasted text, then score the answer across 9 RAG pipelines — Dense, Sparse and Hybrid retrieval x three LLMs."
        canonicalUrl="https://rag.nevatal.tech/"
      />

      <main>
        {/* --- Hero Section --- */}
        <section id="top" className="relative pt-24 pb-20 lg:pt-32 overflow-hidden">
          <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[500px] bg-blue-600/20 rounded-full blur-[140px] -z-10" />
          <div className="absolute bottom-0 right-0 w-[800px] h-[600px] bg-cyan-600/10 rounded-full blur-[120px] -z-10" />

          <div className="container mx-auto px-6 grid lg:grid-cols-2 gap-12 items-start">
            <div className="space-y-8">
              <span className="inline-flex items-center gap-2 rounded-full border border-cyan-500/30 bg-cyan-500/10 px-4 py-1.5 text-xs font-semibold text-cyan-300 shadow-sm shadow-cyan-500/10">
                <Sparkles className="w-3.5 h-3.5" />
                Dense · Sparse · Hybrid, measured on your own document
              </span>

              <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold leading-tight text-white tracking-tight">
                Stop guessing which RAG pipeline answers your document best
              </h1>

              <p className="text-lg text-slate-400 leading-relaxed">
                RAGReader answers your question straight away with dense
                retrieval. Then, on one click, it re-runs the <em>same</em>{" "}
                question through up to nine pipelines — three retrieval methods
                across three LLMs — and reports nine scores for each, so the
                comparison is evidence rather than intuition.
              </p>

              <dl className="grid grid-cols-3 gap-4 max-w-lg">
                {[
                  { k: "3 × 3", v: "retrievers × LLMs" },
                  { k: "9", v: "scores per pipeline" },
                  { k: "Live", v: "WebSocket stream" },
                ].map((stat) => (
                  <div
                    key={stat.v}
                    className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 backdrop-blur-sm"
                  >
                    <dt className="sr-only">{stat.v}</dt>
                    <dd>
                      <span className="block text-2xl font-bold text-cyan-400">
                        {stat.k}
                      </span>
                      <span className="block text-xs text-slate-500 mt-1 font-medium">
                        {stat.v}
                      </span>
                    </dd>
                  </div>
                ))}
              </dl>

              {/* Submit Document Card */}
              <div className="p-1 bg-gradient-to-r from-slate-800 via-cyan-900/40 to-slate-900 rounded-2xl border border-slate-700/80 shadow-2xl">
                <div className="bg-slate-950 rounded-xl p-5">
                  <p className="mb-1 text-xs text-cyan-400 font-semibold uppercase tracking-wider">
                    Start your analysis
                  </p>
                  <p className="mb-3 text-xs text-slate-400">
                    One source at a time: a PDF, a web page URL, or pasted text.
                  </p>
                  <FileSubmit onSubmit={handleSubmit} />
                </div>
              </div>

              <p className="text-sm text-slate-500 flex items-center gap-1.5">
                New here?{" "}
                <Link to="/docs" className="text-cyan-400 hover:text-cyan-300 font-medium underline underline-offset-4">
                  Walk through the whole flow in screenshots
                </Link>{" "}
                first.
              </p>
            </div>

            {/* Illustrative Result Card */}
            <div className="relative lg:mt-4">
              <figure className="relative z-10 bg-slate-900/90 border border-slate-700/80 rounded-2xl p-5 shadow-2xl backdrop-blur-xl">
                <div className="flex items-center justify-between border-b border-slate-700/80 pb-3 mb-4">
                  <div className="flex items-center gap-3">
                    <div className="flex gap-1.5">
                      <div className="w-3 h-3 rounded-full bg-red-500/80" />
                      <div className="w-3 h-3 rounded-full bg-yellow-500/80" />
                      <div className="w-3 h-3 rounded-full bg-green-500/80" />
                    </div>
                    <div className="text-white font-semibold text-sm">
                      Hybrid Retrieval —{" "}
                      <span className="text-cyan-400">Claude Haiku 4.5</span>
                    </div>
                  </div>
                  <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/40">
                    Live Result
                  </span>
                </div>

                <div className="space-y-3 text-xs">
                  <div className="bg-slate-950/80 p-3.5 rounded-xl border border-slate-800">
                    <div className="text-[10px] text-slate-400 mb-1 uppercase tracking-wider font-mono">
                      Query
                    </div>
                    <div className="text-white text-xs font-semibold">
                      What happened in the Battle of Surabaya?
                    </div>
                  </div>

                  <div className="bg-slate-950/80 p-3.5 rounded-xl border border-slate-800">
                    <div className="text-[10px] text-slate-400 mb-1 uppercase tracking-wider font-mono">
                      Generated Answer
                    </div>
                    <div className="text-slate-200 leading-relaxed">
                      In November 1945 Indonesian militias in Surabaya fought
                      British-led Allied troops. The battle caused heavy
                      casualties and is commemorated annually as Heroes' Day.
                    </div>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[10px] text-slate-400 uppercase tracking-wider font-mono">
                      Retrieved Context Chunks
                    </div>
                    {[
                      {
                        n: 1,
                        score: "91.4%",
                        text: "The Battle of Surabaya occurred in November 1945 and involved Indonesian militias resisting British-led Allied troops.",
                      },
                      {
                        n: 2,
                        score: "77.0%",
                        text: "The conflict resulted in heavy casualties and is commemorated annually as Heroes' Day in Indonesia.",
                      },
                    ].map((chunk) => (
                      <div
                        key={chunk.n}
                        className="bg-slate-950/60 rounded-lg border border-slate-800 overflow-hidden"
                      >
                        <div className="flex items-center justify-between px-3 py-1 border-b border-slate-800 bg-slate-900/50">
                          <span className="text-cyan-400 font-mono text-[10px]">
                            chunk #{chunk.n}
                          </span>
                          <span className="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-emerald-950 text-emerald-400 border border-emerald-800/40">
                            Retrieval Score: {chunk.score}
                          </span>
                        </div>
                        <div className="px-3 py-2 text-[11px] text-slate-300 leading-relaxed">
                          {chunk.text}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="bg-slate-950/80 rounded-xl border border-slate-800 overflow-hidden">
                    <div className="px-3 py-1.5 border-b border-slate-800 bg-slate-900/50 text-[10px] text-slate-400 uppercase tracking-wider font-mono font-semibold">
                      Chunk Evaluation
                    </div>
                    <div className="grid grid-cols-3 gap-px bg-slate-800">
                      {[
                        ["Precision@K", "60.0%"],
                        ["Recall@K", "75.0%"],
                        ["F1@K", "66.7%"],
                      ].map(([label, value]) => (
                        <div key={label} className="bg-slate-950 p-2 text-center">
                          <div className="text-[10px] text-slate-500 mb-0.5">
                            {label}
                          </div>
                          <div className="text-sm font-bold font-mono text-cyan-400">
                            {value}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="bg-slate-950/80 rounded-xl border border-slate-800 overflow-hidden">
                    <div className="px-3 py-1.5 border-b border-slate-800 bg-slate-900/50 text-[10px] text-slate-400 uppercase tracking-wider font-mono font-semibold">
                      Response Evaluation
                    </div>
                    <div className="grid grid-cols-3 gap-px bg-slate-800">
                      {[
                        ["ROUGE-L F1", "41.2%"],
                        ["Faithfulness", "80.0%"],
                        ["Answer Relevance", "80.0%"],
                      ].map(([label, value]) => (
                        <div key={label} className="bg-slate-950 p-2 text-center">
                          <div className="text-[10px] text-slate-500 mb-0.5">
                            {label}
                          </div>
                          <div className="text-sm font-bold font-mono text-cyan-400">
                            {value}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <figcaption className="mt-3 text-[11px] text-slate-500">
                  Illustrative sample card. Nine metrics per pipeline are reported live during deep analysis runs.
                </figcaption>
              </figure>

              <div className="absolute -inset-4 bg-gradient-to-r from-cyan-600 to-blue-600 opacity-25 blur-3xl -z-10 rounded-full" />
            </div>
          </div>
        </section>

        {/* --- Interactive Benchmark Matrix Playground Section --- */}
        <section id="benchmark" aria-labelledby="benchmark-title" className="py-20 border-t border-white/5 bg-slate-900/30">
          <div className="container mx-auto px-6">
            <SectionHeading
              id="benchmark-title"
              eyebrow="Live Playground"
              title="Test the 9-Pipeline Matrix interactively"
            >
              Explore how Dense, Sparse, and Hybrid retrieval methods combined with GPT-4o mini, Gemini 3 Flash, or Claude Haiku 4.5 perform on sample documents before running your own.
            </SectionHeading>

            <InteractiveBenchmarkSimulator />
          </div>
        </section>

        {/* --- How it works (Architecture Flow) --- */}
        <section
          id="how-it-works"
          aria-labelledby="how-it-works-title"
          className="py-20 border-t border-white/5"
        >
          <div className="container mx-auto px-6">
            <SectionHeading
              id="how-it-works-title"
              eyebrow="Architecture & Pipeline"
              title="From raw document to 9 scored pipelines"
            >
              Six transparent phases — nothing happens in an uninspectable black box.
            </SectionHeading>

            <ArchitectureFlow />
          </div>
        </section>

        {/* --- Retrieval methods --- */}
        <section
          id="retrieval"
          aria-labelledby="retrieval-title"
          className="py-20 border-t border-white/5 bg-slate-900/20"
        >
          <div className="container mx-auto px-6">
            <SectionHeading
              id="retrieval-title"
              eyebrow="Retrieval Strategy"
              title="Three ways to find the right chunk"
            >
              The three methods disagree in interesting ways — semantics catches
              paraphrase, keywords catch exact names, and the reranker arbitrates.
              Running all three on your document is how you find out which one
              your content rewards.
            </SectionHeading>

            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              {RETRIEVAL_METHODS.map((method) => (
                <Card key={method.name} className="h-full">
                  <div
                    className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ring-1 ${method.accent}`}
                  >
                    <method.icon className="w-6 h-6" />
                  </div>
                  <h3 className="text-lg font-bold text-white mb-1">
                    {method.name}
                  </h3>
                  <p className="text-sm text-cyan-400/80 mb-3 font-medium">
                    {method.summary}
                  </p>
                  <p className="text-sm text-slate-400 leading-relaxed">
                    {method.detail}
                  </p>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* --- Models --- */}
        <section
          id="models"
          aria-labelledby="models-title"
          className="py-20 border-y border-white/5 bg-slate-900/30"
        >
          <div className="container mx-auto px-6">
            <SectionHeading
              id="models-title"
              eyebrow="Multi-LLM Execution"
              title="The same question, answered by three different LLMs"
            >
              Each pipeline is end-to-end: the model rewrites your question into
              a search query, retrieves with its assigned method, and generates
              at temperature 0 — so its scores reflect the whole chain, query
              rewriting included. All traffic is routed through OpenRouter with a
              single API key.
            </SectionHeading>

            <div className="grid md:grid-cols-3 gap-6 mb-10">
              {MODELS.map((model) => (
                <Card key={model.id}>
                  <p className="text-xs uppercase tracking-wider text-slate-500 mb-2 font-mono">
                    {model.provider}
                  </p>
                  <h3 className="text-xl font-bold text-white mb-3">
                    {model.label}
                  </h3>
                  <code className="text-xs font-mono text-cyan-400/90 break-all bg-slate-950 p-2 rounded-lg border border-slate-800 block">
                    {model.id}
                  </code>
                </Card>
              ))}
            </div>

            <div className="rounded-2xl border border-slate-800 bg-slate-950/60 divide-y divide-slate-800">
              {SUPPORTING_MODELS.map((item) => (
                <div
                  key={item.id}
                  className="grid sm:grid-cols-[12rem_1fr] gap-2 sm:gap-6 p-5"
                >
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <Braces className="w-4 h-4 text-cyan-400" />
                    {item.role}
                  </div>
                  <div>
                    <code className="text-xs font-mono text-cyan-400/90 break-all">
                      {item.id}
                    </code>
                    <p className="text-sm text-slate-400 mt-1">{item.note}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* --- Metrics --- */}
        <section id="metrics" aria-labelledby="metrics-title" className="py-20">
          <div className="container mx-auto px-6">
            <SectionHeading
              id="metrics-title"
              eyebrow="Dual Evaluation Engine"
              title="Nine numbers for every pipeline"
            >
              Retrieval and generation fail differently, so they're scored
              separately: a pipeline can retrieve perfectly and still answer
              badly, and the metrics will say so.
            </SectionHeading>

            <div className="grid lg:grid-cols-2 gap-6">
              <Card>
                <div className="flex items-center gap-3 mb-5">
                  <span className="w-10 h-10 rounded-xl bg-blue-500/10 text-blue-400 flex items-center justify-center ring-1 ring-blue-500/20">
                    <Gauge className="w-5 h-5" />
                  </span>
                  <h3 className="text-lg font-bold text-white">
                    Retrieval quality (Chunks)
                  </h3>
                </div>
                <dl className="space-y-4">
                  {RETRIEVAL_METRICS.map((metric) => (
                    <div key={metric.name}>
                      <dt className="text-sm font-semibold text-cyan-400">
                        {metric.name}
                      </dt>
                      <dd className="text-sm text-slate-400 leading-relaxed">
                        {metric.body}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-5 pt-5 border-t border-slate-800 text-xs text-slate-500 leading-relaxed">
                  Computed as set overlap between retrieved chunk IDs and
                  ground-truth chunk IDs. Position inside the result list is not
                  rewarded — there is no MRR or nDCG here.
                </p>
              </Card>

              <Card>
                <div className="flex items-center gap-3 mb-5">
                  <span className="w-10 h-10 rounded-xl bg-pink-500/10 text-pink-400 flex items-center justify-center ring-1 ring-pink-500/20">
                    <BarChart3 className="w-5 h-5" />
                  </span>
                  <h3 className="text-lg font-bold text-white">
                    Answer quality (Response & LLM Judge)
                  </h3>
                </div>
                <dl className="space-y-4">
                  {ANSWER_METRICS.map((metric) => (
                    <div key={metric.name}>
                      <dt className="text-sm font-semibold text-cyan-400">
                        {metric.name}
                      </dt>
                      <dd className="text-sm text-slate-400 leading-relaxed">
                        {metric.body}
                      </dd>
                    </div>
                  ))}
                </dl>
                <p className="mt-5 pt-5 border-t border-slate-800 text-xs text-slate-500 leading-relaxed">
                  Faithfulness, relevance and coverage are judged by Mistral
                  Nemo on a 1–5 scale and reported normalized to 0–1, so every
                  metric on a card shares one axis.
                </p>
              </Card>
            </div>

            <div className="mt-6">
              <Caveat>
                Metrics only exist where ground truth does. Without
                ground-truth chunks the retrieval scores have nothing to compare
                against, and without an expected answer the answer metrics are
                skipped entirely — which is why setting ground truth is a step
                in the flow rather than an optional extra.
              </Caveat>
            </div>
          </div>
        </section>

        {/* --- Ground truth --- */}
        <section
          id="ground-truth"
          aria-labelledby="ground-truth-title"
          className="py-20 border-y border-white/5 bg-slate-900/30"
        >
          <div className="container mx-auto px-6">
            <SectionHeading
              id="ground-truth-title"
              eyebrow="Ground Truth Standard"
              title="Decide what 'relevant' means — by hand or by consensus"
            >
              Retrieval metrics are only as good as the set they're scored
              against, so RAGReader makes that choice explicit and stores it with
              the run.
            </SectionHeading>

            <GroundTruthVisualizer />

            <div className="mt-6">
              <Caveat>
                Pooling scores retrievers against a consensus they helped produce,
                and hybrid retrieval is structurally closer to that consensus than
                dense or sparse. Read pooled Precision@K and Recall@K as{" "}
                <em>agreement with the consensus</em>, not as ground truth in the
                hand-labelled sense.
              </Caveat>
            </div>
          </div>
        </section>

        {/* --- Configuration --- */}
        <section
          id="configure"
          aria-labelledby="configure-title"
          className="py-20"
        >
          <div className="container mx-auto px-6 grid lg:grid-cols-2 gap-12">
            <div>
              <SectionHeading
                id="configure-title"
                eyebrow="Control"
                title="What you can change per run"
              >
                The deep-analysis sidebar narrows the matrix before it runs, and
                whatever you pick is saved on the batch — so every stored result
                records the configuration that produced it.
              </SectionHeading>

              <dl className="rounded-2xl border border-slate-800 divide-y divide-slate-800 overflow-hidden">
                {CONFIGURABLE.map((row) => (
                  <div
                    key={row.label}
                    className="grid sm:grid-cols-2 gap-1 sm:gap-4 p-5 bg-slate-900/40"
                  >
                    <dt className="text-sm font-semibold text-white flex items-center gap-2">
                      <Settings2 className="w-4 h-4 text-cyan-400" />
                      {row.label}
                    </dt>
                    <dd className="text-sm text-slate-400">{row.value}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <div className="lg:pt-24">
              <Card className="h-full">
                <div className="flex items-center gap-3 mb-4">
                  <span className="w-10 h-10 rounded-xl bg-slate-800 text-slate-300 flex items-center justify-center">
                    <Scale className="w-5 h-5 text-cyan-400" />
                  </span>
                  <h3 className="text-lg font-bold text-white">
                    Deliberately not adjustable per run
                  </h3>
                </div>
                <ul className="space-y-4 text-sm text-slate-400 leading-relaxed">
                  <li>
                    <span className="font-semibold text-slate-200">
                      Chunking.
                    </span>{" "}
                    Applied once at ingest (fixed 512-character chunks, 50
                    characters of overlap). Changing it re-chunks the document,
                    which replaces every stored chunk — and takes the ground
                    truth attached to them with it. Re-upload to chunk
                    differently.
                  </li>
                  <li>
                    <span className="font-semibold text-slate-200">
                      The hybrid reranker.
                    </span>{" "}
                    The cross-encoder is the only thing separating hybrid from
                    dense + sparse. Turn it off and hybrid becomes the same RRF
                    fusion the candidate pool uses, so the run would be scored
                    against its own algorithm.
                  </li>
                </ul>
              </Card>
            </div>
          </div>
        </section>

        {/* --- Comparison Matrix Section --- */}
        <section id="comparison" aria-labelledby="comparison-title" className="py-20 border-t border-white/5 bg-slate-900/20">
          <div className="container mx-auto px-6">
            <SectionHeading
              id="comparison-title"
              eyebrow="Why RAGReader?"
              title="Built for objective evaluation, not basic chat"
            >
              See how RAGReader compares against standard vector databases and standard document chat tools.
            </SectionHeading>

            <ComparisonMatrix />
          </div>
        </section>

        {/* --- Stack --- */}
        <section
          id="stack"
          aria-labelledby="stack-title"
          className="py-20 border-y border-white/5 bg-slate-900/30"
        >
          <div className="container mx-auto px-6">
            <SectionHeading
              id="stack-title"
              eyebrow="Under the hood"
              title="What it's actually built on"
            >
              No hidden services: the whole thing runs from one Docker Compose
              file and one OpenRouter key.
            </SectionHeading>

            <ul className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {STACK.map((item) => (
                <li
                  key={item.name}
                  className="rounded-xl border border-slate-800 bg-slate-950/60 p-5"
                >
                  <p className="text-sm font-semibold text-white">{item.name}</p>
                  <p className="text-xs text-slate-500 mt-1">{item.note}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* --- Quick Start Developer Section --- */}
        <section id="quickstart" aria-labelledby="quickstart-title" className="py-20">
          <div className="container mx-auto px-6 max-w-4xl">
            <SectionHeading
              id="quickstart-title"
              eyebrow="Self-Hosting"
              title="Deploy locally in under 2 minutes"
            >
              Clone the repository, configure your OpenRouter key, and run Docker Compose.
            </SectionHeading>

            <QuickStartCode />
          </div>
        </section>

        {/* --- FAQ Accordion --- */}
        <section id="faq" aria-labelledby="faq-title" className="py-20 border-t border-white/5 bg-slate-900/20">
          <div className="container mx-auto px-6 max-w-4xl">
            <SectionHeading
              id="faq-title"
              eyebrow="FAQ"
              title="Questions worth answering before you upload"
            />

            <div className="space-y-4">
              {FAQ.map((item, idx) => {
                const isOpen = openFaqIndex === idx;
                return (
                  <div
                    key={item.q}
                    className="rounded-2xl border border-slate-800 bg-slate-900/50 overflow-hidden transition-all"
                  >
                    <button
                      onClick={() => toggleFaq(idx)}
                      className="w-full p-6 text-left flex items-center justify-between gap-4 font-bold text-white hover:text-cyan-400 transition-colors focus:outline-none"
                    >
                      <span className="text-base sm:text-lg">{item.q}</span>
                      {isOpen ? (
                        <ChevronUp className="w-5 h-5 text-cyan-400 shrink-0" />
                      ) : (
                        <ChevronDown className="w-5 h-5 text-slate-500 shrink-0" />
                      )}
                    </button>
                    {isOpen && (
                      <div className="px-6 pb-6 text-sm text-slate-400 leading-relaxed border-t border-slate-800/60 pt-4 animate-in fade-in-50 duration-200">
                        {item.a}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* --- Closing CTA --- */}
        <section className="py-24 border-t border-white/5 bg-gradient-to-b from-slate-900/40 to-slate-950">
          <div className="container mx-auto px-6 text-center max-w-3xl">
            <span className="inline-flex items-center gap-2 rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3.5 py-1 text-xs font-semibold text-cyan-300 mb-4">
              <Zap className="w-3.5 h-3.5" /> Start Benchmarking Free
            </span>
            <h2 className="text-3xl sm:text-4xl font-bold text-white mb-4 tracking-tight">
              Run it on a document you actually care about
            </h2>
            <p className="text-slate-400 mb-8 leading-relaxed">
              The comparison is only useful on your own content — that's the
              point. Add a source and the first answer is a few seconds away.
            </p>
            <div className="flex flex-wrap justify-center gap-4">
              <a
                href="#top"
                onClick={(event) => {
                  event.preventDefault();
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
                className="rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 px-6 py-3.5 text-sm font-semibold text-white transition-all shadow-lg shadow-cyan-600/20 active:scale-95"
              >
                Add a document
              </a>
              <Link
                to="/docs"
                className="rounded-xl border border-slate-700 hover:border-cyan-500/40 px-6 py-3.5 text-sm font-semibold text-slate-200 transition-colors bg-slate-900/60"
              >
                Read the walkthrough
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* --- Footer --- */}
      <footer className="bg-slate-950 border-t border-slate-800/80 pt-16 pb-8">
        <div className="container mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            <div className="col-span-2 md:col-span-1">
              <div className="text-xl font-bold text-white mb-4 flex items-center gap-2">
                <div className="w-7 h-7 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-md flex items-center justify-center text-white font-bold text-sm">
                  R
                </div>
                RAGReader
              </div>
              <p className="text-slate-500 text-sm leading-relaxed">
                Document QA that shows its work: every retrieval method, every
                model, every score, side by side.
              </p>
            </div>
            <div>
              <h3 className="text-white font-semibold mb-4 text-sm">
                On this page
              </h3>
              <ul className="space-y-2 text-sm text-slate-400">
                <li>
                  <a href="#how-it-works" className="hover:text-cyan-400 transition-colors">
                    How it works
                  </a>
                </li>
                <li>
                  <a href="#retrieval" className="hover:text-cyan-400 transition-colors">
                    Retrieval methods
                  </a>
                </li>
                <li>
                  <a href="#metrics" className="hover:text-cyan-400 transition-colors">
                    Metrics
                  </a>
                </li>
                <li>
                  <a href="#ground-truth" className="hover:text-cyan-400 transition-colors">
                    Ground truth
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <h3 className="text-white font-semibold mb-4 text-sm">
                Resources
              </h3>
              <ul className="space-y-2 text-sm text-slate-400">
                <li>
                  <Link to="/docs" className="hover:text-cyan-400 transition-colors">
                    Walkthrough Guide
                  </Link>
                </li>
                <li>
                  <a
                    href={`${REPO_URL}#readme`}
                    className="hover:text-cyan-400 transition-colors"
                    target="_blank"
                    rel="noreferrer"
                  >
                    README
                  </a>
                </li>
                <li>
                  <a
                    href={`${REPO_URL}/blob/main/LICENSE`}
                    className="hover:text-cyan-400 transition-colors"
                    target="_blank"
                    rel="noreferrer"
                  >
                    MIT License
                  </a>
                </li>
              </ul>
            </div>
            <div>
              <h3 className="text-white font-semibold mb-4 text-sm">Project</h3>
              <ul className="space-y-2 text-sm text-slate-400">
                <li>
                  <a
                    href={REPO_URL}
                    className="inline-flex items-center gap-2 hover:text-cyan-400 transition-colors"
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Github className="w-4 h-4" />
                    Source on GitHub
                  </a>
                </li>
                <li>
                  <a
                    href={`${REPO_URL}/issues`}
                    className="hover:text-cyan-400 transition-colors"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Issue Tracker
                  </a>
                </li>
                <li>
                  <a
                    href="https://openrouter.ai/"
                    className="hover:text-cyan-400 transition-colors"
                    target="_blank"
                    rel="noreferrer"
                  >
                    Powered by OpenRouter
                  </a>
                </li>
              </ul>
            </div>
          </div>
          <div className="border-t border-slate-800/80 pt-8 text-center text-slate-600 text-sm flex flex-col sm:flex-row items-center justify-between gap-4">
            <div>
              © {new Date().getFullYear()} RAGReader · Open source under the MIT License
            </div>
            <div className="text-xs text-slate-500 font-mono">
              rag.nevatal.tech
            </div>
          </div>
        </div>
      </footer>

      {/* Back To Top Floating Action */}
      <BackToTop />
    </div>
  );
};

export default LandingPage;
