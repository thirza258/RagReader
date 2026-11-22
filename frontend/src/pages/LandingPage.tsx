import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Activity, Compass, ExternalLink, FlaskConical, GitBranch, Shuffle } from "lucide-react";
import { chattyDeskURL } from "../constant";

import { SubmitPayload } from "../types/types";
import { createDocument } from "../features/documents/api/documents";
import { loginPathFor } from "../features/auth/lib/redirect";
import { getToken } from "../features/auth/lib/session";

import FileSubmit from "../components/FileSubmit";
import SEO from "../components/SEO";
import InteractiveBenchmarkSimulator from "../components/landing/InteractiveBenchmarkSimulator";
import GroundTruthVisualizer from "../components/landing/GroundTruthVisualizer";
import ArchitectureFlow from "../components/landing/ArchitectureFlow";
import ComparisonMatrix from "../components/landing/ComparisonMatrix";
import QuickStartCode from "../components/landing/QuickStartCode";
import BackToTop from "../components/landing/BackToTop";

const REPO_URL = "https://github.com/thirza258/RagReader";

const SUMMARY = [
  { term: "Retrieval methods", def: "Dense, sparse (BM25), weighted hybrid & RRF with cross-encoder / LLM reranking" },
  { term: "Zero-cost free tier", def: "OpenRouter free embeddings & generation with automatic multi-model shuffled failover" },
  { term: "RAG Observability", def: "Full latency waterfalls, candidate provenance, and 'Why this answer?' inspector" },
  { term: "Evaluation Lab", def: "Golden test datasets, automated batch experiments, and bootstrap confidence intervals" },
  { term: "Research Platform", def: "Multi-document claim verification, matrix comparisons, and structured report synthesis" },
  { term: "Pipeline Versioning", def: "Immutable configuration versions for reproducible benchmarks across documents" },
  { term: "Licence", def: "MIT, self-hostable with Docker Compose" },
];

const SAMPLE_CHUNKS = [
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
];

const SAMPLE_METRICS: { group: string; rows: [string, string][] }[] = [
  {
    group: "Retrieval",
    rows: [
      ["Precision@K", "60.0%"],
      ["Recall@K", "75.0%"],
      ["F1@K", "66.7%"],
    ],
  },
  {
    group: "Answer",
    rows: [
      ["Faithfulness", "Unavailable"],
      ["Response relevance", "Unavailable"],
      ["Factual correctness (F1)", "Unavailable"],
    ],
  },
];

const CONTENTS = [
  { id: "how-it-works", label: "How it works" },
  { id: "retrieval", label: "Retrieval methods" },
  { id: "observability", label: "RAG observability & traces" },
  { id: "evaluation-lab", label: "Evaluation lab & datasets" },
  { id: "research", label: "Deep research platform" },
  { id: "models", label: "Models & free-tier failover" },
  { id: "metrics", label: "Evaluation metrics" },
  { id: "ground-truth", label: "Ground truth" },
  { id: "configure", label: "What you can change per run" },
  { id: "benchmark", label: "Worked example" },
  { id: "comparison", label: "Comparison with adjacent tools" },
  { id: "stack", label: "Implementation" },
  { id: "quickstart", label: "Running it yourself" },
  { id: "faq", label: "Questions" },
];

const RETRIEVAL_METHODS = [
  {
    name: "Dense retrieval",
    summary: "Semantic vector search over embeddings.",
    detail:
      "Every chunk is embedded with nvidia/nemotron-3.5-embed-1b:free (with automatic failover to compatible 2048-dim free embeddings) and ranked by cosine similarity against the embedded query. This is also the default method that answers in the normal workspace chat.",
  },
  {
    name: "Sparse retrieval",
    summary: "BM25 keyword search.",
    detail:
      "BM25Okapi over a corpus that is lowercased, stripped of punctuation and filtered through NLTK's English stopword list. Exact terms, names, code identifiers and numbers survive here even when embeddings blur them.",
  },
  {
    name: "Hybrid retrieval",
    summary: "Dense + sparse candidates fused and reranked.",
    detail:
      "Both engines contribute candidates (at least 10 each). They are combined through min-max weighted fusion (customizable dense-vs-sparse balance) or Reciprocal Rank Fusion (RRF), and then optionally reranked by Ollama cross-encoders or an OpenRouter LLM reranker before top-K selection.",
  },
];

