import React, { useState } from "react";
import service from "../services/service";
import { useNavigate, useSearchParams } from "react-router-dom";
import SEO from "../components/SEO";
import { sanitizeNextPath } from "../features/auth/lib/redirect";
import { saveSession } from "../features/auth/lib/session";
import { toApiError } from "../services/api/errors";
import {
  authFeedback,
  carryOver,
  validateAuthForm,
} from "../features/auth/lib/authForm";
import type { AuthField, AuthMode, AuthValues, FieldErrors } from "../features/auth/lib/authForm";

const EMPTY: AuthValues = { identifier: "", username: "", email: "", password: "", confirm: "" };

const COPY: Record<AuthMode, { title: string; lead: string; submit: string; busy: string }> = {
  signin: {
    title: "Sign in",
    lead: "Use your username or email and your password.",
    submit: "Sign in",
    busy: "Signing in…",
  },
  create: {
    title: "Create account",
    lead: "Choose a username and a password. Created your account before passwords existed? Enter its exact username and email here to set one.",
    submit: "Create account",
    busy: "Creating account…",
  },
};

const field =
  "w-full border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus:border-primary aria-[invalid=true]:border-destructive";

interface FieldProps {
  id: AuthField;
  label: string;
  type: string;
  value: string;
  autoComplete: string;
  placeholder?: string;
  errors?: string[];
  onChange: (value: string) => void;
}

const Field: React.FC<FieldProps> = ({ id, label, type, value, autoComplete, placeholder, errors, onChange }) => (
  <div>
    <label className="mb-1.5 block text-sm font-medium" htmlFor={id}>
      {label}
    </label>
    <input
      id={id}
      name={id}
      type={type}
      className={field}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      autoComplete={autoComplete}
      placeholder={placeholder}
      aria-invalid={errors?.length ? true : undefined}
      aria-describedby={errors?.length ? `${id}-errors` : undefined}
    />
    {errors?.length ? (
      <ul id={`${id}-errors`} className="mt-1.5 space-y-0.5 text-sm text-destructive">
        {errors.map((message) => (
          <li key={message}>{message}</li>
        ))}
      </ul>
    ) : null}
  </div>
);

const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  // Only a path on this site is followed; anything else falls back to home.
  const next = sanitizeNextPath(searchParams.get("next"));

  const [mode, setMode] = useState<AuthMode>(() => (searchParams.get("mode") === "create" ? "create" : "signin"));
  const [values, setValues] = useState<AuthValues>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState("");
  const [notice, setNotice] = useState("");
  const [suggestMode, setSuggestMode] = useState<AuthMode | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const set = (key: keyof AuthValues) => (value: string) => {
    setValues((previous) => ({ ...previous, [key]: value }));
    setFieldErrors((previous) => ({ ...previous, [key]: undefined }));
  };

  const switchMode = (to: AuthMode, keepNotice = "") => {
    setMode(to);
    setValues((previous) => ({ ...carryOver(previous, to), password: "", confirm: "" }));
    setFieldErrors({});
    setFormError("");
    setSuggestMode(null);
    setNotice(keepNotice);
  };

  const finish = (session: { username?: string; email?: string; token?: string | null }) => {
    if (!session.token) {
      setFormError("The server did not issue an access token. Try again later.");
      return;
    }
    saveSession(session);
    navigate(next ?? "/", { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const problems = validateAuthForm(mode, values);
    setFormError("");
    setSuggestMode(null);
    if (Object.keys(problems).length) {
      setFieldErrors(problems);
      return;
    }
    setFieldErrors({});
    setSubmitting(true);
    try {
      if (mode === "signin") {
        finish(await service.signIn(values.identifier.trim(), values.password));
      } else {
        const body = await service.signUp(values.email.trim(), values.username.trim(), values.password);
        finish(body?.data ?? {});
      }
    } catch (error) {
      const feedback = authFeedback(toApiError(error, "Could not reach the server. Try again."), mode);
      if (feedback.mode !== mode) switchMode(feedback.mode, feedback.notice);
      else setNotice(feedback.notice);
      setFieldErrors(feedback.fieldErrors);
      setFormError(feedback.formError);
      setSuggestMode(feedback.suggestMode);
    } finally {
      setSubmitting(false);
    }
  };

  const copy = COPY[mode];
  const tab = (to: AuthMode, label: string) => (
    <button
      type="button"
      onClick={() => mode !== to && switchMode(to)}
      aria-pressed={mode === to}
      className={`flex-1 border-b-2 px-3 py-2 text-sm transition-colors ${
        mode === to ? "border-primary font-medium text-foreground" : "border-transparent text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <SEO
        title={`${copy.title} — RAGReader`}
        description="Sign in or create an account to benchmark RAG retrieval pipelines."
        canonicalUrl="https://rag.nevatal.id/login"
      />

      <form className="w-full max-w-sm border border-border p-8" onSubmit={handleSubmit} noValidate>
        <div className="mb-6 flex">
          {tab("signin", "Sign in")}
          {tab("create", "Create account")}
        </div>

        <h1 className="font-serif text-2xl font-semibold">{copy.title}</h1>
        <p className="mt-1 text-sm text-muted-foreground">{copy.lead}</p>
        {next && next !== "/" && (
          <p className="mt-3 border-l-2 border-primary/50 pl-3 text-sm">
            Sign in to continue where you were.
          </p>
        )}
        {notice && (
          <p role="status" className="mt-4 border border-border bg-accent/40 p-3 text-sm">
            {notice}
          </p>
        )}

        <div className="mt-8 space-y-5">
          {mode === "signin" ? (
            <>
              <Field id="identifier" label="Username or email" type="text" value={values.identifier}
                autoComplete="username" placeholder="alex or alex@example.com"
                errors={fieldErrors.identifier} onChange={set("identifier")} />
              <Field id="password" label="Password" type="password" value={values.password}
                autoComplete="current-password" errors={fieldErrors.password} onChange={set("password")} />
            </>
          ) : (
            <>
              <Field id="username" label="Username" type="text" value={values.username}
                autoComplete="username" placeholder="e.g. alex"
                errors={fieldErrors.username} onChange={set("username")} />
              <Field id="email" label="Email" type="email" value={values.email}
                autoComplete="email" placeholder="alex@example.com"
                errors={fieldErrors.email} onChange={set("email")} />
              <Field id="password" label="Password" type="password" value={values.password}
                autoComplete="new-password" errors={fieldErrors.password} onChange={set("password")} />
              <Field id="confirm" label="Confirm password" type="password" value={values.confirm}
                autoComplete="new-password" errors={fieldErrors.confirm} onChange={set("confirm")} />
              <p className="text-xs text-muted-foreground">
                At least 8 characters; not a common password, not only digits and not close to your
                username or email. There is no password reset yet, so keep it somewhere safe.
              </p>
            </>
          )}
        </div>

        {formError && (
          <div role="alert" className="mt-6 border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
            <p>{formError}</p>
            {suggestMode && (
              <button
                type="button"
                onClick={() => switchMode(suggestMode)}
                className="mt-2 font-medium underline underline-offset-2"
              >
                {suggestMode === "signin" ? "Sign in instead" : "Create an account instead"}
              </button>
            )}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="mt-8 w-full border border-primary bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-70"
        >
          {submitting ? copy.busy : copy.submit}
        </button>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="mt-2 w-full border border-input px-4 py-2.5 text-sm transition-colors hover:bg-accent"
        >
          Go back
        </button>
      </form>
    </div>
  );
};

export default LoginPage;
