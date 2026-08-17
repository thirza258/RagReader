import React, { useEffect } from "react";
import { steps } from "../components/data/DocsData";

const Docs: React.FC = () => {
  // The SPA serves one static <head> for every route (see index.html), so the
  // per-page title is set here rather than in a meta framework.
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Walkthrough — RAGReader, step by step";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  return (
    <div className="my-12 min-h-screen bg-background text-foreground font-sans selection:bg-primary selection:text-primary-foreground">
      <main className="container mx-auto px-4 py-12 max-w-5xl">
        <header className="mb-12 pt-12 max-w-3xl">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary mb-3">
            Walkthrough
          </p>
          <h1 className="text-4xl font-bold text-foreground mb-4">
            RAGReader, step by step
          </h1>
          <p className="text-lg text-muted-foreground leading-relaxed">
            Every screen you'll pass through, from signing in to reading the
            evaluation metrics for each retrieval method and model.
          </p>
        </header>

        <div className="relative border-l border-border ml-4 md:ml-6 space-y-12">
          {steps.map((step) => (
            <div key={step.id} className="relative pl-8 md:pl-12">
              {/* Timeline Dot */}
              <div className="absolute -left-[20px] top-0 flex h-10 w-10 items-center justify-center rounded-full border border-border bg-card shadow-sm ring-4 ring-background">
                <span className="text-primary font-bold text-sm">
                  {step.id}
                </span>
              </div>

              {/* Content Card */}
              <div className="grid gap-6 md:grid-cols-2 bg-card/50 border border-border rounded-lg p-6 hover:border-primary/50 transition-colors duration-300">
                {/* Text Content */}
                <div className="flex flex-col justify-center space-y-4">
                  <div className="flex items-center gap-3">
                    <div className="p-2 rounded-md bg-accent text-primary">
                      {step.icon}
                    </div>
                    <h2 className="text-2xl font-bold text-foreground">
                      {step.title}
                    </h2>
                  </div>
                  <p className="text-muted-foreground leading-relaxed">
                    {step.description}
                  </p>
                </div>

                {/* Image Content */}
                <div className="relative rounded-lg overflow-hidden border border-border bg-muted/30 aspect-video group cursor-pointer">
                  <div className="absolute inset-0 flex items-center justify-center bg-black/20 group-hover:bg-transparent transition-all z-10">
                    <span className="sr-only">View Screenshot</span>
                  </div>
                  <img
                    src={
                      step.imagePath ||
                      `https://placehold.co/600x400/0f172a/06b6d4?text=${encodeURIComponent(step.imagePlaceholderText)}`
                    }
                    alt={step.imageAlt}
                    className="w-full h-full object-cover opacity-90 group-hover:opacity-100 group-hover:scale-105 transition-all duration-500"
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
};

export default Docs;