const MODELS = [
  { label: "Gemma 4 26B (Free)", id: "google/gemma-4-26b-a4b-it:free", provider: "Google" },
  { label: "Nemotron 3.5 (Free)", id: "nvidia/nemotron-3.5-lightning:free", provider: "NVIDIA" },
  { label: "GPT-4o mini", id: "openai/gpt-4o-mini", provider: "OpenAI" },
  { label: "Gemini 3 Flash", id: "google/gemini-3-flash-preview", provider: "Google" },
  { label: "Claude Haiku 4.5", id: "anthropic/claude-haiku-4.5", provider: "Anthropic" },
];

const SUPPORTING_MODELS = [
  {
    role: "Free Embeddings",
    id: "nvidia/nemotron-3.5-embed-1b:free",
    note: "High-capacity vector embeddings at zero cost, with automatic failover between compatible 2048-dim free embedding models (e.g. nvidia/nemotron-3-embed-1b:free).",
  },
  {
    role: "Dynamic Free Fallback Pool",
    id: "14 OpenRouter Free Models",
    note: "Automatic shuffled fallback across Gemma 4, Nemotron 3.5/Nano/Ultra, Cohere North, Flint, Ling, Ernie, and Particle whenever rate limits (429) or credit exhaustion (402) occur.",
  },
  {
    role: "Local Reranker",
    id: "cross-encoder/ms-marco-MiniLM-L6-v2",
    note: "The cross-encoder that makes hybrid different from dense + sparse (runs locally via Ollama).",
  },
  {
    role: "Evaluation judge",
    id: "mistralai/mistral-nemo",
    note: "Ragas scores faithfulness, response relevance and factual correctness.",
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
    name: "Faithfulness",
    body: "Is every claim in the answer supported by the retrieved chunks, or did the model invent some of it?",
  },
  {
    name: "Response relevance",
    body: "Ragas generates questions from the answer, then compares their meaning to your original question using remote embeddings.",
  },
  {
    name: "Factual correctness (F1)",
    body: "Ragas checks answer claims against your expected answer and balances factual precision with completeness.",
  },
];

const CONFIGURABLE = [
  { label: "Retrieval methods", value: "Any subset of dense, sparse, hybrid" },
  { label: "Models", value: "Any models OpenRouter serves; the three defaults come pre-selected" },
  { label: "Retrieval depth (Top-K)", value: "1–20, default 5 — the same K as in Precision@K" },
  { label: "Ground truth", value: "Manual selection or candidate pooling" },
  { label: "Pool depth", value: "1–50, default 10 — deeper than Top-K on purpose" },
];

const STACK = [
  { name: "OpenRouter Free Tier", note: "Zero-cost embeddings and generation with 14-model shuffled failover" },
  { name: "Django + DRF", note: "REST API, workspace persistence, and auth" },
  { name: "Channels + Daphne", note: "WebSocket streaming of analysis results and live updates" },
  { name: "Celery + Redis", note: "Background document indexing, evaluation experiments, and research tasks" },
  { name: "PostgreSQL", note: "Workspaces, documents, chunks, pipeline versions, runs, and datasets" },
  { name: "rank-bm25 + NLTK", note: "Sparse keyword retrieval and tokenization" },
  { name: "Ollama", note: "Local cross-encoder and embedding reranking" },
  { name: "Evaluation Lab", note: "Golden datasets, batch matrix experiments, and paired bootstrap CIs" },
  { name: "Research Engine", note: "Multi-document claim verification, synthesis, and citation auditing" },
  { name: "Observability Tracer", note: "Per-span latency waterfalls, provenance tracking, and Why-This-Answer" },
  { name: "React + Vite + Tailwind", note: "Fast, academic-style responsive interface" },
];

