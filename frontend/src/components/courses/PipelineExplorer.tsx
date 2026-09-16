import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

const stages = [
  { title: "Ingest", detail: "Extract the document, split it into understandable chunks, and preserve each source's identity. Build the indexes before the first question.", example: "The handbook becomes source passages containing the standard cache rule and the Atlas exception.", href: "/courses/rag-fundamentals/ingestion-and-chunking" },
  { title: "Prepare a query", detail: "Keep the original question as the task. Rewriting, abstraction, hypothetical passages, and memory can provide additional search inputs.", example: "“How does Atlas differ?” becomes explicit searches for the two cache durations and the reason for the exception.", href: "/courses/query-methods" },
  { title: "Retrieve", detail: "Find candidates with dense or lexical search. Fuse rankings or retrieve through larger units when the question needs broader evidence.", example: "Dense search matches meaning; BM25 matches Atlas by name. Their candidate lists may contain different passages.", href: "/courses/retrieval-methods" },
  { title: "Refine evidence", detail: "Check relevance and sufficiency, search again when needed, and pack the final source text into a finite context budget.", example: "Discard the unrelated log-retention passage and retain both the 15-minute rule and the 5-minute exception.", href: "/courses/adaptive-pipelines" },
  { title: "Write an answer", detail: "The reader answers the original question from actual source passages. Demonstrations can teach a pattern; they are separate from evidence.", example: "“The standard cache is 15 minutes. Atlas uses 5 minutes because its catalog changes more frequently.”", href: "/courses/rag-fundamentals/grounded-generation" },
  { title: "Evaluate", detail: "Check retrieved source IDs and generated claims separately. Independent references and visible missing scores make comparisons interpretable.", example: "Did both facts reach the reader? Are the answer's claims supported? Does it fully answer the comparison?", href: "/courses/evaluation" },
];

export default function PipelineExplorer() {
  const [active, setActive] = useState(0);
  const stage = stages[active];
  return (
    <section aria-labelledby="pipeline-explorer-heading" className="my-12 border-y border-border py-8">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="pipeline-explorer-heading" className="text-xl font-semibold">Follow a question through RAG</h2>
        <p className="text-xs text-muted-foreground">Select a stage to explore</p>
      </div>
      <div className="mt-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" role="group" aria-label="RAG pipeline stages">
        {stages.map((item, index) => (
          <button key={item.title} type="button" aria-pressed={index === active} aria-controls="pipeline-explanation" onClick={() => setActive(index)}
            className={`flex min-h-14 items-center gap-2 border px-3 py-3 text-left text-sm transition-colors ${index === active ? "border-primary bg-primary/5 text-primary" : "border-border hover:bg-muted"}`}>
            <span className="font-mono text-xs" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            {item.title}
          </button>
        ))}
      </div>
      <div id="pipeline-explanation" className="mt-5 grid gap-4 sm:grid-cols-2 sm:gap-8" aria-live="polite">
        <div>
          <h3 className="font-semibold">{stage.title}</h3>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{stage.detail}</p>
          <Link to={stage.href} className="link mt-3 inline-flex items-center gap-2 text-sm">Study this stage <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
        </div>
        <blockquote className="border-l-2 border-primary/40 pl-5 font-serif text-base leading-relaxed">
          <span className="mb-2 block font-sans text-xs uppercase tracking-wide text-muted-foreground">Northstar example</span>
          {stage.example}
        </blockquote>
      </div>
    </section>
  );
}
