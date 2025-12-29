import React, { RefObject, ChangeEvent } from "react";


interface FileUploadProps {
    inputRef: RefObject<HTMLInputElement>;
    onChange: (event: ChangeEvent<HTMLInputElement>) => void;
    disabled: boolean;
  }
  
  export const FileUploadSection: React.FC<FileUploadProps> = ({
    inputRef,
    onChange,
    disabled,
  }) => (
    <div className="mb-2 w-full">
      <label htmlFor="file-upload" className="block text-sm font-medium mb-2 w-full">
        Upload File:
      </label>
      <input
        id="file-upload"
        type="file"
        ref={inputRef}
        onChange={onChange}
        disabled={disabled}
        className={`w-full border rounded p-2 ${
          disabled ? "bg-gray-100 cursor-not-allowed opacity-50" : ""
        }`}
        style={{ width: "100%" }}
      />
    </div>
  );

export default FileUploadSection;