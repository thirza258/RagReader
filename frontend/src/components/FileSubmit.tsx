import React, { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import service from "../services/service";
import FileUploadSection from "./file/FileInput";
import UrlUploadSection from "./file/URLInput";
import TextUploadSection from "./file/TextInput";


interface FileSubmitProps {
  setFile: (file: File | null) => void;
  setUrl: (url: string | null) => void;
}

const FileSubmit: React.FC<FileSubmitProps> = ({
  setFile,
  setUrl,
}) => {
  const [fileLocal, setFileLocal] = useState<File | null>(null);
  const [url, setLocalUrl] = useState<string>("");
  const [textInput, setTextInput] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);

  // Reference to the file input element to clear it programmatically
  const fileInputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // --- Handlers ---

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    if (event.target.files && event.target.files[0]) {
      const selectedFile = event.target.files[0];
      setFileLocal(selectedFile);
      setFile(selectedFile);

      // Clear other inputs
      setLocalUrl("");
      setUrl("");
      setTextInput("");
    }
  };

  const handleUrlChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const value = event.target.value;
    setLocalUrl(value);
    setUrl(value);

    // If user starts typing URL, clear other inputs
    if (value) {
      setFileLocal(null);
      setFile(null);
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
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setLocalUrl("");
      setUrl("");
    }
  };

  const handleSubmit = async () => {
    if (!fileLocal && !url && !textInput) {
      alert("Please upload a file, enter a URL, or paste text.");
      return;
    }

    try {
      setIsLoading(true);

      let response;
      

      console.log("Submission successful:", response);
      alert("Submitted successfully!");
      navigate("/main");
    } catch (error) {
      console.error("Error submitting:", error);
      alert("Failed to submit.");
    } finally {
      setIsLoading(false);
    }
  };

  // --- Helpers for disabling inputs ---
  const isFileFilled = !!fileLocal;
  const isUrlFilled = url.length > 0;
  const isTextFilled = textInput.length > 0;

  return (
    <div className="card w-full mx-auto p-6">

      <div className="space-y-4 w-full">
       
        <FileUploadSection
          inputRef={fileInputRef}
          onChange={handleFileChange}
          disabled={isFileFilled || isUrlFilled || isTextFilled}
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

      {/* Submit Button */}
      <button
        onClick={handleSubmit}
        disabled={isLoading}
        className="w-full bg-blue-500 text-white py-2 px-4 rounded hover:bg-blue-600 disabled:bg-blue-300 disabled:cursor-not-allowed"
      >
        {isLoading ? "Submitting..." : "Submit"}
      </button>
    </div>
  );
};

export default FileSubmit;