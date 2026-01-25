import { useState } from "react";
import service from "../services/service";
import { ChatResponse } from "../interface";
import { useNavigate } from "react-router-dom";

import { ChatMessage } from "../components/ui/chatmessage";
import { Message } from "../types/types";

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
  
      const botMessage: Message = {
        user: "bot",
        text: response.data.answer, 
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
   
    <div className="flex flex-col h-[calc(100vh-64px)] bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      
      <div className="flex-grow overflow-y-auto p-4">
      {messages.map((msg, index) => (
        <ChatMessage
          key={index}
          user={msg.user}
          text={msg.text}
          onDeepAnalysis={
            () => navigate("/deep-result")
          }
        />
      ))}

      {chatLoading && (
        <p className="text-center text-[hsl(var(--muted-foreground))]">
          Loading...
        </p>
      )}
    </div>

      <div className="flex-shrink-0 flex items-center p-4 bg-[hsl(var(--card))] border-t border-[hsl(var(--input))]">
        <input
          type="text"
          className="flex-grow border border-[hsl(var(--input))] rounded-lg px-4 py-2 mr-4 bg-[hsl(var(--background))] text-[hsl(var(--foreground))]"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) =>
            e.key === "Enter" && !chatLoading ? sendMessage() : null
          }
          placeholder="Type your message here"
          disabled={chatLoading}
        />
        <button
          className={`px-6 py-2 rounded-lg font-semibold transition-colors duration-200
            ${
              chatLoading
                ? "bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]"
                : "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
            }`}
          onClick={sendMessage}
          disabled={chatLoading}
        >
          {chatLoading ? "Sending..." : "Send"}
        </button>
      </div>
    </div>
  );
}

export default Chatbot;
