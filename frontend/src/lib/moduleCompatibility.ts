import type { ModuleCompatibilityRule } from "../interface";

export function activeCompatibilityRules(
  rules: ModuleCompatibilityRule[],
  selectedModules: string[],
  methods: string[],
): ModuleCompatibilityRule[] {
  const selected = new Set(selectedModules);
  return rules.filter((rule) =>
    rule.modules.filter((id) => selected.has(id)).length >= rule.min_selected &&
    (!rule.methods || rule.methods.some((method) => methods.includes(method))),
  );
}
