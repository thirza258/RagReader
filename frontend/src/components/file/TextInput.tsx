import React, { ChangeEvent } from "react";

interface TextInputProps {
  value: string;
  onChange: (event: ChangeEvent<HTMLTextAreaElement>) => void;
  disabled: boolean;
}

export const TextInputSection: React.FC<TextInputProps> = ({
  value,
  onChange,
  disabled,
}) => (
  <div>
    <label htmlFor="text-input" className="mb-1.5 block text-sm font-medium">
      Or paste the text
    </label>
    <textarea
      id="text-input"
      rows={4}
      value={value}
      onChange={onChange}
      placeholder="Paste your content here…"
      disabled={disabled}
      className={`w-full resize-y border border-input bg-background px-3 py-2 text-sm outline-none transition-colors
        placeholder:text-muted-foreground focus:border-primary
        ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    />
  </div>
);

export default TextInputSection;
