import type { PipelineConfig, PipelineConfigKey, PipelineOptions, PipelineVersion, PipelineVersionLabel, RerankerSpec } from "../types/index.ts";

/**
 * Pipeline configuration logic (PRD §17–19), pure so the form, the version
 * history and the chat header agree and tests can pin them: which settings a
 * strategy uses, client-side validation mirroring the server's, the PATCH
 * body for an edit, and readable diffs between versions.
 */

/** The shape of an OpenRouter id, as `common.constant.MODEL_ID_RE` on the server. */
export const MODEL_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._:-]*$/;
export const MODEL_ID_MAX_LENGTH = 128;

export const CONFIG_KEYS: PipelineConfigKey[] = [
  "strategy",
  "fusion",
  "hybrid_weight",
  "rrf_k",
  "candidate_k",
  "top_k",
  "reranker",
  "generation_model",
  "temperature",
  "prompt_version",
  "embedding_model",
];

export const FIELD_LABELS: Record<PipelineConfigKey, string> = {
  strategy: "Retrieval",
  fusion: "Fusion",
  hybrid_weight: "Hybrid weight",
  rrf_k: "RRF k",
  candidate_k: "Candidate top-k",
  top_k: "Final top-k",
  reranker: "Reranker",
  generation_model: "Generator",
  temperature: "Temperature",
  prompt_version: "Prompt version",
  embedding_model: "Embedding",
};

const STRATEGY_LABELS: Record<string, string> = {
  dense: "Dense",
  bm25: "BM25",
  hybrid: "Hybrid (dense + BM25)",
  hybrid_rerank: "Hybrid + reranking",
};

const FUSION_LABELS: Record<string, string> = { weighted: "Weighted scores", rrf: "Reciprocal rank fusion" };

export function strategyLabel(strategy: string | null | undefined): string {
  if (!strategy) return "—";
  return STRATEGY_LABELS[strategy] ?? strategy;
}

export function usesFusion(strategy: string | null | undefined): boolean {
  return strategy === "hybrid" || strategy === "hybrid_rerank";
}

export function usesReranker(strategy: string | null | undefined): boolean {
  return strategy === "hybrid_rerank";
}

export function usesDense(strategy: string | null | undefined): boolean {
  return strategy === "dense" || usesFusion(strategy);
}

/** Settings that do nothing for this configuration (hidden in the form, dimmed in summaries). */
export function inactiveKeys(config: Pick<PipelineConfig, "strategy" | "fusion">): Set<PipelineConfigKey> {
  const inactive = new Set<PipelineConfigKey>();
  if (!usesFusion(config.strategy)) {
    inactive.add("fusion");
    inactive.add("hybrid_weight");
    inactive.add("rrf_k");
  } else if (config.fusion === "rrf") {
    inactive.add("hybrid_weight");
  } else {
    inactive.add("rrf_k");
  }
  if (!usesReranker(config.strategy)) inactive.add("reranker");
  return inactive;
}

/** A strategy change: the reranker exists exactly when the strategy uses one. */
export function withStrategy(config: PipelineConfig, strategy: string, defaultReranker: RerankerSpec): PipelineConfig {
  if (usesReranker(strategy)) return { ...config, strategy, reranker: config.reranker ?? { ...defaultReranker } };
  return { ...config, strategy, reranker: null };
}

function isInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function isValidModelId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= MODEL_ID_MAX_LENGTH && MODEL_ID_RE.test(value);
}

export type ConfigErrors = Partial<Record<PipelineConfigKey, string>>;

