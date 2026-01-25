import React from "react";
import ReactMarkdown from "react-markdown";
import { EvalScore } from "../../types/types";

type ChatMessageProps = {
  user: "me" | "bot";
  text: string;
  onDeepAnalysis?: () => void;
};

export const ChatMessage: React.FC<ChatMessageProps> = ({
  user,
  text,
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
          <div className="flex items-end mt-2">

            {onDeepAnalysis && user === "bot" && (
              <button
                onClick={onDeepAnalysis}
                className="bg-green-600 hover:bg-green-700 text-white text-xs px-4 py-1 rounded-full shadow transition-all"
              >
                Deep Analysis
              </button>
            )}
          </div>
      </div>
    </div>
  );
};

export default ChatMessage;