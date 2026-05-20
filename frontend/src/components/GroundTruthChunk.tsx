import React, { useState, useMemo, useEffect } from "react";
import { Search, Database, CheckCircle2, Filter, FileText } from "lucide-react";
import service from "../services/service";
import { Chunk } from "../interface";

const cn = (...classes: (string | undefined | boolean)[]) =>
  classes.filter(Boolean).join(" ");

interface GroundTruthChunkProps {
  documentId: string;
  selectedIds: Set<string>;
  toggleSelection: (id: string) => void;
}

const GroundTruthChunk: React.FC<GroundTruthChunkProps> = ({
  documentId,
  selectedIds,
  toggleSelection,
}) => {
  const [allChunks, setAllChunks] = useState<Chunk[]>([]);
  const[searchQuery, setSearchQuery] = useState("");
  const [filterMode, setFilterMode] = useState<"all" | "selected">("all");
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchChunks = async () => {
      setIsLoading(true);
      try {
        if (documentId) {
          const response = await service.getChunk(documentId);
          setAllChunks(response.chunks ||[]);
        }
      } catch (error) {
        console.error("Error fetching chunks:", error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchChunks();
  }, [documentId]);

  const filteredChunks = useMemo(() => {
    return allChunks.filter((chunk) => {
      const matchesSearch = chunk.text
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const matchesMode = filterMode === "all" ? true : selectedIds.has(chunk.id);
      return matchesSearch && matchesMode;
    });
  }, [allChunks, searchQuery, filterMode, selectedIds]);

  if (isLoading)
    return <div className="p-4 text-muted-foreground">Loading chunks...</div>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col md:flex-row gap-3 border-b border-border/40 pb-4">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search content or source..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-muted/50 border border-input rounded-md pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setFilterMode("all")}
            className={cn(
              "px-3 py-2 text-xs font-medium rounded-md border transition-colors flex items-center gap-2",
              filterMode === "all"
                ? "bg-secondary text-secondary-foreground border-transparent"
                : "bg-transparent border-border hover:bg-muted text-muted-foreground"
            )}
          >
            <Database size={14} />
            All Chunks
          </button>
          <button
            onClick={() => setFilterMode("selected")}
            className={cn(
              "px-3 py-2 text-xs font-medium rounded-md border transition-colors flex items-center gap-2",
              filterMode === "selected"
                ? "bg-secondary text-secondary-foreground border-transparent"
                : "bg-transparent border-border hover:bg-muted text-muted-foreground"
            )}
          >
            <CheckCircle2 size={14} />
            Selected Only
          </button>
        </div>
      </div>

      {/* Chunk Grid */}
      {filteredChunks.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-muted-foreground">
          <Filter size={32} className="mb-4 opacity-20" />
          <p>No chunks found matching your criteria.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-h-[500px] overflow-y-auto pr-2 custom-scrollbar">
          {filteredChunks.map((chunk) => {
            const isSelected = selectedIds.has(chunk.id);
            return (
              <div
                key={chunk.id}
                onClick={() => toggleSelection(chunk.id)}
                className={cn(
                  "group relative flex flex-col justify-between rounded-lg border p-4 cursor-pointer transition-all duration-200",
                  isSelected
                    ? "bg-primary/5 border-primary shadow-[0_0_0_1px_hsl(var(--primary))]"
                    : "bg-card border-border hover:border-muted-foreground/50 hover:bg-accent/50"
                )}
              >
                <div>
                  <div className="flex justify-between items-start mb-2">
                    <div className="flex items-center gap-2 text-xs text-muted-foreground">
                      <FileText size={12} />
                      <span className="truncate max-w-[150px]">{chunk.id}</span>
                    </div>
                    <div
                      className={cn(
                        "h-5 w-5 rounded-full border flex items-center justify-center transition-colors",
                        isSelected
                          ? "bg-primary border-primary text-primary-foreground"
                          : "border-muted-foreground/40 group-hover:border-muted-foreground"
                      )}
                    >
                      {isSelected && <CheckCircle2 size={12} />}
                    </div>
                  </div>
                  <p className="text-sm text-foreground/90 line-clamp-4 leading-relaxed">
                    {chunk.text}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default GroundTruthChunk;