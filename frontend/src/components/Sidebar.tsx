import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import service from "../services/service";
import { FileMetadata, ConversationItem } from "../interface";

const Sidebar: React.FC = () => {
  const navigate = useNavigate();

  const [files, setFiles] = useState<FileMetadata[]>([]);
  const[history, setHistory] = useState<ConversationItem[]>([]);

  const usernameFromStorage = localStorage.getItem("username");

   useEffect(() => {
    if (!usernameFromStorage) {
      navigate("/login");
      return;
    }

    const fetchData = async () => {
      try {
        const cacheKey = `chat_history_${usernameFromStorage}`;
        const cachedHistory = sessionStorage.getItem(cacheKey);

        const filesPromise = service.getDocumentInfo(usernameFromStorage).catch(err => {
          console.error("Failed to fetch files:", err);
          return null; 
        });

        const historyPromise = cachedHistory
          ? Promise.resolve(JSON.parse(cachedHistory))
          : service.getConversationHistory(usernameFromStorage)
              .then((res) => {
                const unwrappedData = res?.data || res ||[];
                const dataToCache = Array.isArray(unwrappedData) ? unwrappedData :[];
                sessionStorage.setItem(cacheKey, JSON.stringify(dataToCache));
                return dataToCache;
              })
              .catch(err => {
                console.error("Failed to fetch history:", err);
                return [];
              });

        const [historyResponse, filesResponse] = await Promise.all([
          historyPromise,
          filesPromise,
        ]);

        setHistory(Array.isArray(historyResponse) ? historyResponse :[]);

        const actualFiles = filesResponse?.data || filesResponse;

        if (Array.isArray(actualFiles)) {
          setFiles(actualFiles);
        } else if (actualFiles && typeof actualFiles === 'object' && actualFiles.id) {
          setFiles([actualFiles]);
        } else {
          setFiles([]);
        }
        
      } catch (error) {
        console.error("Error fetching sidebar data:", error);
        setHistory([]);
        setFiles([]);
      }
    };

    fetchData();
  },[usernameFromStorage, navigate]);

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
        <section>
          <h3 className="text-sm font-semibold uppercase tracking-wider text-[hsl(var(--primary))] mb-3">
            Current Active Content
          </h3>

          {/* SAFEGUARD: added safe optional chaining files?.length */}
          {!files?.length ? (
            <div className="p-4 rounded-lg bg-[hsl(var(--muted))] border border-dashed border-[hsl(var(--border))] text-center">
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                No active content selected.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {files.map((file) => (
                <div
                  key={file.id}
                  className="p-4 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] shadow-sm relative overflow-hidden"
                >
                  <div className="absolute top-0 left-0 w-1 h-full bg-[hsl(var(--primary))]"></div>
                  <div className="flex items-center mb-2">
                    <span className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-xs px-2 py-1 rounded">
                      FILE
                    </span>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">
                        File Name
                      </p>
                      <p className="text-sm font-medium truncate" title={file.name}>
                        {file.name}
                      </p>
                    </div>

                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">
                          Type
                        </p>
                        <p className="text-sm truncate" title={file.source_type}>
                          {file.source_type || "Unknown"}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">
                          Date Added
                        </p>
                        <p className="text-sm">
                          {file.created_at ? new Date(file.created_at).toLocaleDateString() : "Unknown"}
                        </p>
                      </div>
                    </div>

                    <div>
                      <p className="text-xs text-[hsl(var(--muted-foreground))] font-semibold">
                        Source Path
                      </p>
                      <p className="text-sm truncate" title={file.source_path}>
                        {file.source_path || "N/A"}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <hr className="border-[hsl(var(--border))]" />

        <section>
          <div className="flex justify-between items-center mb-3">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-[hsl(var(--primary))]">
              Recent History
            </h3>
            {/* SAFEGUARD: Fallback to 0 if history is undefined */}
            <span className="text-xs text-[hsl(var(--muted-foreground))]">
              {history?.length || 0} Items
            </span>
          </div>

          {/* SAFEGUARD: properly checks optional chaining */}
          {!history?.length ? (
            <p className="text-sm text-[hsl(var(--muted-foreground))] italic">
              No recent history.
            </p>
          ) : (
            <div className="space-y-2">
              {history.map((item, index) => (
                <div
                  key={index}
                  className="group p-3 rounded-md border border-transparent hover:border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))] cursor-pointer transition-all duration-200"
                >
                  <div className="flex justify-between items-start">
                    <p
                      className="text-sm font-medium group-hover:text-[hsl(var(--primary))] transition-colors truncate pr-2"
                      title={item.query}
                    >
                      {item.query}
                    </p>
                    <span className="text-[10px] bg-[hsl(var(--muted))] border border-[hsl(var(--border))] px-1 rounded text-[hsl(var(--muted-foreground))] whitespace-nowrap">
                      Chat
                    </span>
                  </div>
                  <p
                    className="text-xs text-[hsl(var(--muted-foreground))] mt-1 line-clamp-2"
                    title={item.response}
                  >
                    {item.response}
                  </p>
                  <p className="text-[10px] text-[hsl(var(--muted-foreground))] mt-2 opacity-70">
                    {item.created_at ? new Date(item.created_at).toLocaleString() : "Unknown"}
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