import React from "react";
import { errorBox } from "./classes";

interface ErrorNoticeProps {
  title?: string;
  code?: string | null;
  message: string;
  /** Extra lines such as "Stage: Embedding". */
  children?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}

/** A structured error (PRD §38): what failed, why, its code, what to do. */
const ErrorNotice: React.FC<ErrorNoticeProps> = ({ title, code, message, children, actions, className = "" }) => (
  <div role="alert" className={`${errorBox} ${className}`}>
    {title && <p className="font-medium text-destructive">{title}</p>}
    <p className={title ? "mt-1 text-foreground/85" : "text-destructive"}>{message}</p>
    {children}
    {code && <p className="mt-1.5 break-all font-mono text-[11px] text-muted-foreground">Error code: {code}</p>}
    {actions && <div className="mt-2 flex flex-wrap gap-2">{actions}</div>}
  </div>
);

export default ErrorNotice;
