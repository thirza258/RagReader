/**
 * Client-side checks that mirror the backend's upload rules (PRD §39), so a
 * file the server would refuse is rejected before it is sent. The server is
 * still the authority: it checks content, not names, and refuses private
 * network URLs only after resolving them.
 */

export const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".text", ".md", ".markdown"] as const;

/** For `<input type="file" accept>`. */
export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.join(",");

/** `RAG_MAX_UPLOAD_BYTES` default: 25 MB. */
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

/** `RAG_MAX_TEXT_CHARS` default. */
export const MAX_TEXT_CHARS = 2_000_000;

export const ACCEPTED_TYPES_LABEL = "PDF, DOCX, TXT or Markdown";

export interface FileLike {
  name: string;
  size: number;
}

export interface ValidationProblem {
  code: string;
  message: string;
}

export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 && !name.startsWith(".") ? "" : name.slice(dot).toLowerCase();
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function validateUploadFile(file: FileLike): ValidationProblem | null {
  const extension = fileExtension(file.name);
  if (!(ACCEPTED_EXTENSIONS as readonly string[]).includes(extension)) {
    return {
      code: "unsupported_file_type",
      message: `“${file.name}” is not a supported file. Upload a ${ACCEPTED_TYPES_LABEL} file.`,
    };
  }
  if (file.size === 0) {
    return { code: "empty_file", message: `“${file.name}” is empty.` };
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    return {
      code: "file_too_large",
      message: `“${file.name}” is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_UPLOAD_BYTES)}.`,
    };
  }
  return null;
}

const ALLOWED_PORTS = new Set(["", "80", "443", "8080", "8443"]);

function isPrivateIPv4(host: string): boolean {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  if (!match) return false;
  const [a, b] = [Number(match[1]), Number(match[2])];
  return (
    a === 0 ||
    a === 10 ||
    a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && b === 168) ||
    a >= 224
  );
}

function isNonGlobalIPv6(host: string): boolean {
  if (!host.startsWith("[")) return false;
  const address = host.slice(1, -1).toLowerCase();
  return (
    address === "::" ||
    address === "::1" ||
    address.startsWith("fc") ||
    address.startsWith("fd") ||
    address.startsWith("fe8") ||
    address.startsWith("fe9") ||
    address.startsWith("fea") ||
    address.startsWith("feb") ||
    address.startsWith("ff") ||
    address.startsWith("::ffff:")
  );
}

/** Returns the normalised URL, or the reason it cannot be added. */
export function validateSourceUrl(raw: string): { url: string } | { problem: ValidationProblem } {
  const value = raw.trim();
  if (!value) return { problem: { code: "invalid_request", message: "Enter a web page URL." } };
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return { problem: { code: "invalid_request", message: "Enter a full URL, starting with https://." } };
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { problem: { code: "url_not_allowed", message: "Only http and https URLs can be added." } };
  }
  if (parsed.username || parsed.password) {
    return { problem: { code: "url_not_allowed", message: "URLs with a user name or password cannot be added." } };
  }
  const host = parsed.hostname.toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || isPrivateIPv4(host) || isNonGlobalIPv6(host)) {
    return { problem: { code: "url_not_allowed", message: "Local and private network addresses cannot be added." } };
  }
  if (!ALLOWED_PORTS.has(parsed.port)) {
    return { problem: { code: "url_not_allowed", message: "Only the standard web ports (80, 443, 8080, 8443) are allowed." } };
  }
  return { url: parsed.toString() };
}

export function validatePastedText(text: string): ValidationProblem | null {
  if (!text.trim()) return { code: "invalid_request", message: "Paste some text first." };
  if (text.length > MAX_TEXT_CHARS) {
    return {
      code: "text_too_long",
      message: `The text is ${text.length.toLocaleString("en-US")} characters; the limit is ${MAX_TEXT_CHARS.toLocaleString("en-US")}.`,
    };
  }
  return null;
}
