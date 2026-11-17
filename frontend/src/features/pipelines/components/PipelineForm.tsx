import React, { useId, useState } from "react";
import { buttonOutline, buttonPrimary, focusRing, inputSmall } from "../../../components/ui/classes";
import { FIELD_LABELS, inactiveKeys, usesReranker, validateConfig, withStrategy, type ConfigErrors } from "../lib/pipelineConfig";
import type { PipelineConfig, PipelineConfigKey, PipelineOptions } from "../types";

interface PipelineFormProps {
  options: PipelineOptions;
  initialName: string;
  initialConfig: PipelineConfig;
  submitLabel: string;
  busy: boolean;
  /** Server-side field errors (`config.<key>` or `name`), shown under their fields. */
  serverErrors?: Record<string, string[]> | null;
  onSubmit: (name: string, config: PipelineConfig) => void;
  onCancel: () => void;
}

function Field({ id, label, error, hint, children }: { id: string; label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] items-start gap-2 py-1">
      <label htmlFor={id} className="pt-1 text-muted-foreground">
        {label}
      </label>
      <div className="min-w-0">
        {children}
        {hint && !error && <p className="mt-0.5 text-[11px] text-muted-foreground">{hint}</p>}
        {error && (
          <p id={`${id}-error`} className="mt-0.5 text-[11px] text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

function asNumber(value: string): number {
  return value.trim() === "" ? Number.NaN : Number(value);
}

/**
 * Create or edit a pipeline (PRD §17 layout: embedding, retrieval, hybrid
 * weight or RRF k, candidate top-k, reranker, final top-k, generator,
 * temperature). Validates against the server's ranges and choices before it
 * submits; settings the chosen strategy does not use are hidden.
 */
const PipelineForm: React.FC<PipelineFormProps> = ({ options, initialName, initialConfig, submitLabel, busy, serverErrors, onSubmit, onCancel }) => {
  const [name, setName] = useState(initialName);
  const [config, setConfig] = useState<PipelineConfig>(initialConfig);
  const [touched, setTouched] = useState(false);
  const formId = `pipeline-form-${useId().replace(/:/g, "")}`;
  const errors: ConfigErrors = validateConfig(config, options);
  const nameError = name.trim() ? (name.trim().length > 120 ? "At most 120 characters." : undefined) : "Give the pipeline a name.";
  const hidden = inactiveKeys(config);
  const shown = (key: PipelineConfigKey) => !hidden.has(key);
  const errorFor = (key: PipelineConfigKey) => (touched ? errors[key] : undefined) ?? serverErrors?.[`config.${key}`]?.[0];
  const set = <K extends PipelineConfigKey>(key: K, value: PipelineConfig[K]) => setConfig((current) => ({ ...current, [key]: value }));
  const id = (key: string) => `${formId}-${key}`;
  const invalid = Object.keys(errors).length > 0 || nameError != null;
  const provider = options.reranker_providers.find((item) => item.id === config.reranker?.provider) ?? null;
  const described = (key: PipelineConfigKey) => (errorFor(key) ? { "aria-invalid": true, "aria-describedby": `${id(key)}-error` } : {});

  return (
    <form
      noValidate
      className="text-xs"
      onSubmit={(event) => {
        event.preventDefault();
        setTouched(true);
        if (!invalid) onSubmit(name.trim(), config);
      }}
    >
      <Field id={id("name")} label="Name" error={touched ? nameError : serverErrors?.name?.[0]}>
        <input id={id("name")} className={`${inputSmall} w-full`} value={name} maxLength={120} onChange={(event) => setName(event.target.value)} />
      </Field>
      <Field id={id("embedding_model")} label={FIELD_LABELS.embedding_model} error={errorFor("embedding_model")} hint="Fixed: indexes are built with this model at ingest time.">
        <input id={id("embedding_model")} className={`${inputSmall} w-full font-mono`} value={config.embedding_model} readOnly />
      </Field>
      <Field id={id("strategy")} label={FIELD_LABELS.strategy} error={errorFor("strategy")} hint={options.strategies.find((item) => item.id === config.strategy)?.description}>
        <select id={id("strategy")} className={`${inputSmall} w-full`} value={config.strategy} onChange={(event) => setConfig((current) => withStrategy(current, event.target.value, options.default_reranker))}>
          {options.strategies.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </Field>
      {shown("fusion") && (
        <Field id={id("fusion")} label={FIELD_LABELS.fusion} error={errorFor("fusion")} hint={options.fusion_methods.find((item) => item.id === config.fusion)?.description}>
          <select id={id("fusion")} className={`${inputSmall} w-full`} value={config.fusion} onChange={(event) => set("fusion", event.target.value)}>
            {options.fusion_methods.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </Field>
      )}
      {shown("hybrid_weight") && (
        <Field id={id("hybrid_weight")} label={FIELD_LABELS.hybrid_weight} error={errorFor("hybrid_weight")} hint="Dense share; 1 is dense only, 0 is BM25 only.">
          <input
            id={id("hybrid_weight")}
            type="number"
            inputMode="decimal"
            step={0.05}
            min={options.ranges.hybrid_weight.min}
            max={options.ranges.hybrid_weight.max}
            className={`${inputSmall} w-24 font-mono`}
            value={Number.isNaN(config.hybrid_weight) ? "" : config.hybrid_weight}
            onChange={(event) => set("hybrid_weight", asNumber(event.target.value))}
            {...described("hybrid_weight")}
          />
        </Field>
      )}
      {shown("rrf_k") && (
        <Field id={id("rrf_k")} label={FIELD_LABELS.rrf_k} error={errorFor("rrf_k")} hint="Larger k flattens the advantage of the top ranks.">
          <input
            id={id("rrf_k")}
            type="number"
            inputMode="numeric"
            min={options.ranges.rrf_k.min}
            max={options.ranges.rrf_k.max}
            className={`${inputSmall} w-24 font-mono`}
            value={Number.isNaN(config.rrf_k) ? "" : config.rrf_k}
            onChange={(event) => set("rrf_k", asNumber(event.target.value))}
            {...described("rrf_k")}
          />
        </Field>
      )}
      <Field id={id("candidate_k")} label={FIELD_LABELS.candidate_k} error={errorFor("candidate_k")} hint={`Passages retrieved (${options.ranges.candidate_k.min}–${options.ranges.candidate_k.max}).`}>
        <input
          id={id("candidate_k")}
          type="number"
          inputMode="numeric"
          min={options.ranges.candidate_k.min}
          max={options.ranges.candidate_k.max}
          className={`${inputSmall} w-24 font-mono`}
          value={Number.isNaN(config.candidate_k) ? "" : config.candidate_k}
          onChange={(event) => set("candidate_k", asNumber(event.target.value))}
          {...described("candidate_k")}
        />
      </Field>
      {usesReranker(config.strategy) && (
        <Field id={id("reranker")} label={FIELD_LABELS.reranker} error={errorFor("reranker")} hint={provider?.description}>
          <div className="flex flex-wrap gap-1.5">
            <select
              id={id("reranker")}
              aria-label="Reranker provider"
              className={`${inputSmall} min-w-0`}
              value={config.reranker?.provider ?? ""}
              onChange={(event) => {
                const next = options.reranker_providers.find((item) => item.id === event.target.value);
                if (next) set("reranker", { provider: next.id, model: next.default_model });
              }}
            >
              {options.reranker_providers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.label}
                </option>
              ))}
            </select>
            {provider?.open ? (
              <>
                <input
                  aria-label="Reranker model"
                  list={id("reranker-models")}
                  className={`${inputSmall} min-w-0 flex-1 font-mono`}
                  value={config.reranker?.model ?? ""}
                  onChange={(event) => set("reranker", { provider: config.reranker?.provider ?? "llm", model: event.target.value.trim() })}
                />
                <datalist id={id("reranker-models")}>
                  {provider.models.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.label}
                    </option>
                  ))}
                </datalist>
              </>
            ) : (
              <select
                aria-label="Reranker model"
                className={`${inputSmall} min-w-0 flex-1`}
                value={config.reranker?.model ?? ""}
                onChange={(event) => set("reranker", { provider: config.reranker?.provider ?? "ollama", model: event.target.value })}
              >
                {(provider?.models ?? []).map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.label}
                  </option>
                ))}
              </select>
            )}
          </div>
        </Field>
      )}
      <Field id={id("top_k")} label={FIELD_LABELS.top_k} error={errorFor("top_k")} hint="Passages given to the model as numbered sources.">
        <input
          id={id("top_k")}
          type="number"
          inputMode="numeric"
          min={options.ranges.top_k.min}
          max={options.ranges.top_k.max}
          className={`${inputSmall} w-24 font-mono`}
          value={Number.isNaN(config.top_k) ? "" : config.top_k}
          onChange={(event) => set("top_k", asNumber(event.target.value))}
          {...described("top_k")}
        />
      </Field>
      <Field id={id("generation_model")} label={FIELD_LABELS.generation_model} error={errorFor("generation_model")} hint="Any OpenRouter model id.">
        <input
          id={id("generation_model")}
          list={id("generation-models")}
          className={`${inputSmall} w-full font-mono`}
          value={config.generation_model}
          onChange={(event) => set("generation_model", event.target.value.trim())}
          {...described("generation_model")}
        />
        <datalist id={id("generation-models")}>
          {options.generation_models.map((model) => (
            <option key={model.id} value={model.id}>
              {model.label}
            </option>
          ))}
        </datalist>
      </Field>
      <Field id={id("temperature")} label={FIELD_LABELS.temperature} error={errorFor("temperature")}>
        <input
          id={id("temperature")}
          type="number"
          inputMode="decimal"
          step={0.1}
          min={options.ranges.temperature.min}
          max={options.ranges.temperature.max}
          className={`${inputSmall} w-24 font-mono`}
          value={Number.isNaN(config.temperature) ? "" : config.temperature}
          onChange={(event) => set("temperature", asNumber(event.target.value))}
          {...described("temperature")}
        />
      </Field>
      <Field id={id("prompt_version")} label={FIELD_LABELS.prompt_version}>
        <input id={id("prompt_version")} className={`${inputSmall} w-full font-mono`} value={config.prompt_version} readOnly />
      </Field>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="submit" className={`${buttonPrimary} px-2.5 py-1 text-xs`} disabled={busy || (touched && invalid)}>
          {busy ? "Saving…" : submitLabel}
        </button>
        <button type="button" className={`${buttonOutline} px-2.5 py-1 text-xs ${focusRing}`} onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </form>
  );
};

export default PipelineForm;
