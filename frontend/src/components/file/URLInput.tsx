import React, { ChangeEvent } from "react";

interface UrlInputProps {
  value: string;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  disabled: boolean;
}

export const UrlInputSection: React.FC<UrlInputProps> = ({
  value,
  onChange,
  disabled,
}) => (
  <div>
    <label htmlFor="url-input" className="mb-1.5 block text-sm font-medium">
      Or a web page URL
    </label>
    <input
      id="url-input"
      type="text"
      value={value}
      onChange={onChange}
      placeholder="https://example.com"
      disabled={disabled}
      className={`w-full border border-input bg-background px-3 py-2 text-sm outline-none transition-colors
        placeholder:text-muted-foreground focus:border-primary
        ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    />
  </div>
);

export default UrlInputSection;
