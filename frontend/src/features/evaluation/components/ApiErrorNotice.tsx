import React from "react";
import ErrorNotice from "../../../components/ui/ErrorNotice";
import type { ApiRequestError } from "../../../services/api/errors";

function fieldErrors(error: ApiRequestError): [string, string][] {
  const details = error.details;
  if (!details || typeof details !== "object" || Array.isArray(details)) return [];
  return Object.entries(details as Record<string, unknown>).map(([field, messages]) => [
    field,
    Array.isArray(messages) ? messages.map(String).join(" ") : typeof messages === "string" ? messages : JSON.stringify(messages),
  ]);
}

interface ApiErrorNoticeProps {
  title: string;
  error: ApiRequestError;
  actions?: React.ReactNode;
  className?: string;
}

/** An API error with its code and, for `invalid_request`, one line per field. */
const ApiErrorNotice: React.FC<ApiErrorNoticeProps> = ({ title, error, actions, className }) => {
  const fields = fieldErrors(error);
  return (
    <ErrorNotice title={title} code={error.code} message={error.message} actions={actions} className={className}>
      {fields.length > 0 && (
        <ul className="mt-1 list-disc pl-4 text-[11px]">
          {fields.map(([field, message]) => (
            <li key={field}>
              <span className="font-mono">{field}</span>: {message}
            </li>
          ))}
        </ul>
      )}
    </ErrorNotice>
  );
};

export default ApiErrorNotice;
