import { useState } from "react";
import service from "../services/service";
import { ChatResponse } from "../interface";
import { useNavigate } from "react-router-dom";

import { ChatMessage } from "../components/ui/chatmessage";
import { Message } from "../types/types";
import SEO from "../components/SEO";

function Chatbot() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [chatLoading, setChatLoading] = useState<boolean>(false);

  const navigate = useNavigate();

  const sendMessage = async (): Promise<void> => {
    if (!input.trim() || chatLoading) return;

    const userMessage: Message = {
      user: "me",
      text: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setChatLoading(true);

    try {
      const username = localStorage.getItem("username") || "";
      const response: ChatResponse = await service.generateChat(input, username);

      if (response.status !== 200) {
        throw new Error(response.message);
      }

      sessionStorage.removeItem(`chat_history_${username}`);

      const botMessage: Message = {
        user: "bot",
        text: response.data.answer,
        conversationId: response.data.conversation_id,
        documentId: response.data.document_id,
      };

      setMessages((prev) => [...prev, botMessage]);
    } catch (error) {
      console.error("Error fetching AI response:", error);

      setMessages((prev) => [
        ...prev,
        {
          user: "bot",
          text: "Sorry, something went wrong.",
        },
      ]);
    } finally {
      setChatLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-64px)] flex-col bg-background text-foreground">
      <SEO
        title="Document Chat Workspace — RAGReader"
        description="Query your uploaded document with dense vector retrieval."
      />

      <div className="flex-grow overflow-y-auto px-6 py-6">
        {messages.length === 0 && !chatLoading && (
          <p className="mt-16 text-center text-sm text-muted-foreground">
            Ask a question about the document. The first answer comes from dense
            retrieval.
          </p>
        )}

        {messages.map((msg, index) => (
          <ChatMessage
            key={index}
            user={msg.user}
            text={msg.text}
            onDeepAnalysis={() =>
              navigate(`/ground-truth/${msg.conversationId}/${msg.documentId}`)
            }
          />
        ))}

        {chatLoading && (
          <p className="text-center text-sm text-muted-foreground">Thinking…</p>
        )}
      </div>

      <div className="flex flex-shrink-0 items-center gap-3 border-t border-border px-6 py-4">
        <input
          type="text"
          className="flex-grow border border-input bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) =>
            e.key === "Enter" && !chatLoading ? sendMessage() : null
          }
          placeholder="Type your question"
          disabled={chatLoading}
        />
        <button
          className="border border-primary bg-primary px-5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
          onClick={sendMessage}
          disabled={chatLoading}
        >
          {chatLoading ? "Sending…" : "Send"}
        </button>
      </div>
    </div>
  );
}

export default Chatbot;
