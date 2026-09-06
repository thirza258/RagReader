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
    <aside className="z-10 flex h-full w-1/3 min-w-[300px] max-w-[380px] flex-col border-r border-border bg-muted">
      <div className="border-b border-border px-5 py-4">
        <h2 className="font-serif text-lg font-semibold">Context</h2>
        <p className="text-xs text-muted-foreground">
          Document metadata and session history
        </p>
      </div>

      <div className="custom-scrollbar flex-1 space-y-8 overflow-y-auto px-5 py-5">
        <section>
          <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Active document
          </h3>

          {!files?.length ? (
            <p className="mt-3 border border-dashed border-border px-4 py-4 text-sm text-muted-foreground">
              No active content selected.
            </p>
          ) : (
            <div className="mt-3 space-y-4">
              {files.map((file) => (
                <dl key={file.id} className="border-t border-border text-sm">
                  <div className="border-b border-border py-2">
                    <dt className="text-xs text-muted-foreground">Name</dt>
                    <dd className="truncate font-medium" title={file.name}>
                      {file.name}
                    </dd>
                  </div>
                  <div className="border-b border-border py-2">
                    <dt className="text-xs text-muted-foreground">Type</dt>
                    <dd className="truncate" title={file.source_type}>
                      {file.source_type || "Unknown"}
                    </dd>
                  </div>
                  <div className="border-b border-border py-2">
                    <dt className="text-xs text-muted-foreground">Added</dt>
                    <dd>
                      {file.created_at
                        ? new Date(file.created_at).toLocaleDateString()
                        : "Unknown"}
                    </dd>
                  </div>
                  <div className="border-b border-border py-2">
                    <dt className="text-xs text-muted-foreground">Source</dt>
                    <dd className="truncate" title={file.source_path}>
                      {file.source_path || "N/A"}
                    </dd>
                  </div>
                </dl>
              ))}
            </div>
          )}
        </section>

        <section>
          <div className="flex items-baseline justify-between">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Recent history
            </h3>
            <span className="font-mono text-xs text-muted-foreground tabular">
              {history?.length || 0}
            </span>
          </div>

          {!history?.length ? (
            <p className="mt-3 text-sm text-muted-foreground">No recent history.</p>
          ) : (
            <ul className="mt-3 border-t border-border">
              {history.map((item, index) => (
                <li
                  key={index}
                  className="cursor-pointer border-b border-border py-3 transition-colors hover:bg-accent"
                >
                  <p className="truncate text-sm font-medium" title={item.query}>
                    {item.query}
                  </p>
                  <p
                    className="mt-1 line-clamp-2 text-xs text-muted-foreground"
                    title={item.response}
                  >
                    {item.response}
                  </p>
                  <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                    {item.created_at
                      ? new Date(item.created_at).toLocaleString()
                      : "Unknown"}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </aside>
  );
};

export default Sidebar;
