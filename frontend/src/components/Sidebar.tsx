import React from "react";
import { format } from "date-fns"; // Optional: for nice date formatting, or use standard JS Date

// Define interfaces for History items
export interface HistoryItem {
  id: string;
  title: string;
  type: "file" | "url";
  date: string; // ISO string
}

interface SidebarProps {
  files?: File[];
  url?: string;
  // New prop for history (you can pass this from your parent state)
  history?: HistoryItem[];
}

const Sidebar: React.FC<SidebarProps> = ({ 
  files, 
  url, 
  history = [] // Default to empty array if not provided
}) => {
  
  // Helper to format bytes to KB/MB
  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 Bytes";
    const k = 1024;
    const sizes = ["Bytes", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
  };

  return (
    <div className="w-1/3 min-w-[300px] max-w-[400px] h-full flex flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--card-foreground))] shadow-xl z-10">
      
      <div className="p-4 border-b border-[hsl(var(--border))]">
        <h2 className="text-xl font-bold tracking-tight text-[hsl(var(--foreground))]">
          Context Details
        </h2>
        <p className="text-sm text-[hsl(var(--muted-foreground))]">
          Metadata & Session History
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        
        {/* --- SECTION 1: ACTIVE METADATA --- */}
        <section>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[hsl(var(--primary))] mb-3">
            Current Active Content
          </h3>

          {!files?.length && !url ? (
            <div className="p-4 rounded-lg bg-[hsl(var(--muted))] border border-dashed border-[hsl(var(--border))] text-center">
              <p className="text-sm text-[hsl(var(--muted-foreground))]">No active content selected.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {/* URL METADATA */}
              {url && (
                <div className="p-4 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] shadow-sm">
                  <div className="flex items-center mb-2">
                    <span className="bg-[hsl(var(--secondary))] text-[hsl(var(--secondary-foreground))] text-xs px-2 py-1 rounded">WEB RESOURCE</span>
                  </div>
                  <div className="space-y-2">
                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">URL</p>
                      <a href={url} target="_blank" rel="noreferrer" className="text-sm text-[hsl(var(--primary))] hover:underline break-all">
                        {url}
                      </a>
                    </div>
                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">Status</p>
                      <p className="text-sm">Active</p>
                    </div>
                  </div>
                </div>
              )}

              {/* FILE METADATA */}
              {files && files.map((file, index) => (
                <div key={index} className="p-4 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] shadow-sm relative overflow-hidden">
                  <div className="absolute top-0 left-0 w-1 h-full bg-[hsl(var(--primary))]"></div>
                  <div className="flex items-center mb-2">
                     <span className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-xs px-2 py-1 rounded">FILE</span>
                  </div>
                  
                  <div className="space-y-3">
                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">File Name</p>
                      <p className="text-sm font-medium truncate" title={file.name}>{file.name}</p>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">Size</p>
                        <p className="text-sm">{formatSize(file.size)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">Type</p>
                        <p className="text-sm truncate" title={file.type}>{file.type || "Unknown"}</p>
                      </div>
                    </div>

                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">Last Modified</p>
                      <p className="text-sm">
                        {new Date(file.lastModified).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <hr className="border-[hsl(var(--border))]" />

        {/* --- SECTION 2: HISTORY --- */}
        <section>
          <div className="flex justify-between items-center mb-3">
             <h3 className="text-sm font-semibold uppercase tracking-wider text-[hsl(var(--primary))]">
               Recent History
             </h3>
             <span className="text-xs text-[hsl(var(--muted-foreground))]">{history.length} Items</span>
          </div>

          {history.length === 0 ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] italic">No recent history.</p>
          ) : (
            <div className="space-y-2">
              {history.map((item) => (
                <div 
                  key={item.id} 
                  className="group p-3 rounded-md border border-transparent hover:border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))] cursor-pointer transition-all duration-200"
                >
                  <div className="flex justify-between items-start">
                    <p className="text-sm font-medium group-hover:text-[hsl(var(--primary))] transition-colors">
                      {item.title}
                    </p>
                    <span className="text-[10px] bg-[hsl(var(--muted))] border border-[hsl(var(--border))] px-1 rounded text-[hsl(var(--muted-foreground))]">
                      {item.type}
                    </span>
                  </div>
                  <p className="text-xs text-[hsl(var(--muted-foreground))] mt-1">
                    {item.date}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

      </div>
    </div>
  );
};

export default Sidebar;