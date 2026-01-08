import React from "react";
import ReactMarkdown from "react-markdown";
import { EvalScore } from "../../types/types";

type ChatMessageProps = {
  user: "me" | "bot";
  text: string;
  evalScore?: EvalScore;
  onDeepAnalysis?: () => void;
};

export const ChatMessage: React.FC<ChatMessageProps> = ({
  user,
  text,
  evalScore,
  onDeepAnalysis,
}) => {
  const isMe = user === "me";

  return (
    <div className={`flex w-full mb-4 ${isMe ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-md p-4 rounded-2xl shadow-lg flex flex-col space-y-3
          ${
            isMe
              ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] rounded-br-md"
              : "bg-slate-800 text-slate-100 rounded-bl-md"
          }
        `}
      >
        {/* Message content */}
        <ReactMarkdown>{text}</ReactMarkdown>

        {/* Optional evaluation metrics */}
        {evalScore && (
          <div className="flex items-end mt-2">
            <div className="bg-slate-900/70 p-3 rounded-lg flex flex-row items-center space-x-6 text-xs mr-3">
              {evalScore.mrr5 !== undefined && (
                <div className="flex items-center space-x-1">
                  <span className="text-slate-400">MRR@5:</span>
                  <span className="font-bold text-yellow-300">
                    {evalScore.mrr5.toFixed(2)}
                  </span>
                </div>
              )}
              {evalScore.precision3 !== undefined && (
                <div className="flex items-center space-x-1">
                  <span className="text-slate-400">Precision@3:</span>
                  <span className="font-bold text-green-300">
                    {evalScore.precision3.toFixed(2)}
                  </span>
                </div>
              )}
              {evalScore.recall3 !== undefined && (
                <div className="flex items-center space-x-1">
                  <span className="text-slate-400">Recall@3:</span>
                  <span className="font-bold text-blue-300">
                    {evalScore.recall3.toFixed(2)}
                  </span>
                </div>
              )}
            </div>

            {onDeepAnalysis && (
              <button
                onClick={onDeepAnalysis}
                className="bg-green-600 hover:bg-green-700 text-white text-xs px-4 py-1 rounded-full shadow transition-all"
              >
                Deep Analysis
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;