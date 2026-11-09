import React, { useState, useRef } from "react";
import FileUploadSection from "./file/FileInput";
import UrlUploadSection from "./file/URLInput";
import TextUploadSection from "./file/TextInput";
import { SubmitPayload } from "../types/types";
import { toApiError } from "../services/api/errors";
import { validatePastedText, validateSourceUrl, validateUploadFile } from "../features/documents/lib/uploadValidation";


interface FileSubmitProps {
  /** Uploads the source and moves on (to the workspace); rejects on failure. */
  onSubmit: (payload: SubmitPayload) => Promise<void>;
}

const FileSubmit: React.FC<FileSubmitProps> = ({
  onSubmit,
}) => {
  const [fileLocal, setFileLocal] = useState<File | null>(null);
  const [url, setLocalUrl] = useState<string>("");
  const [textInput, setTextInput] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);

  // Reference to the file input element to clear it programmatically
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      const selectedFile = event.target.files[0];
      setFileLocal(selectedFile)
      setLocalUrl("");
      setTextInput("");
    }
  };

  const handleUrlChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setLocalUrl(value);

    // If user starts typing URL, clear other inputs
    if (value) {
      setFileLocal(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTextInput("");
    }
  };

  const handleTextChange = (event: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.target.value;
    setTextInput(value);

    // If user starts typing Text, clear other inputs
    if (value) {
      setFileLocal(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setLocalUrl("");
    }
  };

  const handleSubmit = async () => {
    if (!fileLocal && !url && !textInput) {
      setError({ code: "invalid_request", message: "Upload a file, enter a URL, or paste text." });
      return;
    }
    // The same checks the backend makes, so a doomed upload is never sent.
    let payload: SubmitPayload;
    if (fileLocal) {
      const problem = validateUploadFile(fileLocal);
      if (problem) {
        setError(problem);
        return;
      }
      payload = { type: "file", file: fileLocal };
    } else if (url) {
      const checked = validateSourceUrl(url);
      if ("problem" in checked) {
        setError(checked.problem);
        return;
      }
      payload = { type: "url", url: checked.url };
    } else {
      const problem = validatePastedText(textInput);
      if (problem) {
        setError(problem);
        return;
      }
      payload = { type: "text", text: textInput };
    }
    setError(null);
    setIsLoading(true);

    try {
      await onSubmit(payload);
    } catch (caught) {
      const apiError = toApiError(caught, "Failed to submit.");
      setError({ code: apiError.code, message: apiError.message });
    } finally {
      setIsLoading(false);
    }
  };

  // --- Helpers for disabling inputs ---
  const isFileFilled = !!fileLocal;
  const isUrlFilled = url.length > 0;
  const isTextFilled = textInput.length > 0;

  return (
    <div className="w-full p-6">
      <div className="w-full space-y-5">
        <FileUploadSection
          inputRef={fileInputRef}
          onChange={handleFileChange}
          disabled={isUrlFilled || isTextFilled}
          fileName={fileLocal?.name}
          onClear={() => {
            setFileLocal(null);
            if (fileInputRef.current) {
              fileInputRef.current.value = "";
            }
          }}
        />
        <UrlUploadSection
          value={url}
          onChange={handleUrlChange}
          disabled={isFileFilled || isTextFilled}
        />
        <TextUploadSection
          value={textInput}
          onChange={handleTextChange}
          disabled={isFileFilled || isUrlFilled}
        />
      </div>

      {error && (
        <div role="alert" className="mt-6 border border-destructive/30 bg-destructive/5 p-3 text-sm">
          <p className="text-destructive">{error.message}</p>
          <p className="mt-1 break-all font-mono text-xs text-muted-foreground">Error code: {error.code}</p>
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={isLoading}
        className="mt-6 w-full border border-primary bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? "Submitting…" : "Submit"}
      </button>
    </div>
  );
};

export default FileSubmit;