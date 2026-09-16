import type { AnalysisOption, ModuleCompatibility } from "../interface";
import { activeCompatibilityRules } from "../lib/moduleCompatibility";

interface Props {
  compatibility?: ModuleCompatibility;
  modules: AnalysisOption[];
  selectedModules: string[];
  methods: string[];
}

const KIND_LABELS = {
  compatible: "Works together",
  conditional: "Conditional behavior",
  cost: "More work",
  requirement: "Requires embeddings",
};

export default function ModuleCompatibilityPanel({ compatibility, modules, selectedModules, methods }: Props) {
  if (!compatibility) return null;

  const labels = new Map(modules.map((module) => [module.id, module.label]));
  const selected = new Set(selectedModules);
  const stages = compatibility.stages
    .map((stage) => ({ ...stage, modules: stage.modules.filter((id) => selected.has(id)) }))
    .filter((stage) => stage.modules.length > 0);
  const rules = selected.size > 0
    ? activeCompatibilityRules(compatibility.rules, selectedModules, methods)
    : compatibility.rules;

  return (
    <section aria-labelledby="module-compatibility-heading" className="mb-4 border border-border bg-background p-3 text-xs">
      <h4 id="module-compatibility-heading" className="text-sm font-medium">Module compatibility</h4>
      <p className="mt-2 text-muted-foreground">{compatibility.summary}</p>
      {selected.size > 0 && compatibility.all_modules_supported && (
        <p role="status" className="mt-2 font-medium">
          {selected.size} selected · no incompatible pairs
        </p>
      )}

      {stages.length > 0 ? (
        <ol aria-label="Selected module execution order" className="mt-3 space-y-2 border-l-2 border-border pl-3">
          {stages.map((stage, index) => (
            <li key={stage.label}>
              <span className="font-medium">{index + 1}. {stage.label}</span>
              <p className="mt-0.5 text-muted-foreground">
                {stage.modules.map((id) => labels.get(id) ?? id).join(" → ")}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-2 text-muted-foreground">Select modules to see their execution order and interaction notes.</p>
      )}

      {rules.length > 0 && (
        <details className="mt-3 border-t border-border pt-2">
          <summary className="cursor-pointer font-medium">
            {selected.size > 0 ? `Interaction notes for this selection (${rules.length})` : "Combination guide"}
          </summary>
          <ul className="mt-3 space-y-3">
            {rules.map((rule) => (
              <li key={rule.id}>
                <span className="block text-[10px] uppercase tracking-wide text-muted-foreground">{KIND_LABELS[rule.kind]}</span>
                <p className="mt-0.5 font-medium">{rule.title}</p>
                <p className="mt-1 text-muted-foreground">{rule.description}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
