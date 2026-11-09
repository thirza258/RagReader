import React, { useState } from "react";
import { ArrowUp } from "lucide-react";
import { buttonPrimary, inputBase } from "../../../components/ui/classes";

interface ComposerProps {
  /** Returns false when the question was not accepted (e.g. still streaming). */
  onSend: (content: string) => boolean | Promise<boolean>;
  busy: boolean;
  disabledReason?: string | null;
  placeholder?: string;
  id: string;
}

/**
 * The question box. Enter sends, Shift+Enter adds a line; sending is off
 * while an answer streams, but typing the next question is not.
 */
const Composer: React.FC<ComposerProps> = ({ onSend, busy, disabledReason = null, placeholder = "Ask a question about your documents", id }) => {
  const [value, setValue] = useState("");
  const [sending, setSending] = useState(false);
  const blocked = busy || sending || !!disabledReason;
  const canSend = !blocked && value.trim().length > 0;

  const submit = async () => {
    if (!canSend) return;
    const content = value.trim();
    setSending(true);
    try {
      const accepted = await onSend(content);
      if (accepted) setValue("");
    } finally {
      setSending(false);
    }
  };

  return (
    <form
      className="border-t border-border p-3"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label htmlFor={id} className="sr-only">
        Your question
      </label>
      <div className="flex items-end gap-2">
        <textarea
          id={id}
          rows={2}
          value={value}
          placeholder={placeholder}
          aria-describedby={`${id}-hint`}
          className={`${inputBase} max-h-40 min-h-[2.75rem] resize-none`}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              void submit();
            }
          }}
        />
        <button type="submit" className={`${buttonPrimary} h-[2.75rem] px-3`} disabled={!canSend} aria-label={busy ? "Sending is paused while the answer streams" : "Send question"}>
          <ArrowUp aria-hidden="true" className="h-4 w-4" />
        </button>
      </div>
      <p id={`${id}-hint`} className="mt-1 text-[11px] text-muted-foreground">
        {disabledReason ?? (busy ? "Answering… you can type the next question meanwhile." : "Enter to send · Shift+Enter for a new line")}
      </p>
    </form>
  );
};

export default Composer;
