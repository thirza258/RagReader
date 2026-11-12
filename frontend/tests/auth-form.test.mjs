import assert from "node:assert/strict";
import { test } from "node:test";
import {
  PASSWORD_NOT_SET_NOTICE,
  authFeedback,
  carryOver,
  validateAuthForm,
} from "../src/features/auth/lib/authForm.ts";

const EMPTY = { identifier: "", username: "", email: "", password: "", confirm: "" };

test("the form checks required fields and the password confirmation before sending", () => {
  assert.deepEqual(Object.keys(validateAuthForm("signin", EMPTY)).sort(), ["identifier", "password"]);
  assert.deepEqual(validateAuthForm("signin", { ...EMPTY, identifier: "alex", password: "x" }), {});
  assert.deepEqual(Object.keys(validateAuthForm("create", EMPTY)).sort(), ["email", "password", "username"]);
  const mismatch = validateAuthForm("create", { ...EMPTY, username: "alex", email: "a@x.io", password: "one", confirm: "two" });
  assert.deepEqual(Object.keys(mismatch), ["confirm"]);
  assert.deepEqual(validateAuthForm("create", { ...EMPTY, username: "alex", email: "a@x.io", password: "pw", confirm: "pw" }), {});
});

test("password validator messages land under the password field", () => {
  const feedback = authFeedback({
    status: 400, code: "invalid_request", message: "Choose a different password.",
    details: { PASSWORD: ["This password is too short.", "This password is too common."] },
  }, "create");
  assert.deepEqual(feedback.fieldErrors, { password: ["This password is too short.", "This password is too common."] });
  assert.equal(feedback.formError, "");
  assert.equal(feedback.mode, "create");
});

test("sign-in field errors map USERNAME and EMAIL to the one identifier field", () => {
  const feedback = authFeedback({ status: 400, code: "invalid_request", message: "x", details: { USERNAME: ["Enter your username or email."] } }, "signin");
  assert.deepEqual(feedback.fieldErrors, { identifier: ["Enter your username or email."] });
});

test("an invalid_request without field details is shown as a form error", () => {
  const feedback = authFeedback({ status: 400, code: "invalid_request", message: "Bad JSON.", details: null }, "signin");
  assert.equal(feedback.formError, "Bad JSON.");
});

test("an existing account offers to sign in instead", () => {
  const feedback = authFeedback({ status: 409, code: "account_exists", message: "That username or email is already registered." }, "create");
  assert.equal(feedback.formError, "That username or email is already registered.");
  assert.equal(feedback.suggestMode, "signin");
});

test("wrong credentials are one message, whichever part was wrong", () => {
  const feedback = authFeedback({ status: 401, code: "invalid_credentials", message: "The username, email or password is incorrect." }, "signin");
  assert.equal(feedback.formError, "The username, email or password is incorrect.");
  assert.equal(feedback.mode, "signin");
});

test("an account without a password switches to the claim form with an explanation", () => {
  const feedback = authFeedback({ status: 409, code: "password_not_set", message: "…" }, "signin");
  assert.equal(feedback.mode, "create");
  assert.equal(feedback.notice, PASSWORD_NOT_SET_NOTICE);
  assert.equal(feedback.formError, "");
});

test("throttling shows the server's wait, or a fallback", () => {
  assert.equal(authFeedback({ status: 429, code: "rate_limited", message: "Too many attempts. Try again in 42 seconds." }, "signin").formError,
    "Too many attempts. Try again in 42 seconds.");
  assert.match(authFeedback({ status: 429, code: "rate_limited", message: "" }, "create").formError, /Too many attempts/);
  assert.match(authFeedback({ status: 429, code: "request_failed", message: "Request was throttled." }, "create").formError, /Too many attempts/);
});

test("what was typed follows a mode switch", () => {
  assert.equal(carryOver({ ...EMPTY, identifier: "alex" }, "create").username, "alex");
  assert.equal(carryOver({ ...EMPTY, identifier: "alex@example.com" }, "create").email, "alex@example.com");
  assert.equal(carryOver({ ...EMPTY, username: "alex" }, "signin").identifier, "alex");
});
