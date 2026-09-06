import React, { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Loader2, Search } from "lucide-react";
import service from "../services/service";
import {
  AnalysisConfigOptions,
  CatalogModel,
  DeepAnalysisConfig,
  GroundTruthMode,
} from "../interface";

const cn = (...classes: (string | undefined | boolean)[]) =>
  classes.filter(Boolean).join(" ");

export interface AnalysisRunState {
  isRunning: boolean;
  completed: number;
  total: number;
}

interface DeepSidebarProps {
  file?: File;
  conversationId: string | null;
  documentId: string | null;
  runState: AnalysisRunState;
  onBack: () => void;
  onAnalyze: (config: DeepAnalysisConfig) => void;
  onStop: () => void;
}

// Used only until GET /analysis-config/ answers, so the panel never renders
// with an empty selection. The server is the authority on every value here.
const FALLBACK_OPTIONS: AnalysisConfigOptions = {
  retrieval_methods: [
    { id: "Dense Retrieval", label: "Dense" },
    { id: "Sparse Retrieval", label: "Sparse" },
    { id: "Hybrid Retrieval", label: "Hybrid" },
  ],
  models: [],
  default_models: [],
  model_catalog: { source: "defaults", count: 0, error: null },
  rerankers: [],
  ground_truth_modes: [
    { id: "manual", label: "Manual selection" },
    { id: "pooled", label: "Candidate pooling (RRF)" },
  ],
  top_k: { min: 1, max: 20, default: 5 },
  pool_top_n: { min: 1, max: 50, default: 10 },
  temperature: { min: 0, max: 2, default: 0 },
  child_top_k: { min: 1, max: 50, default: 10 },
  rrf_k: { min: 1, max: 1000, default: 60 },
  judge_model: { default: "mistralai/mistral-nemo" },
  ingest: {
    embedding_model: "openai/text-embedding-3-small",
    chunk_strategy: "fixed",
    chunk_size: 512,
    overlap: 50,
  },
  defaults: {
    methods: ["Dense Retrieval", "Sparse Retrieval", "Hybrid Retrieval"],
    models: [],
    top_k: 5,
    ground_truth_mode: "manual",
    pool_top_n: 10,
    temperature: 0,
    child_top_k: 10,
    rrf_k: 60,
    reranker_model: "cross-encoder/ms-marco-MiniLM-L6-v2",
    judge_model: "mistralai/mistral-nemo",
  },
  max_variants: 12,
};

const SectionHeader: React.FC<{ title: string }> = ({ title }) => (
  <h3 className="mb-3 border-b border-border pb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
    {title}
  </h3>
);

/** A control that exists in the UI but cannot be changed here, plus why. */
const LockedNote: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="border-l-2 border-border py-1 pl-3 text-xs text-muted-foreground">
    {children}
  </div>
);

/** A labelled slider with its current value shown in tabular figures. */
const Slider: React.FC<{
  id: string;
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  hint?: React.ReactNode;
}> = ({ id, label, value, min, max, step = 1, onChange, hint }) => (
  <div>
    <div className="mb-2 flex items-baseline justify-between">
      <label htmlFor={id} className="text-sm">
        {label}
      </label>
      <span className="font-mono text-sm tabular">{value}</span>
    </div>
    <input
      id={id}
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(event) => onChange(Number(event.target.value))}
      className="h-1 w-full cursor-pointer appearance-none bg-border accent-primary"
    />
    {hint && <p className="mt-2 text-xs text-muted-foreground">{hint}</p>}
  </div>
);

/** Price per million tokens — the unit people actually compare on. */
const perMillion = (price?: number | null) =>
  typeof price === "number" && price > 0
    ? `$${(price * 1_000_000).toFixed(2)}/M`
    : null;

