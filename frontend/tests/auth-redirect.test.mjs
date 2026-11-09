import assert from "node:assert/strict";
import { test } from "node:test";
import { loginPathFor, sanitizeNextPath } from "../src/features/auth/lib/redirect.ts";

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
