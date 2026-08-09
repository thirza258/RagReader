import React, { useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowLeft,
  Cpu,
  Database,
  FileText,
  Info,
  Layers,
  Loader2,
  Lock,
  Play,
  Square,
} from "lucide-react";
import service from "../services/service";
import {
  AnalysisConfigOptions,
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
// with an empty selection.
const FALLBACK_OPTIONS: AnalysisConfigOptions = {
  retrieval_methods: [
    { id: "Dense Retrieval", label: "Dense" },
    { id: "Sparse Retrieval", label: "Sparse" },
    { id: "Hybrid Retrieval", label: "Hybrid" },
  ],
  models: [],
  ground_truth_modes: [
    { id: "manual", label: "Manual selection" },
    { id: "pooled", label: "Candidate pooling (RRF)" },
  ],
  top_k: { min: 1, max: 20, default: 5 },
  pool_top_n: { min: 1, max: 50, default: 10 },
  defaults: {
    methods: ["Dense Retrieval", "Sparse Retrieval", "Hybrid Retrieval"],
    models: [],
    top_k: 5,
    ground_truth_mode: "manual",
    pool_top_n: 10,
  },
  max_variants: 9,
};

const SectionHeader: React.FC<{ icon: React.ReactNode; title: string }> = ({
  icon,
  title,
}) => (
  <div className="flex items-center gap-2 mb-3 text-[hsl(var(--primary))]">
    {icon}
    <h3 className="text-xs font-bold uppercase tracking-wider">{title}</h3>
  </div>
);

/** A control that exists in the UI but cannot be changed here, plus why. */
const LockedNote: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div className="flex items-start gap-2 rounded-md border border-dashed border-[hsl(var(--border))] bg-[hsl(var(--muted))]/40 p-3 text-xs text-[hsl(var(--muted-foreground))]">
    <Lock size={13} className="mt-0.5 shrink-0" />
    <span>{children}</span>
  </div>
);

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

  // The option set is served rather than hardcoded — the model IDs here must
  // match the ones the backend can actually instantiate.
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
  const canRun = Boolean(conversationId) && variantCount > 0 && !runState.isRunning;

  const config: DeepAnalysisConfig = useMemo(
    () => ({
      methods,
      models,
      top_k: topK,
      ground_truth_mode: groundTruthMode,
      pool_top_n: poolTopN,
    }),
    [methods, models, topK, groundTruthMode, poolTopN]
  );

  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + ["B", "KB", "MB", "GB"][i];
  };

  return (
    <div className="w-1/3 min-w-[320px] max-w-[400px] h-full flex flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--card-foreground))] shadow-2xl z-20">
      {/* --- HEADER --- */}
      <div className="p-4 border-b border-[hsl(var(--border))] flex items-center gap-3">
        <button
          onClick={onBack}
          className="p-2 rounded-md hover:bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-[hsl(var(--foreground))]">
            Deep Analysis
          </h2>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Configuration &amp; Pipeline
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-8">
        {/* --- 1. TARGET METADATA --- */}
        <section>
          <SectionHeader icon={<FileText size={16} />} title="Target Context" />
          {file ? (
            <div className="p-4 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] shadow-sm">
              <div className="flex justify-between items-start mb-2">
                <span className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-[10px] px-2 py-0.5 rounded font-bold">
                  ACTIVE FILE
                </span>
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {formatSize(file.size)}
                </span>
              </div>
              <p className="text-sm font-medium truncate mb-1" title={file.name}>
                {file.name}
              </p>
              <p className="text-xs text-[hsl(var(--muted-foreground))] uppercase">
                {file.type || "Unknown Type"}
              </p>
            </div>
          ) : (
            <div className="p-4 rounded-lg bg-[hsl(var(--muted))] border border-dashed border-[hsl(var(--border))] text-center">
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                {conversationId ? `Conversation #${conversationId}` : "No conversation loaded"}
              </p>
              {documentId && (
                <p className="mt-1 text-xs text-[hsl(var(--muted-foreground))]">
                  Document #{documentId}
                </p>
              )}
            </div>
          )}
        </section>

        {/* --- 2. RETRIEVAL METHOD --- */}
        <section>
          <SectionHeader icon={<Database size={16} />} title="Retrieval Pipeline" />
          <div className="space-y-2">
            {options.retrieval_methods.map((option) => (
              <label
                key={option.id}
                title={option.description}
                className="flex items-center justify-between p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--muted))] cursor-pointer transition-colors group"
              >
                <span className="text-sm font-medium text-[hsl(var(--foreground))] group-hover:text-[hsl(var(--primary))] transition-colors">
                  {option.label}
                </span>
                <input
                  type="checkbox"
                  checked={methods.includes(option.id)}
                  onChange={() => setMethods((prev) => toggle(prev, option.id))}
                  className="w-4 h-4 rounded border-gray-300 text-[hsl(var(--primary))] focus:ring-[hsl(var(--ring))] accent-[hsl(var(--primary))]"
                />
              </label>
            ))}
          </div>
        </section>

        {/* --- 3. MODEL CONSENSUS --- */}
        <section>
          <SectionHeader icon={<Cpu size={16} />} title="Model Consensus" />
          {isLoadingOptions ? (
            <div className="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
              <Loader2 size={14} className="animate-spin" /> Loading models…
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-2">
              {options.models.map((model) => (
                <label
                  key={model.id}
                  className={cn(
                    "flex items-center p-3 rounded-md border cursor-pointer transition-all",
                    models.includes(model.id)
                      ? "bg-[hsl(var(--muted))] border-[hsl(var(--primary))] shadow-sm"
                      : "bg-[hsl(var(--background))] border-[hsl(var(--border))]"
                  )}
                >
                  <input
                    type="checkbox"
                    checked={models.includes(model.id)}
                    onChange={() => setModels((prev) => toggle(prev, model.id))}
                    className="w-4 h-4 rounded border-gray-300 text-[hsl(var(--primary))] focus:ring-[hsl(var(--ring))] accent-[hsl(var(--primary))]"
                  />
                  <span className="ml-3">
                    <span
                      className={cn(
                        "block text-sm font-medium",
                        models.includes(model.id)
                          ? "text-[hsl(var(--primary))]"
                          : "text-[hsl(var(--foreground))]"
                      )}
                    >
                      {model.label}
                    </span>
                    <span className="block text-[11px] text-[hsl(var(--muted-foreground))]">
                      {model.provider}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          )}
        </section>

        {/* --- 4. RETRIEVAL DEPTH --- */}
        <section>
          <SectionHeader icon={<Layers size={16} />} title="Retrieval Depth" />
          <div className="flex justify-between mb-2">
            <label className="text-sm font-medium text-[hsl(var(--foreground))]">
              Retrieved Chunks (Top-K)
            </label>
            <span className="text-sm font-bold text-[hsl(var(--primary))]">{topK}</span>
          </div>
          <input
            type="range"
            min={options.top_k.min}
            max={options.top_k.max}
            value={topK}
            onChange={(e) => setTopK(parseInt(e.target.value, 10))}
            className="w-full h-2 bg-[hsl(var(--muted))] rounded-lg appearance-none cursor-pointer accent-[hsl(var(--primary))]"
          />
          <p className="mt-2 text-xs text-[hsl(var(--muted-foreground))]">
            How many chunks each method feeds the model. Also the K in Precision@K and
            Recall@K.
          </p>
        </section>

        {/* --- 5. GROUND TRUTH --- */}
        <section>
          <SectionHeader icon={<Info size={16} />} title="Ground Truth" />
          <div className="space-y-2">
            {options.ground_truth_modes.map((option) => (
              <label
                key={option.id}
                className={cn(
                  "flex items-start gap-3 p-3 rounded-md border cursor-pointer transition-all",
                  groundTruthMode === option.id
                    ? "bg-[hsl(var(--muted))] border-[hsl(var(--primary))] shadow-sm"
                    : "bg-[hsl(var(--background))] border-[hsl(var(--border))]"
                )}
              >
                <input
                  type="radio"
                  name="groundTruthMode"
                  checked={groundTruthMode === option.id}
                  onChange={() => setGroundTruthMode(option.id as GroundTruthMode)}
                  className="mt-1 accent-[hsl(var(--primary))]"
                />
                <span>
                  <span className="block text-sm font-medium text-[hsl(var(--foreground))]">
                    {option.label}
                  </span>
                  {option.description && (
                    <span className="block text-[11px] text-[hsl(var(--muted-foreground))]">
                      {option.description}
                    </span>
                  )}
                </span>
              </label>
            ))}
          </div>

          {groundTruthMode === "pooled" && (
            <div className="mt-3">
              <div className="flex justify-between mb-2">
                <label className="text-sm font-medium text-[hsl(var(--foreground))]">
                  Pool depth
                </label>
                <span className="text-sm font-bold text-[hsl(var(--primary))]">
                  {poolTopN}
                </span>
              </div>
              <input
                type="range"
                min={options.pool_top_n.min}
                max={options.pool_top_n.max}
                value={poolTopN}
                onChange={(e) => setPoolTopN(parseInt(e.target.value, 10))}
                className="w-full h-2 bg-[hsl(var(--muted))] rounded-lg appearance-none cursor-pointer accent-[hsl(var(--primary))]"
              />
              <p className="mt-2 text-xs text-[hsl(var(--muted-foreground))]">
                Running the analysis re-pools and overwrites this conversation's ground
                truth. Keep the pool deeper than Top-K, or the ground truth becomes a
                near-copy of a single run's output.
              </p>
            </div>
          )}
        </section>

        {/* --- 6. INGEST-TIME SETTINGS (not changeable here) --- */}
        <section>
          <SectionHeader icon={<Lock size={16} />} title="Fixed For This Document" />
          <div className="space-y-2">
            <LockedNote>
              <strong>Chunking strategy &amp; size</strong> are applied when the document
              is indexed. Changing them re-chunks the document, which discards every
              stored chunk — and the ground truth attached to it. Re-upload to chunk
              differently.
            </LockedNote>
            <LockedNote>
              <strong>Reranker</strong> is what makes Hybrid distinct from Dense + Sparse.
              Turning it off would make Hybrid the same fusion the candidate pool uses, so
              a run would be scored against its own algorithm.
            </LockedNote>
          </div>
        </section>
      </div>

      {/* --- FOOTER ACTION --- */}
      <div className="p-4 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))] space-y-3">
        {variantCount === 0 ? (
          <p className="flex items-center gap-2 text-xs text-[hsl(var(--destructive))]">
            <AlertCircle size={14} />
            Pick at least one retrieval method and one model.
          </p>
        ) : (
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
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
            className="w-full flex items-center justify-center gap-2 bg-red-500 hover:bg-red-600 text-white py-3 px-4 rounded-lg font-bold shadow-lg transition-all active:scale-95"
          >
            <Square size={16} fill="currentColor" />
            STOP ANALYSIS
          </button>
        ) : (
          <button
            onClick={() => onAnalyze(config)}
            disabled={!canRun}
            className={cn(
              "w-full flex items-center justify-center gap-2 py-3 px-4 rounded-lg font-bold shadow-lg transition-all",
              canRun
                ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] hover:opacity-90 active:scale-95"
                : "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] cursor-not-allowed"
            )}
          >
            <Play size={18} fill="currentColor" />
            RUN DEEP ANALYSIS
          </button>
        )}
      </div>
    </div>
  );
};

export default DeepSidebar;
