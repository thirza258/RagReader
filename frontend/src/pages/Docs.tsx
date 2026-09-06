import React from "react";
import { steps } from "../components/data/DocsData";
import SEO from "../components/SEO";

const Docs: React.FC = () => {
  return (
    <div className="min-h-screen bg-background text-foreground">
      <SEO
        title="Walkthrough Guide — RAGReader Step-by-Step"
        description="Learn how to upload documents, ask questions, select ground truth, and run 9-pipeline RAG benchmarks step-by-step with screenshots."
        canonicalUrl="https://rag.nevatal.tech/docs"
      />

      <main className="container mx-auto max-w-4xl px-6 pb-24 pt-28">
        <header className="border-b border-border pb-12">
          <h1 className="text-4xl font-semibold">RAGReader, step by step</h1>
          <p className="prose-note measure mt-4">
            Every screen you'll pass through, from signing in to reading the
            evaluation metrics for each retrieval method and model.
          </p>
        </header>

        <ol>
          {steps.map((step) => (
            <li key={step.id} className="grid gap-6 border-b border-border py-10 md:grid-cols-2 md:gap-10">
              <div>
                <p className="font-mono text-sm text-muted-foreground tabular">
                  {String(step.id).padStart(2, "0")}
                </p>
                <h2 className="mt-2 text-xl font-semibold">{step.title}</h2>
                <p className="prose-note mt-3 text-base">{step.description}</p>
              </div>

              <figure className="border border-border">
                {step.imagePath ? (
                  <img
                    src={step.imagePath}
                    alt={step.imageAlt}
                    loading="lazy"
                    className="aspect-video w-full object-cover"
                  />
                ) : (
                  <div className="flex aspect-video w-full items-center justify-center bg-muted px-4 text-center text-xs text-muted-foreground">
                    {step.imagePlaceholderText}
                  </div>
                )}
              </figure>
            </li>
          ))}
        </ol>
      </main>
    </div>
  );
};

export default Docs;
