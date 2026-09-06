import React, { RefObject, ChangeEvent } from "react";

interface FileUploadProps {
  // React 19 types `useRef<T>(null)` as RefObject<T | null>.
  inputRef: RefObject<HTMLInputElement | null>;
  onChange: (event: ChangeEvent<HTMLInputElement>) => void;
  disabled: boolean;
  fileName?: string;
  onClear?: () => void;
}

// Kept in step with what the backend's DataLoader can actually read, so the
// picker never offers a file the upload would reject.
const ACCEPTED_FILE_TYPES =
  ".pdf,.txt,.md,.markdown,text/plain,text/markdown,application/pdf";

export const FileUploadSection: React.FC<FileUploadProps> = ({
  inputRef,
  onChange,
  disabled,
  fileName,
  onClear,
}) => (
  <div>
    <div className="mb-1.5 flex items-baseline justify-between">
      <label htmlFor="file-upload" className="text-sm font-medium">
        Upload a file{" "}
        <span className="font-normal text-muted-foreground">(PDF, TXT, MD)</span>
      </label>
      {fileName && !disabled && (
        <button
          type="button"
          onClick={onClear}
          className="text-xs text-muted-foreground underline underline-offset-2 hover:text-destructive"
        >
          Remove
        </button>
      )}
    </div>

    <input
      id="file-upload"
      type="file"
      ref={inputRef}
      onChange={onChange}
      disabled={disabled}
      accept={ACCEPTED_FILE_TYPES}
      className={`w-full border border-input bg-background px-3 py-2 text-sm outline-none transition-colors
        file:mr-3 file:border-0 file:bg-muted file:px-3 file:py-1 file:text-sm file:text-foreground
        focus:border-primary ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
    />

    {fileName && (
      <p className="mt-1.5 truncate text-xs text-muted-foreground">
        Selected: {fileName}
      </p>
    )}
  </div>
);

export default FileUploadSection;
