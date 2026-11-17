import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CLOSE_NOT_FOUND,
  CLOSE_UNAUTHENTICATED,
  authFrame,
  classifySocketClose,
  isBatchNotFoundFrame,
  socketAuthMessage,
} from "../src/services/analysisSocketAuth.ts";

test("the first frame carries the token, never the URL", () => {
  assert.deepEqual(JSON.parse(authFrame("rr_abc")), { type: "auth", token: "rr_abc" });
});

test("authentication closes are never retried", () => {
  assert.equal(classifySocketClose(CLOSE_UNAUTHENTICATED, false), "unauthenticated");
  assert.equal(classifySocketClose(CLOSE_NOT_FOUND, false), "not_found");
  // Even after a completion frame, the auth codes are what the user must act on.
  assert.equal(classifySocketClose(CLOSE_UNAUTHENTICATED, true), "unauthenticated");
});

test("normal and unexpected closes keep their old handling", () => {
  assert.equal(classifySocketClose(1000, false), "finished");
  assert.equal(classifySocketClose(1006, true), "finished");
  assert.equal(classifySocketClose(1006, false), "retry");
  assert.equal(classifySocketClose(4400, false), "retry");
});

test("only the terminal job_not_found frame means the batch is not ours", () => {
  assert.equal(isBatchNotFoundFrame({ status: "ERROR", error_code: "job_not_found", terminal: true }), true);
  assert.equal(isBatchNotFoundFrame({ error_code: "job_not_found", method: "Dense Retrieval" }), false);
  assert.equal(isBatchNotFoundFrame({ error_code: "provider_timeout" }), false);
  assert.equal(isBatchNotFoundFrame(null), false);
});

test("each failure has a sign-in prompt", () => {
  assert.match(socketAuthMessage("unauthenticated"), /Sign in again/);
  assert.match(socketAuthMessage("not_found"), /Sign in with the account/);
});
