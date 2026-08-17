import React, { useState } from "react";
import { Terminal, Copy, Check, ExternalLink } from "lucide-react";

export const QuickStartCode: React.FC = () => {
  const [copied, setCopied] = useState<boolean>(false);

  const command = `git clone https://github.com/thirza258/RagReader.git
cd RagReader
cp .env.example .env # Add your OPENROUTER_API_KEY
docker compose up --build`;

  const handleCopy = () => {
    navigator.clipboard.writeText(command);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="w-full bg-slate-950 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
      <div className="flex items-center justify-between px-4 py-3 bg-slate-900 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-cyan-400" />
          <span className="text-xs font-mono font-semibold text-slate-300">
            Self-Host with Docker Compose
          </span>
        </div>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs font-medium text-slate-200 transition-colors"
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" /> Copied!
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5 text-slate-400" /> Copy commands
            </>
          )}
        </button>
      </div>
      <pre className="p-4 text-xs font-mono text-cyan-300 leading-relaxed overflow-x-auto bg-slate-950">
        <code>{command}</code>
      </pre>
      <div className="px-4 py-2.5 bg-slate-900/50 border-t border-slate-800/80 flex items-center justify-between text-xs text-slate-400">
        <span>MIT Licensed · Complete stack runs in Docker</span>
        <a
          href="https://github.com/thirza258/RagReader#readme"
          target="_blank"
          rel="noreferrer"
          className="text-cyan-400 hover:underline flex items-center gap-1"
        >
          View README docs <ExternalLink className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
};

export default QuickStartCode;
