/**
 * Companion Application: ChattyDesk (Foundation Model Benchmarking Lab & Multi-Model Playground)
 * Overridable with VITE_CHATTYDESK_URL at build/runtime.
 */
export const chattyDeskURL =
  import.meta.env.VITE_CHATTYDESK_URL ||
  (typeof window !== "undefined" && (window as any).CHATTYDESK_URL) ||
  "https://chatty.nevatal.id";
