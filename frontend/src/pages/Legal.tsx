import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import SEO from "../components/SEO";

export default function Legal() {
  const location = useLocation();
  const [tab, setTab] = useState<"privacy" | "terms">(
    location.pathname.includes("terms") ? "terms" : "privacy"
  );

  return (
    <div className="min-h-screen bg-background text-foreground">
      <SEO
        title="Legal &amp; Privacy Policies — RAGReader"
        description="Transparency regarding RAGReader's self-hosted architecture, local document storage, and OpenRouter AI integrations."
        canonicalUrl={`https://rag.nevatal.id/${tab}`}
      />

      <main className="container mx-auto max-w-4xl px-6 pb-24 pt-28">
        <header className="border-b border-border pb-8">
          <div className="flex items-center gap-2 text-xs font-mono uppercase tracking-wider text-muted-foreground mb-2">
            <Link to="/" className="hover:text-foreground">Home</Link>
            <span>/</span>
            <span>Legal &amp; Policies</span>
          </div>
          <h1 className="text-4xl font-semibold">Privacy Policy &amp; Terms of Service</h1>
          <p className="prose-note measure mt-3 text-base">
            Understand how data is processed in our self-hosted RAG architecture and how inference is executed via OpenRouter.
          </p>

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => setTab("privacy")}
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                tab === "privacy"
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              Privacy Policy
            </button>
            <button
              onClick={() => setTab("terms")}
              className={`px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                tab === "terms"
                  ? "bg-foreground text-background"
                  : "bg-muted text-muted-foreground hover:text-foreground"
              }`}
            >
              Terms of Service
            </button>
          </div>
        </header>

        {tab === "privacy" ? (
          <div className="mt-10 space-y-10 leading-relaxed text-sm">
            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">1. 100% Self-Hosted &amp; Private Storage</h2>
              <p className="text-muted-foreground mb-3">
                RAGReader is an open-source, fully self-hosted Retrieval-Augmented Generation benchmarking workbench.
                All uploaded documents, chunked text passages, vector store embeddings, ground truth selections,
                evaluation run results, and user accounts reside strictly within your self-hosted Docker volumes and PostgreSQL database.
              </p>
              <p className="text-muted-foreground">
                There are zero third-party telemetry scripts, analytics trackers, or commercial data brokers.
                Your uploaded documents and evaluation benchmarks are never monetized, rented, or transmitted to outside third parties.
              </p>
            </section>

            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">2. AI Inference via OpenRouter</h2>
              <p className="text-muted-foreground mb-3">
                RAGReader routes its LLM generation traffic through <strong>OpenRouter</strong> to allow benchmarking against
                multiple foundation models with a unified API interface.
              </p>
              <p className="text-muted-foreground mb-3">
                When you run a benchmark query or request deep analysis:
              </p>
              <ul className="list-disc pl-5 space-y-1 text-muted-foreground mb-4">
                <li>Only the query string, rewritten prompt, and specific retrieved context chunks needed to generate the answer are transmitted to OpenRouter.</li>
                <li>Your broader document library, host system configuration, and internal network parameters remain isolated.</li>
              </ul>
              <div className="rounded-lg border border-border bg-card p-4">
                <p className="text-xs font-mono uppercase font-semibold text-foreground mb-2">
                  OpenRouter Terms &amp; Policies:
                </p>
                <div className="flex flex-wrap gap-4 text-xs font-medium">
                  <a
                    href="https://openrouter.ai/privacy"
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline hover:text-muted-foreground"
                  >
                    OpenRouter Privacy Policy &rarr;
                  </a>
                  <a
                    href="https://openrouter.ai/terms"
                    target="_blank"
                    rel="noreferrer"
                    className="text-foreground underline hover:text-muted-foreground"
                  >
                    OpenRouter Terms of Service &rarr;
                  </a>
                </div>
              </div>
            </section>

            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">3. Data Retention &amp; Management</h2>
              <p className="text-muted-foreground">
                Because this installation is completely self-hosted, you maintain absolute control over all stored documents and indices.
                Deleting a document or purging evaluation records removes those records from the local disk and vector indices immediately.
              </p>
            </section>

            <section className="pb-8">
              <h2 className="text-xl font-semibold mb-3">4. Privacy Contact</h2>
              <p className="text-muted-foreground">
                For questions regarding data handling or privacy practices, contact us at:{" "}
                <a href="mailto:nevatalapp@gmail.com" className="font-semibold text-foreground underline">
                  nevatalapp@gmail.com
                </a>
              </p>
            </section>
          </div>
        ) : (
          <div className="mt-10 space-y-10 leading-relaxed text-sm">
            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">1. Agreement to Terms</h2>
              <p className="text-muted-foreground">
                By hosting, accessing, or evaluating models with RAGReader, you agree to these Terms of Service.
                RAGReader is designed for research, benchmarking, and evaluating document retrieval systems.
              </p>
            </section>

            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">2. Evaluation Metrics &amp; AI Output Notice</h2>
              <p className="text-muted-foreground mb-3">
                All benchmark scores, faithfulness ratings, answer relevancy metrics, and generated responses are experimental evaluations produced by automated RAG pipelines.
              </p>
              <p className="text-muted-foreground">
                Maintainers make no guarantee of factual perfection or zero-hallucination outputs. Users are advised to review source chunk citations before relying on outputs in mission-critical applications.
              </p>
            </section>

            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">3. OpenRouter Usage Compliance</h2>
              <p className="text-muted-foreground mb-3">
                When using generative AI models via OpenRouter, users must adhere to OpenRouter&apos;s acceptable use guidelines:
              </p>
              <div className="flex flex-wrap gap-4 text-xs font-medium">
                <a
                  href="https://openrouter.ai/terms"
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground underline hover:text-muted-foreground"
                >
                  OpenRouter Terms of Service &rarr;
                </a>
                <a
                  href="https://openrouter.ai/privacy"
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground underline hover:text-muted-foreground"
                >
                  OpenRouter Privacy Policy &rarr;
                </a>
              </div>
            </section>

            <section className="border-b border-border pb-8">
              <h2 className="text-xl font-semibold mb-3">4. Disclaimer of Warranty</h2>
              <p className="text-muted-foreground">
                RAGReader is provided under the MIT license on an &ldquo;AS IS&rdquo; basis without warranties of any kind.
                In no event shall the authors or contributors be liable for any claim, damages, or other liability.
              </p>
            </section>

            <section className="pb-8">
              <h2 className="text-xl font-semibold mb-3">5. Terms Contact</h2>
              <p className="text-muted-foreground">
                For questions regarding terms and licensing, reach out to:{" "}
                <a href="mailto:nevatalapp@gmail.com" className="font-semibold text-foreground underline">
                  nevatalapp@gmail.com
                </a>
              </p>
            </section>
          </div>
        )}

        <footer className="mt-12 border-t border-border pt-6 text-xs text-muted-foreground flex items-center justify-between">
          <p>RAGReader · Self-Hosted Multi-Pipeline RAG Benchmark</p>
          <p>Contact: nevatalapp@gmail.com</p>
        </footer>
      </main>
    </div>
  );
}
