import React, { useState } from "react";

const SAMPLE_DOCS = [
  {
    title: "Battle of Surabaya (1945)",
    category: "Historical Document",
    defaultQuery: "What caused the Battle of Surabaya and how is it commemorated?",
    data: {
      dense: {
        "GPT-4o mini": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.412,
          faithfulness: 0.8,
          relevance: 0.8,
          coverage: 0.75,
          answer:
            "The Battle of Surabaya in November 1945 began after tensions escalated following the murder of Brigadier A. W. S. Mallaby. Indonesian militias fought British-led troops, resulting in heavy casualties. It is commemorated annually as Heroes' Day (Hari Pahlawan).",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.435,
          faithfulness: 0.85,
          relevance: 0.82,
          coverage: 0.8,
          answer:
            "Indonesian independence forces confronted Allied forces in Surabaya after Brigadier Mallaby's death in late 1945. The intense resistance turned into a turning point for national sovereignty, honored every November 10th as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.6,
          recall: 0.75,
          f1: 0.667,
          rougeL: 0.448,
          faithfulness: 0.88,
          relevance: 0.85,
          coverage: 0.82,
          answer:
            "The battle erupted in November 1945 following the assassination of Brigadier Mallaby. Indonesian militias fought Allied forces fiercely, making Surabaya a landmark event now honored as National Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "89.2%",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "82.5%",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "78.1%",
            },
          ],
        },
      },
      sparse: {
        "GPT-4o mini": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.38,
          faithfulness: 0.75,
          relevance: 0.7,
          coverage: 0.65,
          answer:
            "BM25 keyword matching found chunks referencing 'Surabaya', 'Brigadier Mallaby', and 'November 10'. The clash led to significant battle casualties and Heroes' Day commemoration.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.395,
          faithfulness: 0.78,
          relevance: 0.72,
          coverage: 0.68,
          answer:
            "Keyword search matched exact terms for Mallaby and Surabaya. The fighting in November 1945 is commemorated as Heroes' Day across Indonesia.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.4,
          recall: 0.5,
          f1: 0.444,
          rougeL: 0.405,
          faithfulness: 0.8,
          relevance: 0.75,
          coverage: 0.7,
          answer:
            "Sparse BM25 retrieval retrieved historical entries containing exact names. Brigadier Mallaby's death triggered the conflict, now remembered as Heroes' Day on November 10.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "14.8 BM25",
            },
            {
              id: 5,
              text: "Surabaya was a major industrial center in East Java with strategic port facilities during WWII.",
              score: "11.2 BM25",
            },
          ],
        },
      },
      hybrid: {
        "GPT-4o mini": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.512,
          faithfulness: 0.95,
          relevance: 0.94,
          coverage: 0.92,
          answer:
            "Hybrid retrieval combined vector semantic similarity with BM25 keyword matching, reranked by the cross-encoder. It pinpointed Brigadier A. W. S. Mallaby's death as the key trigger of the November 1945 battle and highlighted Heroes' Day (Hari Pahlawan) on November 10.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
        "Gemini 3 Flash": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.53,
          faithfulness: 0.96,
          relevance: 0.95,
          coverage: 0.94,
          answer:
            "Cross-encoder reranking fused dense vectors and BM25 keywords, giving Gemini full context. The clash erupted over Brigadier Mallaby's assassination in Surabaya, sparking intense urban resistance that is celebrated every November 10 as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
        "Claude Haiku 4.5": {
          precision: 0.8,
          recall: 1.0,
          f1: 0.889,
          rougeL: 0.545,
          faithfulness: 0.98,
          relevance: 0.96,
          coverage: 0.95,
          answer:
            "With MS-MARCO cross-encoder reranking, Claude Haiku 4.5 received all key ground-truth chunks. The battle was ignited by Brigadier Mallaby's death, turning into a defining moment of national independence celebrated as Heroes' Day.",
          chunks: [
            {
              id: 1,
              text: "The Battle of Surabaya occurred in November 1945 following tensions and the death of British Brigadier A. W. S. Mallaby.",
              score: "94.6% Reranked",
            },
            {
              id: 3,
              text: "The conflict resulted in heavy loss of life and became a national symbol of resistance, celebrated annually as Heroes' Day on November 10.",
              score: "91.2% Reranked",
            },
            {
              id: 2,
              text: "Indonesian pro-independence fighters and militias resisted British and Indian Allied troops in fierce urban fighting.",
              score: "88.4% Reranked",
            },
          ],
        },
      },
    },
  },
];

const METHODS: { id: "dense" | "sparse" | "hybrid"; label: string; note: string }[] = [
  { id: "dense", label: "Dense", note: "Cosine similarity over embeddings" },
  { id: "sparse", label: "Sparse", note: "BM25 keyword scoring" },
  { id: "hybrid", label: "Hybrid", note: "Both, reranked by a cross-encoder" },
];

const MODEL_NAMES = ["GPT-4o mini", "Gemini 3 Flash", "Claude Haiku 4.5"];