const DeepSidebar: React.FC<DeepSidebarProps> = ({
  file,
  conversationId,
  documentId,
  runState,
  onBack,
  onAnalyze,
  onStop,
}) => {
  const [options, setOptions] = useState<AnalysisConfigOptions>(FALLBACK_OPTIONS);
  const [isLoadingOptions, setIsLoadingOptions] = useState(true);

  const [methods, setMethods] = useState<string[]>(FALLBACK_OPTIONS.defaults.methods);
  const [models, setModels] = useState<string[]>([]);
  const [topK, setTopK] = useState<number>(FALLBACK_OPTIONS.top_k.default);
  const [groundTruthMode, setGroundTruthMode] = useState<GroundTruthMode>("manual");
  const [poolTopN, setPoolTopN] = useState<number>(FALLBACK_OPTIONS.pool_top_n.default);

  const [temperature, setTemperature] = useState<number>(FALLBACK_OPTIONS.temperature.default);
  const [childTopK, setChildTopK] = useState<number>(FALLBACK_OPTIONS.child_top_k.default);
  const [rrfK, setRrfK] = useState<number>(FALLBACK_OPTIONS.rrf_k.default);
  const [rerankerModel, setRerankerModel] = useState<string>(
    FALLBACK_OPTIONS.defaults.reranker_model
  );
  const [judgeModel, setJudgeModel] = useState<string>(FALLBACK_OPTIONS.judge_model.default);

  const [modelQuery, setModelQuery] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  // The option set is served rather than hardcoded — the ranges here must
  // match the ones the backend clamps to, and the model catalogue comes
  // straight from OpenRouter.
  useEffect(() => {
    let cancelled = false;
    service
      .getAnalysisConfig()
      .then((config) => {
        if (cancelled) return;
        setOptions(config);
        setMethods(config.defaults.methods);
        setModels(config.defaults.models);
        setTopK(config.defaults.top_k);
        setGroundTruthMode(config.defaults.ground_truth_mode);
        setPoolTopN(config.defaults.pool_top_n);
        setTemperature(config.defaults.temperature);
        setChildTopK(config.defaults.child_top_k);
        setRrfK(config.defaults.rrf_k);
        setRerankerModel(config.defaults.reranker_model);
        setJudgeModel(config.defaults.judge_model);
      })
      .catch((error) => console.error("Failed to load analysis config:", error))
      .finally(() => !cancelled && setIsLoadingOptions(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value];

  const variantCount = methods.length * models.length;
  const maxModels = Math.max(1, Math.floor(options.max_variants / Math.max(methods.length, 1)));
  const overCap = variantCount > options.max_variants;
  const canRun =
    Boolean(conversationId) && variantCount > 0 && !overCap && !runState.isRunning;

  /** Selected models first, then whatever the search matches. */
  const visibleModels = useMemo(() => {
    const needle = modelQuery.trim().toLowerCase();
    const matches = (model: CatalogModel) =>
      !needle ||
      model.id.toLowerCase().includes(needle) ||
      model.label.toLowerCase().includes(needle) ||
      (model.provider ?? "").toLowerCase().includes(needle);

    const selected = models
      .map(
        (id) =>
          options.models.find((model) => model.id === id) ?? {
            id,
            label: id,
            is_default: false,
          }
      )
      .filter(matches);

    const rest = options.models.filter((model) => !models.includes(model.id)).filter(matches);

    return [...selected, ...rest];
  }, [models, modelQuery, options.models]);

  const config: DeepAnalysisConfig = useMemo(
    () => ({
      methods,
      models,
      top_k: topK,
      ground_truth_mode: groundTruthMode,
      pool_top_n: poolTopN,
      temperature,
      child_top_k: childTopK,
      rrf_k: rrfK,
      reranker_model: rerankerModel,
      judge_model: judgeModel,
    }),
    [
      methods,
      models,
      topK,
      groundTruthMode,
      poolTopN,
      temperature,
      childTopK,
      rrfK,
      rerankerModel,
      judgeModel,
    ]
  );

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + ["B", "KB", "MB", "GB"][i];
  };

  return (
    <aside className="z-20 flex h-full w-1/3 min-w-[320px] max-w-[380px] flex-col border-r border-border bg-muted">
      {/* --- HEADER --- */}
      <div className="flex items-center gap-3 border-b border-border px-5 py-4">
        <button
          onClick={onBack}
          aria-label="Back"
          className="p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h2 className="font-serif text-lg font-semibold">Deep analysis</h2>
          <p className="text-xs text-muted-foreground">Run configuration</p>
        </div>
      </div>

      <div className="custom-scrollbar flex-1 space-y-8 overflow-y-auto px-5 py-5">
        {/* --- 1. TARGET METADATA --- */}
        <section>
          <SectionHeader title="Target" />
          {file ? (
            <div className="border border-border bg-background p-4">
              <div className="mb-1 flex items-baseline justify-between gap-3">
                <p className="truncate text-sm font-medium" title={file.name}>
                  {file.name}
                </p>
                <span className="shrink-0 font-mono text-xs text-muted-foreground tabular">
                  {formatSize(file.size)}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {file.type || "Unknown type"}
              </p>
            </div>
          ) : (
            <div className="border border-dashed border-border p-4">
              <p className="text-sm text-muted-foreground">
                {conversationId
                  ? `Conversation ${conversationId}`
                  : "No conversation loaded"}
              </p>
              {documentId && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Document {documentId}
                </p>
              )}
            </div>
          )}
        </section>

        {/* --- 2. RETRIEVAL METHODS --- */}
        <section>
          <SectionHeader title="Retrieval methods" />
          <div className="space-y-2">
            {options.retrieval_methods.map((option) => (
              <label
                key={option.id}
                title={option.description}
                className="flex cursor-pointer items-center justify-between border border-border bg-background px-3 py-2.5 transition-colors hover:bg-accent"
              >
                <span className="text-sm">{option.label}</span>
                <input
                  type="checkbox"
                  checked={methods.includes(option.id)}
                  onChange={() => setMethods((prev) => toggle(prev, option.id))}
                  className="h-4 w-4 accent-primary"
                />
              </label>
            ))}
          </div>
        </section>

        {/* --- 3. MODELS --- */}
        <section>
          <SectionHeader title="Models" />

          {isLoadingOptions ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 size={14} className="animate-spin" /> Loading models…
            </div>
          ) : (
            <>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input
                  type="search"
                  value={modelQuery}
                  onChange={(event) => setModelQuery(event.target.value)}
                  placeholder={`Search ${options.model_catalog.count} models`}
                  aria-label="Search models"
                  className="w-full border border-input bg-background py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
                />
              </div>

              <p className="mt-2 text-xs text-muted-foreground">
                {models.length} of at most {maxModels} selected
                {options.model_catalog.source === "defaults" && (
                  <>
                    {" · "}
                    <span title={options.model_catalog.error ?? undefined}>
                      OpenRouter catalogue unavailable, showing the defaults
                    </span>
                  </>
                )}
              </p>

              <div className="custom-scrollbar mt-3 max-h-72 space-y-2 overflow-y-auto pr-1">
                {visibleModels.length === 0 && (
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    No model matches “{modelQuery}”.
                  </p>
                )}

                {visibleModels.map((model) => {
                  const isSelected = models.includes(model.id);
                  // Selecting more than the cap allows would be rejected
                  // server-side, so stop it here rather than silently trim.
                  const isBlocked = !isSelected && models.length >= maxModels;
                  const price = perMillion(model.prompt_price);

                  return (
                    <label
                      key={model.id}
                      className={cn(
                        "flex items-start gap-3 border px-3 py-2.5 transition-colors",
                        isBlocked
                          ? "cursor-not-allowed border-border opacity-40"
                          : "cursor-pointer",
                        isSelected
                          ? "border-foreground/40 bg-accent"
                          : !isBlocked && "border-border bg-background hover:bg-accent"
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={isSelected}
                        disabled={isBlocked}
                        onChange={() => setModels((prev) => toggle(prev, model.id))}
                        className="mt-0.5 h-4 w-4 shrink-0 accent-primary"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-sm font-medium">{model.label}</span>
                          {model.is_default && (
                            <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">
                              default
                            </span>
                          )}
                        </span>
                        <span className="block truncate font-mono text-[11px] text-muted-foreground">
                          {model.id}
                        </span>
                        {(price || model.context_length) && (
                          <span className="block text-[11px] text-muted-foreground">
                            {[
                              price,
                              model.context_length
                                ? `${Math.round(model.context_length / 1000)}k ctx`
                                : null,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                        )}
                      </span>
                    </label>
                  );
                })}
              </div>
            </>
          )}
        </section>

        {/* --- 4. RETRIEVAL DEPTH --- */}
        <section>
          <SectionHeader title="Retrieval depth" />
          <Slider
            id="top-k"
            label="Retrieved chunks (Top-K)"
            value={topK}
            min={options.top_k.min}
            max={options.top_k.max}
            onChange={setTopK}
            hint="How many chunks each method feeds the model. Also the K in Precision@K and Recall@K."
          />
        </section>

        {/* --- 5. GROUND TRUTH --- */}
        <section>
          <SectionHeader title="Ground truth" />
          <div className="space-y-2">
            {options.ground_truth_modes.map((option) => (
              <label
                key={option.id}
                className={cn(
                  "flex cursor-pointer items-start gap-3 border px-3 py-2.5 transition-colors",
                  groundTruthMode === option.id
                    ? "border-foreground/40 bg-accent"
                    : "border-border bg-background hover:bg-accent"
                )}
              >
                <input
                  type="radio"
                  name="groundTruthMode"
                  checked={groundTruthMode === option.id}
                  onChange={() => setGroundTruthMode(option.id as GroundTruthMode)}
                  className="mt-1 accent-primary"
                />
                <span>
                  <span className="block text-sm font-medium">{option.label}</span>
                  {option.description && (
                    <span className="block text-[11px] text-muted-foreground">
                      {option.description}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>

          {groundTruthMode === "pooled" && (
            <div className="mt-3">
              <Slider
                id="pool-top-n"
                label="Pool depth"
                value={poolTopN}
                min={options.pool_top_n.min}
                max={options.pool_top_n.max}
                onChange={setPoolTopN}
                hint="Running the analysis re-pools and overwrites this conversation's ground truth. Keep the pool deeper than Top-K, or the ground truth becomes a near-copy of a single run's output."
              />
            </div>
          )}
        </section>

        {/* --- 6. ADVANCED (still per run) --- */}
        <section>
          <SectionHeader title="Advanced" />
          <button
            type="button"
            onClick={() => setShowAdvanced((open) => !open)}
            aria-expanded={showAdvanced}
            className="w-full border border-border bg-background px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
          >
            {showAdvanced ? "Hide" : "Show"} generation and fusion settings
          </button>

          {showAdvanced && (
            <div className="mt-4 space-y-6">
              <Slider
                id="temperature"
                label="Temperature"
                value={temperature}
                min={options.temperature.min}
                max={options.temperature.max}
                step={0.1}
                onChange={setTemperature}
                hint="0 keeps every pipeline deterministic, which is what makes two runs comparable."
              />

              <Slider
                id="child-top-k"
                label="Hybrid candidate pool"
                value={childTopK}
                min={options.child_top_k.min}
                max={options.child_top_k.max}
                onChange={setChildTopK}
                hint="How many candidates dense and sparse each hand the reranker. Widens automatically if Top-K would otherwise leave nothing to rerank."
              />

              <Slider
                id="rrf-k"
                label="RRF constant (k)"
                value={rrfK}
                min={options.rrf_k.min}
                max={options.rrf_k.max}
                onChange={setRrfK}
                hint="The 60 in 1/(k + rank). Larger flattens the weight given to top ranks."
              />

              <div>
                <label htmlFor="reranker" className="mb-1.5 block text-sm">
                  Reranker
                </label>
                <select
                  id="reranker"
                  value={rerankerModel}
                  onChange={(event) => setRerankerModel(event.target.value)}
                  className="w-full border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary"
                >
                  {(options.rerankers.length
                    ? options.rerankers
                    : [{ id: rerankerModel, label: rerankerModel }]
                  ).map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <p className="mt-2 text-xs text-muted-foreground">
                  Cross-encoders run on the server rather than through
                  OpenRouter, so this list is fixed.
                </p>
              </div>

              <div>
                <label htmlFor="judge-model" className="mb-1.5 block text-sm">
                  Evaluation judge
                </label>
                <input
                  id="judge-model"
                  type="text"
                  value={judgeModel}
                  onChange={(event) => setJudgeModel(event.target.value)}
                  spellCheck={false}
                  className="w-full border border-input bg-background px-3 py-2 font-mono text-xs outline-none focus:border-primary"
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  Any OpenRouter id. Scores faithfulness, answer relevance and
                  answer coverage — three of the nine metrics come from this one
                  model.
                </p>
              </div>
            </div>
          )}
        </section>

        {/* --- 7. INGEST-TIME SETTINGS (not changeable here) --- */}
        <section>
          <SectionHeader title="Fixed for this document" />
          <div className="space-y-2">
            <LockedNote>
              <strong>Chunking</strong> ({options.ingest.chunk_strategy},{" "}
              {options.ingest.chunk_size} characters with {options.ingest.overlap}{" "}
              overlap) is applied when the document is indexed. Changing it
              re-chunks the document, which discards every stored chunk — and the
              ground truth attached to it. Re-upload to chunk differently.
            </LockedNote>
            <LockedNote>
              <strong>Embeddings</strong> (
              <span className="font-mono">{options.ingest.embedding_model}</span>)
              define the vector space the index lives in. A query embedded with a
              different model would be scored against unrelated vectors, so this
              is set once at ingest.
            </LockedNote>
          </div>
        </section>
      </div>

      {/* --- FOOTER ACTION --- */}
      <div className="space-y-3 border-t border-border px-5 py-4">
        {variantCount === 0 ? (
          <p className="text-xs text-destructive">
            Pick at least one retrieval method and one model.
          </p>
        ) : overCap ? (
          <p className="text-xs text-destructive">
            {variantCount} variants exceeds the limit of {options.max_variants}.
            Narrow the methods or the models.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            {runState.isRunning
              ? `Running ${runState.completed}/${runState.total} variants…`
              : `${variantCount} variant${variantCount === 1 ? "" : "s"} — ${methods.length} method${
                  methods.length === 1 ? "" : "s"
                } × ${models.length} model${models.length === 1 ? "" : "s"}`}
          </p>
        )}

        {runState.isRunning ? (
          <button
            onClick={onStop}
            className="w-full border border-destructive px-4 py-2.5 text-sm font-medium text-destructive transition-colors hover:bg-destructive hover:text-destructive-foreground"
          >
            Stop analysis
          </button>
        ) : (
          <button
            onClick={() => onAnalyze(config)}
            disabled={!canRun}
            className={cn(
              "w-full border px-4 py-2.5 text-sm font-medium transition-colors",
              canRun
                ? "border-primary bg-primary text-primary-foreground hover:bg-primary-hover"
                : "cursor-not-allowed border-border text-muted-foreground"
            )}
          >
            Run deep analysis
          </button>
        )}
      </div>
    </aside>
  );
};

export default DeepSidebar;
