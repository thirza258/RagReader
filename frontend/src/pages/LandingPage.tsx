import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";

import service from "../services/service";
import { SubmitPayload } from "../types/types";

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
  { term: "Retrieval methods", def: "Dense, sparse (BM25), hybrid with cross-encoder reranking" },
  { term: "Language models", def: "Any model OpenRouter serves; GPT-4o mini, Gemini 3 Flash and Claude Haiku 4.5 are the defaults" },
  { term: "Pipelines per run", def: "Every selected method × every selected model, up to a fixed cap" },
  { term: "Metrics per pipeline", def: "Three retrieval, six answer" },
  { term: "Results transport", def: "Streamed over a WebSocket as each pipeline finishes" },
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
      ["ROUGE-L F1", "41.2%"],
      ["Faithfulness", "80.0%"],
      ["Answer relevance", "80.0%"],
    ],
  },
];

const CONTENTS = [
  { id: "how-it-works", label: "How it works" },
  { id: "retrieval", label: "Retrieval methods" },
  { id: "models", label: "Models" },
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
      "Every chunk is embedded with openai/text-embedding-3-small and ranked by cosine similarity against the embedded query. This is also the method that answers in the normal chat.",
  },
  {
    name: "Sparse retrieval",
    summary: "BM25 keyword search.",
    detail:
      "BM25Okapi over a corpus that is lowercased, stripped of punctuation and filtered through NLTK's English stopword list. Exact terms, names and numbers survive here even when embeddings blur them.",
  },
  {
    name: "Hybrid retrieval",
    summary: "Dense and sparse candidates, reranked by a cross-encoder.",
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
  { label: "Models", value: "Any models OpenRouter serves; the three defaults come pre-selected" },
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
    a: "Not on the hosted app. If you self-host, one OPENROUTER_API_KEY covers every model — the LLMs, the embeddings and the evaluation judge all go through OpenRouter. That single key is also why the model selector can offer OpenRouter's whole catalogue rather than a fixed list.",
  },
  {
    q: "How many pipelines run at once?",
    a: "Three retrieval methods times however many models you select — nine by default. Narrow either axis in the deep-analysis sidebar and the run gets smaller; widen the model list and it grows, up to a cap, because every extra variant is another full retrieve-generate-judge cycle. The configuration you used is stored with the batch, so a result always records how it was produced.",
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
    <div className="min-h-screen bg-background text-foreground">
      <SEO
        title="RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines"
        description="Ask questions about your own PDF, URL, or pasted text, then score the answer across 9 RAG pipelines — Dense, Sparse and Hybrid retrieval x three LLMs."
        canonicalUrl="https://rag.nevatal.tech/"
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
            three retrieval methods across three LLMs — and reports nine scores for
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
            One source at a time: a PDF, a web page URL, or pasted text. New here?{" "}
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
              Figure 1. One pipeline's result. Nine metrics per pipeline are reported
              live during a deep-analysis run; six are shown here.
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
          title="Retrieval methods"
          lede="The three methods disagree in interesting ways — semantics catches paraphrase, keywords catch exact names, and the reranker arbitrates. Running all three on your document is how you find out which one your content rewards."
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

        {/* --- 3. Models --- */}
        <Section
          id="models"
          number={3}
          title="Models"
          lede="Each pipeline is end-to-end: the model rewrites your question into a search query, retrieves with its assigned method, and generates at temperature 0 — so its scores reflect the whole chain, query rewriting included. All traffic is routed through OpenRouter with a single API key, which is what lets the selector offer any model OpenRouter serves rather than a fixed three."
        >
          <h3 className="text-lg font-semibold">Defaults</h3>
          <p className="prose-note measure mt-2 text-base">
            These three are pre-selected. Swap in any other OpenRouter model from
            the deep-analysis sidebar — the list there is fetched live, with price
            and context length, and searchable.
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

          <h3 className="mt-12 text-lg font-semibold">Supporting models</h3>
          <dl className="mt-4 border-t border-border">
            {SUPPORTING_MODELS.map((item) => (
              <div
                key={item.id}
                className="grid gap-1 border-b border-border py-4 sm:grid-cols-[11rem_1fr] sm:gap-6"
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

        {/* --- 4. Metrics --- */}
        <Section
          id="metrics"
          number={4}
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
                Faithfulness, relevance and coverage are judged by Mistral Nemo on a
                1–5 scale and reported normalized to 0–1, so every metric shares one
                axis.
              </p>
            </div>
          </div>

          <div className="mt-10">
            <Note>
              Metrics only exist where ground truth does. Without ground-truth chunks
              the retrieval scores have nothing to compare against, and without an
              expected answer the answer metrics are skipped entirely — which is why
              setting ground truth is a step in the flow rather than an optional
              extra.
            </Note>
          </div>
        </Section>

        {/* --- 5. Ground truth --- */}
        <Section
          id="ground-truth"
          number={5}
          title="Ground truth"
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

        {/* --- 6. Configuration --- */}
        <Section
          id="configure"
          number={6}
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

        {/* --- 7. Worked example --- */}
        <Section
          id="benchmark"
          number={7}
          title="Worked example"
          lede="Recorded results for one sample document. Switch the retrieval method or the model to see how the same question scores differently before you run your own."
        >
          <InteractiveBenchmarkSimulator />
        </Section>

        {/* --- 8. Comparison --- */}
        <Section
          id="comparison"
          number={8}
          title="Comparison with adjacent tools"
          lede="Where RAGReader differs from a plain vector store and from a general document-chat tool."
        >
          <ComparisonMatrix />
        </Section>

        {/* --- 9. Implementation --- */}
        <Section
          id="stack"
          number={9}
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

        {/* --- 10. Quick start --- */}
        <Section
          id="quickstart"
          number={10}
          title="Running it yourself"
          lede="Clone the repository, add an OpenRouter key, and bring up Docker Compose."
        >
          <QuickStartCode />
        </Section>

        {/* --- 11. FAQ --- */}
        <Section
          id="faq"
          number={11}
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
                  <a href="https://openrouter.ai/" className="link" target="_blank" rel="noreferrer">
                    OpenRouter
                  </a>
                </li>
              </ul>
            </nav>
          </div>

          <div className="mt-10 flex flex-col gap-2 border-t border-border pt-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <span>
              © {new Date().getFullYear()} RAGReader · Open source under the MIT licence
            </span>
            <span className="font-mono">rag.nevatal.tech</span>
          </div>
        </div>
      </footer>

      <BackToTop />
    </div>
  );
};

export default LandingPage;