/** Field errors for `config`, using the ranges and choices of `options` (the server checks the same). */
export function validateConfig(config: PipelineConfig, options: Pick<PipelineOptions, "strategies" | "fusion_methods" | "reranker_providers" | "ranges" | "embedding_models" | "prompt_versions">): ConfigErrors {
  const errors: ConfigErrors = {};
  const { ranges } = options;
  const inRange = (key: "candidate_k" | "top_k" | "rrf_k" | "hybrid_weight" | "temperature", integer: boolean) => {
    const value = config[key];
    const range = ranges[key];
    if (integer ? !isInteger(value) : !isFiniteNumber(value)) {
      errors[key] = integer ? "Enter a whole number." : "Enter a number.";
    } else if (value < range.min || value > range.max) {
      errors[key] = `Must be between ${range.min} and ${range.max}.`;
    }
  };

  if (!options.strategies.some((item) => item.id === config.strategy)) errors.strategy = "Choose a retrieval strategy.";
  inRange("candidate_k", true);
  inRange("top_k", true);
  if (!errors.candidate_k && !errors.top_k && config.top_k > config.candidate_k) errors.top_k = "Cannot be larger than the candidate top-k.";
  if (usesFusion(config.strategy)) {
    if (!options.fusion_methods.some((item) => item.id === config.fusion)) errors.fusion = "Choose a fusion method.";
    if (config.fusion === "rrf") inRange("rrf_k", true);
    else inRange("hybrid_weight", false);
  }
  if (usesReranker(config.strategy)) {
    const reranker = config.reranker;
    const provider = options.reranker_providers.find((item) => item.id === reranker?.provider);
    if (!reranker || !provider) errors.reranker = "Choose a reranker.";
    else if (provider.open ? !isValidModelId(reranker.model) : !provider.models.some((model) => model.id === reranker.model)) {
      errors.reranker = provider.open ? "Use an OpenRouter model id such as openai/gpt-4o-mini." : "Choose one of the listed models.";
    }
  } else if (config.reranker != null) {
    errors.reranker = "Only hybrid + reranking uses a reranker.";
  }
  if (!isValidModelId(config.generation_model)) errors.generation_model = "Use an OpenRouter model id such as openai/gpt-4o-mini.";
  inRange("temperature", false);
  if (!options.embedding_models.includes(config.embedding_model)) {
    errors.embedding_model = `Documents are indexed with ${options.embedding_models.join(", ") || "another model"}.`;
  }
  if (!options.prompt_versions.includes(config.prompt_version)) errors.prompt_version = "Choose a prompt version.";
  return errors;
}

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}

/** The settings of `next` that differ from `base`: the PATCH body of an edit. */
export function configChanges(base: PipelineConfig, next: PipelineConfig): Partial<PipelineConfig> {
  const changes: Partial<PipelineConfig> = {};
  for (const key of CONFIG_KEYS) {
    if (!sameValue(base[key], next[key])) (changes as Record<string, unknown>)[key] = next[key];
  }
  return changes;
}

/** A setting as people read it: "Hybrid (dense + BM25)", "0.6", "ollama · nomic-embed-text", "none". */
export function formatConfigValue(key: PipelineConfigKey, value: unknown): string {
  if (value == null) return key === "reranker" ? "none" : "—";
  if (key === "strategy") return strategyLabel(String(value));
  if (key === "fusion") return FUSION_LABELS[String(value)] ?? String(value);
  if (key === "reranker") {
    const spec = value as RerankerSpec;
    return `${spec.provider} · ${spec.model}`;
  }
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Math.round(value * 10000) / 10000);
  return String(value);
}

export interface ConfigChange {
  key: PipelineConfigKey;
  label: string;
  from: string;
  to: string;
}

/** What changed from `before` to `after`, in configuration order. */
export function diffConfigs(before: PipelineConfig | null | undefined, after: PipelineConfig): ConfigChange[] {
  if (!before) return [];
  return CONFIG_KEYS.filter((key) => !sameValue(before[key], after[key])).map((key) => ({
    key,
    label: FIELD_LABELS[key],
    from: formatConfigValue(key, before[key]),
    to: formatConfigValue(key, after[key]),
  }));
}

export interface VersionHistoryEntry {
  version: PipelineVersion;
  /** Against the previous version; empty for version 1. */
  changes: ConfigChange[];
  initial: boolean;
}

/** Newest first, each version with its changes from the one before it. */
export function versionHistory(versions: readonly PipelineVersion[]): VersionHistoryEntry[] {
  const ascending = [...versions].sort((a, b) => a.number - b.number);
  return ascending
    .map((version, index) => ({
      version,
      changes: index === 0 ? [] : diffConfigs(ascending[index - 1].config, version.config),
      initial: index === 0,
    }))
    .reverse();
}

/** One line: "Hybrid (dense + BM25) · weighted 0.6 · 20 → 5 · reranker ollama · nomic-embed-text · openai/gpt-4o-mini, temperature 0.2". */
export function describeConfig(config: PipelineConfig | null | undefined): string {
  if (!config) return "—";
  const parts = [strategyLabel(config.strategy)];
  if (usesFusion(config.strategy)) {
    parts.push(config.fusion === "rrf" ? `RRF k ${config.rrf_k}` : `weighted ${formatConfigValue("hybrid_weight", config.hybrid_weight)}`);
  }
  parts.push(`${config.candidate_k} → ${config.top_k}`);
  if (usesReranker(config.strategy) && config.reranker) parts.push(`reranker ${formatConfigValue("reranker", config.reranker)}`);
  parts.push(`${config.generation_model}, temperature ${formatConfigValue("temperature", config.temperature)}`);
  return parts.join(" · ");
}

/** "Default (dense) v2"; null when nothing is known. */
export function pipelineVersionLabel(label: PipelineVersionLabel | null | undefined): string | null {
  if (!label || !label.name) return null;
  const number = label.number ?? label.version;
  return number != null ? `${label.name} v${number}` : label.name;
}
