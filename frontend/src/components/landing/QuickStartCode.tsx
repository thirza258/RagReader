import React, { useState } from "react";

const COMMAND = `git clone https://github.com/thirza258/RagReader.git
cd RagReader
cp .env.example .env      # add your OPENROUTER_API_KEY
docker compose up --build`;

export const QuickStartCode: React.FC = () => {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(COMMAND);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <figure className="border border-border">
      <figcaption className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-xs uppercase tracking-wide text-muted-foreground">
          Shell
        </span>
        <button
          onClick={handleCopy}
          className="text-xs text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </figcaption>

      <pre className="overflow-x-auto px-4 py-4 font-mono text-[13px] leading-relaxed">
        <code>{COMMAND}</code>
      </pre>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-2.5 text-xs text-muted-foreground">
        <span>The complete stack runs in Docker. MIT licensed.</span>
        <a
          href="https://github.com/thirza258/RagReader#readme"
          target="_blank"
          rel="noreferrer"
          className="link"
        >
          README
        </a>
      </div>
    </figure>
  );
};

export default QuickStartCode;