const FAQ = [
  {
    q: "What does RAGReader actually do?",
    a: "You add documents to a workspace, ask questions, and get streamed answers with citations linking back to exact source text. From there, you can trace retrieval latency and provenance ('Why this answer?'), compare nine retrieval pipelines in Deep Analysis, run batch benchmarks in the Evaluation Lab, or launch autonomous multi-document Deep Research tasks.",
  },
  {
    q: "How does the zero-cost free model tier and shuffling work?",
    a: "RAGReader defaults to OpenRouter's free models for both embeddings (nvidia/nemotron-3.5-embed-1b:free) and answer generation (Gemma 4 26B, Nemotron 3.5 Lightning, etc.). If a free model hits a provider rate limit (429) or temporary load spike, our dynamic engine automatically shuffles and fails over across 14 free OpenRouter models before the stream begins, ensuring reliable and cost-free operation.",
  },
  {
    q: "What is the Evaluation Lab?",
    a: "The Evaluation Lab allows you to upload golden reference datasets (CSV/JSON), curate test queries from live chat answers, and execute automated batch experiments. It scores retrieval metrics (Recall, Precision, Hit Rate, nDCG, MRR) and generation metrics (Ragas faithfulness, answer relevance, correctness), and provides side-by-side run comparisons with paired bootstrap confidence intervals.",
  },
  {
    q: "What does the Deep Research platform do?",
    a: "The Research tab conducts background multi-document investigations: verifying factual claims against document evidence (calculating confidence and stance per passage), asking synthesizing questions across multiple papers, generating dimensional comparison matrices, extracting structured data, and drafting comprehensive Markdown research reports with verifiable citations.",
  },
  {
    q: "How does RAG observability and 'Why this answer?' work?",
    a: "Every chat turn instruments a bounded trace: query rewriting, vector embedding, index cache lookup, search candidates, and generation latency. Clicking 'Why this answer?' reveals the full waterfall breakdown, candidate score distributions across Dense and BM25 retrievers, and explains why specific passages were chosen or dropped.",
  },
  {
    q: "What can I upload?",
    a: "A PDF, Word (DOCX), plain-text or Markdown file up to 25 MB, a web page URL (fetched and stripped to clean text on the server), or text pasted straight into the form. Each becomes a document in your workspace library, indexed in the background.",
  },
  {
    q: "Do I need my own API keys?",
    a: "Not on the hosted app — it runs on OpenRouter's free tier with automated multi-model shuffling. If you self-host, a single OPENROUTER_API_KEY covers all generation, free embeddings, and evaluation judges.",
  },
  {
    q: "Is it open source?",
    a: "Yes — MIT licensed, on GitHub, and self-hostable with Docker Compose.",
  },
];

/** A numbered section with an academic run-in heading and an optional lede. */
const Section = ({
  id,
  number,
  title,
  lede,
  children,
}: {
  id: string;
  number: number;
  title: string;
  lede?: React.ReactNode;
  children: React.ReactNode;
}) => (
  <section id={id} aria-labelledby={`${id}-title`} className="border-t border-border py-14">
    <h2 id={`${id}-title`} className="text-2xl font-semibold">
      <span className="mr-3 font-mono text-base font-normal text-muted-foreground tabular">
        {String(number).padStart(2, "0")}
      </span>
      {title}
    </h2>
    {lede ? <p className="prose-note measure mt-4">{lede}</p> : null}
    <div className="mt-8">{children}</div>
  </section>
);