/** A monochrome bar: the only chart here, and it carries no colour coding. */
const Bar: React.FC<{ value: number }> = ({ value }) => (
  <span
    aria-hidden="true"
    className="mt-1 block h-[3px] w-full bg-muted"
  >
    <span
      className="block h-full bg-foreground/60"
      style={{ width: `${Math.round(value * 100)}%` }}
    />
  </span>
);

export const InteractiveBenchmarkSimulator: React.FC = () => {
  const [method, setMethod] = useState<"dense" | "sparse" | "hybrid">("hybrid");
  const [model, setModel] = useState<string>("Claude Haiku 4.5");

  const doc = SAMPLE_DOCS[0];
  const result = doc.data[method][model as keyof typeof doc.data.dense];

  const retrievalMetrics = [
    { label: "Precision@K", value: result.precision },
    { label: "Recall@K", value: result.recall },
    { label: "F1@K", value: result.f1 },
  ];

  const answerMetrics = [
    { label: "ROUGE-L F1", value: result.rougeL },
    { label: "Faithfulness", value: result.faithfulness },
    { label: "Answer relevance", value: result.relevance },
    { label: "Answer coverage", value: result.coverage },
  ];

  const choice = (active: boolean) =>
    `border px-3 py-2 text-left text-sm transition-colors ${
      active
        ? "border-foreground bg-foreground text-background"
        : "border-border text-muted-foreground hover:border-foreground/40 hover:text-foreground"
    }`;

  return (
    <div>
      {/* Controls */}
      <div className="grid gap-8 sm:grid-cols-2">
        <fieldset>
          <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Retrieval method
          </legend>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {METHODS.map((item) => (
              <button
                key={item.id}
                onClick={() => setMethod(item.id)}
                aria-pressed={method === item.id}
                title={item.note}
                className={choice(method === item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Generation model
          </legend>
          <div className="mt-3 grid grid-cols-3 gap-2">
            {MODEL_NAMES.map((name) => (
              <button
                key={name}
                onClick={() => setModel(name)}
                aria-pressed={model === name}
                className={choice(model === name)}
              >
                {name}
              </button>
            ))}
          </div>
        </fieldset>
      </div>

      {/* Result */}
      <div className="mt-10 grid gap-10 lg:grid-cols-[1fr_20rem]">
        <div>
          <dl className="border-t border-border text-sm">
            <div className="border-b border-border py-4">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Document
              </dt>
              <dd className="mt-1">
                {doc.title}{" "}
                <span className="text-muted-foreground">— {doc.category}</span>
              </dd>
            </div>
            <div className="border-b border-border py-4">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Query
              </dt>
              <dd className="mt-1">{doc.defaultQuery}</dd>
            </div>
            <div className="border-b border-border py-4">
              <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Generated answer
              </dt>
              <dd className="prose-note mt-1 text-base">{result.answer}</dd>
            </div>
          </dl>

          <h4 className="mt-8 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Retrieved chunks ({result.chunks.length})
          </h4>
          <ul className="mt-3 border-t border-border text-sm">
            {result.chunks.map((chunk) => (
              <li key={chunk.id} className="flex gap-4 border-b border-border py-3">
                <span className="w-8 shrink-0 font-mono text-xs text-muted-foreground tabular">
                  #{chunk.id}
                </span>
                <p className="flex-1 text-muted-foreground">{chunk.text}</p>
                <span className="w-28 shrink-0 text-right font-mono text-xs tabular">
                  {chunk.score}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Scores */}
        <div>
          <h4 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Scores
          </h4>

          <p className="mt-3 text-xs text-muted-foreground">Retrieval</p>
          <dl className="mt-1 border-t border-border">
            {retrievalMetrics.map((metric) => (
              <div key={metric.label} className="border-b border-border py-2.5">
                <div className="flex items-baseline justify-between text-sm">
                  <dt className="text-muted-foreground">{metric.label}</dt>
                  <dd className="font-mono tabular">
                    {Math.round(metric.value * 100)}%
                  </dd>
                </div>
                <Bar value={metric.value} />
              </div>
            ))}
          </dl>

          <p className="mt-6 text-xs text-muted-foreground">Answer</p>
          <dl className="mt-1 border-t border-border">
            {answerMetrics.map((metric) => (
              <div key={metric.label} className="border-b border-border py-2.5">
                <div className="flex items-baseline justify-between text-sm">
                  <dt className="text-muted-foreground">{metric.label}</dt>
                  <dd className="font-mono tabular">
                    {Math.round(metric.value * 100)}%
                  </dd>
                </div>
                <Bar value={metric.value} />
              </div>
            ))}
          </dl>

          <p className="mt-4 text-xs text-muted-foreground">
            Recorded results, normalized to 0–100%. A live run also reports ROUGE-L
            precision and recall, for nine metrics in total.
          </p>
        </div>
      </div>
    </div>
  );
};

export default InteractiveBenchmarkSimulator;
