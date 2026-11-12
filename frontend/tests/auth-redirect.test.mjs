import assert from "node:assert/strict";
import { test } from "node:test";
import { loginPathFor, sanitizeNextPath } from "../src/features/auth/lib/redirect.ts";
import { isProtectedApiPath } from "../src/features/auth/lib/unauthorized.ts";

test("same-site paths are followed as given", () => {
  assert.equal(sanitizeNextPath("/"), "/");
  assert.equal(sanitizeNextPath("/workspace/3/c/9?document=12"), "/workspace/3/c/9?document=12");
  assert.equal(sanitizeNextPath("/docs#walkthrough"), "/docs#walkthrough");
});

test("anything that could leave the site is refused", () => {
  for (const next of [
    null,
    undefined,
    "",
    "workspace",
    "https://evil.example/",
    "//evil.example/",
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "javascript:alert(1)",
    " /workspace",
  ]) {
    assert.equal(sanitizeNextPath(next), null, JSON.stringify(next));
  }
});

test("the login path carries the current page as an encoded next", () => {
  assert.equal(loginPathFor("/workspace/3?document=12"), "/login?next=%2Fworkspace%2F3%3Fdocument%3D12");
  assert.equal(loginPathFor("/login?next=%2F"), "/login");
  assert.equal(loginPathFor("//evil.example"), "/login");
});

test("every legacy and deep-analysis path counts as token-protected", () => {
  for (const path of [
    "/insert-data/", "/insert-text/", "/insert-url/", "/open-chat/", "/job-status/0b1/", "/query/",
    "/start-analysis/", "/analysis-status/0b1/", "/api/v1/analysis-status/0b1/?conversation_id=3",
    "/document/alex/", "/conversation-history/alex/", "/conversation/12/", "/chunk/", "/chunk/4/",
    "/ground-truth-chunk/", "/ground-truth-chunk/pool/", "/ground-truth-chunk/9/",
    "/ground-truth-response/", "/ground-truth-response/9/", "/evaluate/ground-truth-chunk/",
    "/evaluate/ground-truth-response/", "/workspaces/", "/documents/3/text/",
    "https://rag.example/api/v1/conversation/12/",
  ]) {
    assert.equal(isProtectedApiPath(path), true, path);
  }
});

test("sign-in, sign-up, sign-out and analysis-config never trigger the sign-in redirect", () => {
  for (const path of [
    "/sign-in/", "/sign-up/", "/sign-out/", "/api/v1/sign-in/", "/analysis-config/",
    "/analysis-config/?refresh=1", "/documentation/", "/conversationsx/", "/queryx/", "", null, undefined,
  ]) {
    assert.equal(isProtectedApiPath(path), false, String(path));
  }
});