/** A bordered panel. One hairline, no fill, no shadow. */
const Panel = ({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) => (
  <div className={`border border-border p-6 ${className}`}>{children}</div>
);

/** A run-in note, set off by a rule rather than a coloured box. */
const Note = ({ children }: { children: React.ReactNode }) => (
  <aside className="measure border-l-2 border-primary/50 py-1 pl-5">
    <p className="prose-note text-base">
      <span className="font-semibold text-foreground">Note. </span>
      {children}
    </p>
  </aside>
);

const LandingPage: React.FC = () => {
  const navigate = useNavigate();
  const [openFaqIndex, setOpenFaqIndex] = useState<number | null>(0);

  // The upload is acknowledged at once (202) and processed in the background;
  // the workspace shows its progress. Errors are shown inline by FileSubmit.
  const handleSubmit = async (payload: SubmitPayload) => {
    if (!getToken()) {
      navigate(loginPathFor("/"));
      return;
    }
    const { document } = await createDocument(
      payload.type === "file"
        ? { kind: "file", file: payload.file }
        : payload.type === "url"
          ? { kind: "url", url: payload.url }
          : { kind: "text", text: payload.text },
    );
    navigate(`/workspace?document=${document.id}`);
  };

  const toggleFaq = (idx: number) => {
    setOpenFaqIndex(openFaqIndex === idx ? null : idx);
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <SEO
        title="RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines"
        description="Ask questions about your own PDF, URL, or pasted text, then score the answer across 9 RAG pipelines — Dense, Sparse and Hybrid retrieval x three LLMs."
        canonicalUrl="https://rag.nevatal.id/"
      />

      <main className="container mx-auto max-w-4xl px-6 pt-28">
        {/* --- Masthead --- */}
        <header id="top" className="pb-14">
          <h1 className="text-4xl font-semibold leading-tight sm:text-5xl">
            Which RAG pipeline answers your document best?
          </h1>
          <p className="measure mt-5 font-serif text-xl leading-snug text-muted-foreground">
            A document QA tool that reports its own retrieval and answer quality,
            pipeline by pipeline.
          </p>

          <p className="prose-note measure mt-8">
            RAGReader answers your question straight away with dense retrieval.
            Then, on one click, it re-runs the <em>same</em> question through every
            retrieval method and model you picked — nine pipelines by default,
            three retrieval methods across three LLMs — and reports six scores for
            each, so the comparison rests on measurement rather than intuition.
          </p>

          <dl className="mt-10 border-t border-border text-sm">
            {SUMMARY.map((row) => (
              <div
                key={row.term}
                className="grid gap-1 border-b border-border py-3 sm:grid-cols-[13rem_1fr] sm:gap-6"
              >
                <dt className="font-medium text-foreground">{row.term}</dt>
                <dd className="text-muted-foreground">{row.def}</dd>
              </div>
            ))}
          </dl>

          <nav aria-label="Contents" className="mt-10">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Contents
            </h2>
            <ol className="mt-3 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
              {CONTENTS.map((item, idx) => (
                <li key={item.id} className="flex gap-3">
                  <span className="font-mono text-muted-foreground tabular">
                    {String(idx + 1).padStart(2, "0")}
                  </span>
                  <a href={`#${item.id}`} className="link">
                    {item.label}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
        </header>

        {/* --- Submit --- */}
        <section
          id="start"
          aria-labelledby="start-title"
          className="border-t border-border py-14"
        >
          <h2 id="start-title" className="text-2xl font-semibold">
            Add a document
          </h2>
          <p className="prose-note measure mt-4">
            A PDF, Word or text file, a web page URL, or pasted text. It opens in
            your workspace while it is processed, ready to read and ask about. New here?{" "}
            <Link to="/docs" className="link">
              Walk through the whole flow in screenshots
            </Link>{" "}
            first.
          </p>

          <div className="mt-8 border border-border">
            <FileSubmit onSubmit={handleSubmit} />
          </div>

          {/* Figure 1 — an illustrative result, set as a plain figure. */}
          <figure className="mt-12">
            <div className="border border-border">
              <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-5 py-3">
                <span className="text-sm font-medium">
                  Hybrid retrieval · Claude Haiku 4.5
                </span>
                <span className="font-mono text-xs uppercase tracking-wide text-muted-foreground">
                  Illustrative
                </span>
              </div>

              <dl className="divide-y divide-border text-sm">
                <div className="px-5 py-4">
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Query
                  </dt>
                  <dd className="mt-1">What happened in the Battle of Surabaya?</dd>
                </div>
                <div className="px-5 py-4">
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Generated answer
                  </dt>
                  <dd className="prose-note mt-1 text-base">
                    In November 1945 Indonesian militias in Surabaya fought
                    British-led Allied troops. The battle caused heavy casualties and
                    is commemorated annually as Heroes' Day.
                  </dd>
                </div>
                <div className="px-5 py-4">
                  <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    Retrieved context
                  </dt>
                  <dd className="mt-2 space-y-2">
                    {SAMPLE_CHUNKS.map((chunk) => (
                      <div key={chunk.n} className="flex gap-4">
                        <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground tabular">
                          #{chunk.n} · {chunk.score}
                        </span>
                        <span className="text-muted-foreground">{chunk.text}</span>
                      </div>
                    ))}
                  </dd>
                </div>
              </dl>

              <table className="w-full border-t border-border text-sm">
                <caption className="sr-only">
                  Metrics reported for this pipeline
                </caption>
                <tbody>
                  {SAMPLE_METRICS.map(({ group, rows }) => (
                    <tr key={group} className="border-b border-border last:border-b-0">
                      <th
                        scope="row"
                        className="w-28 border-r border-border px-5 py-3 text-left align-top text-xs font-medium uppercase tracking-wide text-muted-foreground"
                      >
                        {group}
                      </th>
                      <td className="px-5 py-3">
                        <div className="flex flex-wrap gap-x-8 gap-y-1">
                          {rows.map(([label, value]) => (
                            <span key={label} className="text-muted-foreground">
                              {label}{" "}
                              <span className="font-mono text-foreground tabular">
                                {value}
                              </span>
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <figcaption className="mt-3 text-sm text-muted-foreground">
              Figure 1. Sample retrieval output. Ragas answer scores have not been
              recorded for this example; run deep analysis to calculate them.
            </figcaption>
          </figure>
        </section>

        {/* --- 1. How it works --- */}
        <Section
          id="how-it-works"
          number={1}
          title="How it works"
          lede="Six phases from raw document to nine scored pipelines. Nothing happens in an uninspectable black box."
        >
          <ArchitectureFlow />
        </Section>

        {/* --- 2. Retrieval methods --- */}
        <Section
          id="retrieval"
          number={2}
          title="Retrieval methods & pipelines"
          lede="The retrieval methods disagree in interesting ways — semantics catches paraphrase, keywords catch exact names, and the reranker arbitrates. Running all three on your document is how you find out which one your content rewards."
        >
          <dl className="border-t border-border">
            {RETRIEVAL_METHODS.map((method) => (
              <div
                key={method.name}
                className="grid gap-2 border-b border-border py-6 md:grid-cols-[14rem_1fr] md:gap-8"
              >
                <dt>
                  <span className="block font-serif text-lg font-semibold">
                    {method.name}
                  </span>
                  <span className="mt-1 block text-sm text-muted-foreground">
                    {method.summary}
                  </span>
                </dt>
                <dd className="prose-note text-base">{method.detail}</dd>
              </div>
            ))}
          </dl>
        </Section>

        {/* --- 3. Observability & Traces --- */}
        <Section
          id="observability"
          number={3}
          title="RAG observability & traces"
          lede="Every question instruments a full execution trace with per-step latency and candidate provenance. See exactly how an answer was derived instead of trusting an opaque pipeline."
        >
          <div className="grid gap-6 md:grid-cols-3">
            <Panel>
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-foreground">Latency Waterfall</h3>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Per-span millisecond breakdown: query rewrite, vector embedding, index cache lookup, candidate search, reranking, and Time-To-First-Token (TTFT).
              </p>
            </Panel>
            <Panel>
              <div className="flex items-center gap-2">
                <Compass className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-foreground">Candidate Funnel</h3>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Inspect every candidate passage considered across Dense, BM25, and fused stages. Discover exactly why specific chunks scored high or were filtered out.
              </p>
            </Panel>
            <Panel>
              <div className="flex items-center gap-2">
                <GitBranch className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-foreground">“Why this answer?”</h3>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                One-click inspector embedded in chat turns that reveals the answering model, active pipeline version, index hash, token usage, and citation mapping.
              </p>
            </Panel>
          </div>
        </Section>

        {/* --- 4. Evaluation Lab --- */}
        <Section
          id="evaluation-lab"
          number={4}
          title="Evaluation lab & datasets"
          lede="Move beyond single-query tests: maintain version-controlled test datasets, launch batch matrix experiments in Celery, and compare pipelines side-by-side with statistical rigor."
        >
          <div className="grid gap-6 md:grid-cols-2">
            <Panel>
              <h3 className="font-semibold text-foreground">Golden Reference Datasets</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Upload CSV or JSON test sets or curate real questions directly from workspace conversations. Every dataset is content-hashed and versioned, guaranteeing reproducible evaluation runs across document revisions.
              </p>
            </Panel>
            <Panel>
              <h3 className="font-semibold text-foreground">Paired Bootstrap Comparisons</h3>
              <p className="mt-2 text-sm text-muted-foreground">
                Compare 2–6 experiments simultaneously. Calculates win/loss margins, baseline metric deltas, and 95% paired bootstrap confidence intervals alongside latency and token cost trade-offs.
              </p>
            </Panel>
          </div>

          {/* AI Evaluation Suite Companion Card */}
          <div className="mt-6 border border-border/80 bg-accent/30 p-5 rounded-sm">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] font-mono uppercase font-semibold tracking-wider px-2 py-0.5 bg-primary/10 text-primary border border-primary/20">
                    AI Evaluation Suite
                  </span>
                  <span className="text-xs font-semibold text-foreground">
                    Looking for Foundation Model Benchmarks?
                  </span>
                </div>
                <p className="text-xs text-muted-foreground max-w-2xl leading-relaxed">
                  RagReader evaluates retrieval and document faithfulness. To benchmark foundational LLM reasoning (MMLU-Pro, GSM8K, HumanEval), latency distributions (P50/P95), and token pricing across 400+ models, visit our companion lab <strong>ChattyDesk</strong>.
                </p>
              </div>
              <a
                href={chattyDeskURL}
                target="_blank"
                rel="noreferrer"
                className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-sm bg-foreground text-background px-4 py-2 text-xs font-semibold hover:bg-foreground/90 transition-colors shadow-xs"
              >
                <span>ChattyDesk Model Lab</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            </div>
          </div>
        </Section>

        {/* --- 5. Deep Research Platform --- */}
        <Section
          id="research"
          number={5}
          title="Deep research platform"
          lede="Autonomous background agents that investigate, cross-verify, and synthesize knowledge across multiple documents in your workspace."
        >
          <div className="grid gap-6 md:grid-cols-2">
            <Panel>
              <div className="flex items-center gap-2">
                <FlaskConical className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-foreground">Claim Verification</h3>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Submit any hypothesis or statement. The engine searches all documents, identifies supporting and contradicting passages, and calculates an objective verdict and confidence score based on citation stances.
              </p>
            </Panel>
            <Panel>
              <div className="flex items-center gap-2">
                <Shuffle className="h-5 w-5 text-primary" />
                <h3 className="font-semibold text-foreground">Cross-Document Synthesis</h3>
              </div>
              <p className="mt-2 text-sm text-muted-foreground">
                Inquire across multi-document libraries: generate comparison matrices along user-defined dimensions, extract typed structured fields, spot contradictory statements, and export comprehensive Markdown reports.
              </p>
            </Panel>
          </div>
        </Section>

        {/* --- 6. Models & Free-Tier Failover --- */}
        <Section
          id="models"
          number={6}
          title="Models & free-tier failover"
          lede="Zero operational costs out of the box: OpenRouter's free embedding and generation models with dynamic multi-model shuffling for seamless rate-limit and quota resilience."
        >
          <h3 className="text-lg font-semibold">Free-Tier & Generation Models</h3>
          <p className="prose-note measure mt-2 text-base">
            Default configurations connect directly to OpenRouter's free tier. If any model experiences provider rate limits (429) or credit exhaustion (402), our client dynamically shuffles across 14 free fallback models before the first token streams.
          </p>
          <table className="mt-4 w-full border-t border-border text-sm">
            <caption className="sr-only">Default generation models</caption>
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="py-3 pr-6 font-medium">Model</th>
                <th scope="col" className="py-3 pr-6 font-medium">Provider</th>
                <th scope="col" className="py-3 font-medium">Identifier</th>
              </tr>
            </thead>
            <tbody>
              {MODELS.map((model) => (
                <tr key={model.id} className="border-b border-border">
                  <td className="py-3 pr-6 font-medium">{model.label}</td>
                  <td className="py-3 pr-6 text-muted-foreground">{model.provider}</td>
                  <td className="py-3 font-mono text-xs">{model.id}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3 className="mt-12 text-lg font-semibold">Supporting & Embedding Models</h3>
          <dl className="mt-4 border-t border-border">
            {SUPPORTING_MODELS.map((item) => (
              <div
                key={item.id}
                className="grid gap-1 border-b border-border py-4 sm:grid-cols-[13rem_1fr] sm:gap-6"
              >
                <dt className="text-sm font-medium">{item.role}</dt>
                <dd>
                  <code className="break-all font-mono text-xs">{item.id}</code>
                  <p className="mt-1 text-sm text-muted-foreground">{item.note}</p>
                </dd>
              </div>
            ))}
          </dl>
        </Section>

        {/* --- 7. Metrics --- */}
        <Section
          id="metrics"
          number={7}
          title="Evaluation metrics"
          lede="Retrieval and generation fail differently, so they are scored separately: a pipeline can retrieve perfectly and still answer badly, and the metrics will say so."
        >
          <div className="grid gap-10 lg:grid-cols-2">
            <div>
              <h3 className="text-lg font-semibold">Retrieval quality</h3>
              <dl className="mt-4 border-t border-border">
                {RETRIEVAL_METRICS.map((metric) => (
                  <div key={metric.name} className="border-b border-border py-4">
                    <dt className="text-sm font-medium">{metric.name}</dt>
                    <dd className="mt-1 text-sm text-muted-foreground">{metric.body}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 text-sm text-muted-foreground">
                Computed as set overlap between retrieved chunk IDs and ground-truth
                chunk IDs. Position inside the result list is not rewarded — there is
                no MRR or nDCG here.
              </p>
            </div>

            <div>
              <h3 className="text-lg font-semibold">Answer quality</h3>
              <dl className="mt-4 border-t border-border">
                {ANSWER_METRICS.map((metric) => (
                  <div key={metric.name} className="border-b border-border py-4">
                    <dt className="text-sm font-medium">{metric.name}</dt>
                    <dd className="mt-1 text-sm text-muted-foreground">{metric.body}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-4 text-sm text-muted-foreground">
                Ragas uses your selected OpenRouter judge and remote embeddings.
                Scores are shown as percentages. Missing inputs or failed evaluations
                show as unavailable, with a reason.
              </p>
            </div>
          </div>

          <div className="mt-10">
            <Note>
              Retrieval metrics compare against your reference chunks. Factual
              correctness needs an expected answer. Faithfulness and response relevance
              can run without that reference; faithfulness still needs source evidence.
            </Note>
          </div>
        </Section>

        {/* --- 8. Ground truth --- */}
        <Section
          id="ground-truth"
          number={8}
          title="Ground truth & consensus"
          lede="Retrieval metrics are only as good as the set they are scored against, so RAGReader makes that choice explicit and stores it with the run — by hand, or by consensus."
        >
          <GroundTruthVisualizer />

          <div className="mt-10">
            <Note>
              Pooling scores retrievers against a consensus they helped produce, and
              hybrid retrieval is structurally closer to that consensus than dense or
              sparse. Read pooled Precision@K and Recall@K as{" "}
              <em>agreement with the consensus</em>, not as ground truth in the
              hand-labelled sense.
            </Note>
          </div>
        </Section>

        {/* --- 9. Configuration --- */}
        <Section
          id="configure"
          number={9}
          title="What you can change per run"
          lede="The deep-analysis sidebar narrows the matrix before it runs, and whatever you pick is saved on the batch — so every stored result records the configuration that produced it."
        >
          <dl className="border-t border-border text-sm">
            {CONFIGURABLE.map((row) => (
              <div
                key={row.label}
                className="grid gap-1 border-b border-border py-3 sm:grid-cols-[14rem_1fr] sm:gap-6"
              >
                <dt className="font-medium">{row.label}</dt>
                <dd className="text-muted-foreground">{row.value}</dd>
              </div>
            ))}
          </dl>

          <Panel className="mt-10">
            <h3 className="text-lg font-semibold">Deliberately not adjustable per run</h3>
            <dl className="mt-4 space-y-5 text-sm">
              <div>
                <dt className="font-medium">Chunking</dt>
                <dd className="mt-1 text-muted-foreground">
                  Applied once at ingest (fixed 512-character chunks, 50 characters of
                  overlap). Changing it re-chunks the document, which replaces every
                  stored chunk — and takes the ground truth attached to them with it.
                  Re-upload to chunk differently.
                </dd>
              </div>
              <div>
                <dt className="font-medium">The hybrid reranker</dt>
                <dd className="mt-1 text-muted-foreground">
                  The cross-encoder is the only thing separating hybrid from dense +
                  sparse. Turn it off and hybrid becomes the same RRF fusion the
                  candidate pool uses, so the run would be scored against its own
                  algorithm.
                </dd>
              </div>
            </dl>
          </Panel>
        </Section>

        {/* --- 10. Worked example --- */}
        <Section
          id="benchmark"
          number={10}
          title="Worked example"
          lede="Inspect sample retrieval results and answer text for each method and model. Run your own analysis to calculate the three Ragas answer metrics."
        >
          <InteractiveBenchmarkSimulator />
        </Section>

        {/* --- 11. Comparison --- */}
        <Section
          id="comparison"
          number={11}
          title="Comparison with adjacent tools"
          lede="Where RAGReader differs from a plain vector store and from a general document-chat tool."
        >
          <ComparisonMatrix />
        </Section>

        {/* --- 12. Implementation --- */}
        <Section
          id="stack"
          number={12}
          title="Implementation"
          lede="No hidden services: the whole thing runs from one Docker Compose file and one OpenRouter key."
        >
          <dl className="grid gap-x-10 border-t border-border sm:grid-cols-2">
            {STACK.map((item) => (
              <div key={item.name} className="border-b border-border py-3 text-sm">
                <dt className="font-medium">{item.name}</dt>
                <dd className="text-muted-foreground">{item.note}</dd>
              </div>
            ))}
          </dl>
        </Section>

        {/* --- 13. Quick start --- */}
        <Section
          id="quickstart"
          number={13}
          title="Running it yourself"
          lede="Clone the repository, add an OpenRouter key, and bring up Docker Compose."
        >
          <QuickStartCode />
        </Section>

        {/* --- 14. FAQ --- */}
        <Section
          id="faq"
          number={14}
          title="Questions"
        >
          <dl className="border-t border-border">
            {FAQ.map((item, idx) => {
              const isOpen = openFaqIndex === idx;
              return (
                <div key={item.q} className="border-b border-border">
                  <dt>
                    <button
                      onClick={() => toggleFaq(idx)}
                      aria-expanded={isOpen}
                      className="flex w-full items-baseline justify-between gap-6 py-4 text-left font-serif text-lg font-semibold hover:text-primary"
                    >
                      <span>{item.q}</span>
                      <span
                        aria-hidden="true"
                        className="shrink-0 font-mono text-sm font-normal text-muted-foreground"
                      >
                        {isOpen ? "−" : "+"}
                      </span>
                    </button>
                  </dt>
                  {isOpen && (
                    <dd className="prose-note measure pb-5 text-base">{item.a}</dd>
                  )}
                </div>
              );
            })}
          </dl>
        </Section>

        {/* --- Closing --- */}
        <section className="border-t border-border py-14">
          <h2 className="text-2xl font-semibold">
            Run it on a document you care about
          </h2>
          <p className="prose-note measure mt-4">
            The comparison is only useful on your own content — that is the point.
            Add a source and the first answer is a few seconds away.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <a
              href="#start"
              onClick={(event) => {
                event.preventDefault();
                document
                  .getElementById("start")
                  ?.scrollIntoView({ behavior: "smooth" });
              }}
              className="border border-primary bg-primary px-5 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
            >
              Add a document
            </a>
            <Link
              to="/docs"
              className="border border-input px-5 py-2.5 text-sm font-medium transition-colors hover:bg-accent"
            >
              Read the walkthrough
            </Link>
            <Link to="/courses" className="border border-input px-5 py-2.5 text-sm font-medium transition-colors hover:bg-accent">
              Take the RAG courses
            </Link>
          </div>
        </section>
      </main>

      {/* --- Footer --- */}
      <footer className="border-t border-border">
        <div className="container mx-auto max-w-4xl px-6 py-12">
          <div className="grid gap-8 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <div className="sm:col-span-2 lg:col-span-1">
              <p className="font-serif text-lg font-semibold">RAGReader</p>
              <p className="mt-2 measure text-muted-foreground">
                Document QA that shows its work: every retrieval method, every model,
                every score, side by side.
              </p>
            </div>

            <nav aria-label="On this page">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                On this page
              </h2>
              <ul className="mt-3 space-y-1.5">
                {CONTENTS.slice(0, 5).map((item) => (
                  <li key={item.id}>
                    <a href={`#${item.id}`} className="link">
                      {item.label}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>

            <nav aria-label="Resources">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Resources
              </h2>
              <ul className="mt-3 space-y-1.5">
                <li>
                  <Link to="/docs" className="link">
                    Walkthrough guide
                  </Link>
                </li>
                <li>
                  <Link to="/courses" className="link">RAG courses</Link>
                </li>
                <li>
                  <a href={`${REPO_URL}#readme`} className="link" target="_blank" rel="noreferrer">
                    README
                  </a>
                </li>
                <li>
                  <a
                    href={`${REPO_URL}/blob/main/LICENSE`}
                    className="link"
                    target="_blank"
                    rel="noreferrer"
                  >
                    MIT licence
                  </a>
                </li>
              </ul>
            </nav>

            <nav aria-label="Project">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Project
              </h2>
              <ul className="mt-3 space-y-1.5">
                <li>
                  <a href={REPO_URL} className="link" target="_blank" rel="noreferrer">
                    Source on GitHub
                  </a>
                </li>
                <li>
                  <a href={`${REPO_URL}/issues`} className="link" target="_blank" rel="noreferrer">
                    Issue tracker
                  </a>
                </li>
                <li>
                  <a href={chattyDeskURL} className="link inline-flex items-center gap-1" target="_blank" rel="noreferrer">
                    <span>ChattyDesk (Model Lab)</span>
                    <ExternalLink className="h-2.5 w-2.5 text-muted-foreground" />
                  </a>
                </li>
                <li>
                  <a href="https://openrouter.ai/" className="link" target="_blank" rel="noreferrer">
                    OpenRouter
                  </a>
                </li>
              </ul>
            </nav>
          </div>

          <div className="mt-10 flex flex-col gap-2 border-t border-border pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-col gap-1">
              <span>
                © {new Date().getFullYear()} RAGReader · Open source under the MIT licence · Self-hosted RAG workbench
              </span>
              <span className="text-[11px] text-muted-foreground/80">
                This project is under nevatal.id for educational purposes.
              </span>
            </div>
            <div className="flex items-center gap-4">
              <Link to="/privacy" className="link">Privacy Policy</Link>
              <span>•</span>
              <Link to="/terms" className="link">Terms of Service</Link>
            </div>
            <span className="font-mono">rag.nevatal.id</span>
          </div>
        </div>
      </footer>

      <BackToTop />
    </div>
  );
};

export default LandingPage;
