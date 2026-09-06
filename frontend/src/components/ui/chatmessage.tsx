import React from "react";
import ReactMarkdown from "react-markdown";

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
    <div className={`mb-4 flex w-full ${isMe ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-xl border px-4 py-3 text-sm ${
          isMe
            ? "border-border bg-muted"
            : "border-border bg-card"
        }`}
      >
        <div className="prose-note text-base [&_p+p]:mt-3">
          <ReactMarkdown>{text}</ReactMarkdown>
        </div>

        {onDeepAnalysis && !isMe && (
          <button
            onClick={onDeepAnalysis}
            className="mt-3 border border-input px-3 py-1.5 text-xs font-medium transition-colors hover:bg-accent"
          >
            Deep analysis
          </button>
        )}
      </div>
    </div>
  );
};

export default ChatMessage;
