import React, { useState, useMemo, useEffect } from "react";
import { Search } from "lucide-react";
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
    return <p className="p-4 text-sm text-muted-foreground">Loading chunks…</p>;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-3 border-b border-border pb-4 md:flex-row">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search the chunks…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full border border-input bg-background py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
          />
        </div>
        <div className="flex gap-2">
          {(["all", "selected"] as const).map((value) => (
            <button
              key={value}
              onClick={() => setFilterMode(value)}
              aria-pressed={filterMode === value}
              className={cn(
                "border px-3 py-2 text-xs transition-colors",
                filterMode === value
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              {value === "all" ? "All chunks" : "Selected only"}
            </button>
          ))}
        </div>
      </div>

      {/* Chunk Grid */}
      {filteredChunks.length === 0 ? (
        <p className="py-10 text-center text-sm text-muted-foreground">
          No chunks match your search.
        </p>
      ) : (
        <div className="custom-scrollbar grid max-h-[500px] grid-cols-1 gap-4 overflow-y-auto pr-2 lg:grid-cols-2">
          {filteredChunks.map((chunk) => {
            const isSelected = selectedIds.has(chunk.id);
            return (
              <div
                key={chunk.id}
                onClick={() => toggleSelection(chunk.id)}
                className={cn(
                  "cursor-pointer border p-4 transition-colors",
                  isSelected
                    ? "border-foreground/40 bg-accent"
                    : "border-border hover:bg-accent"
                )}
              >
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    {chunk.id}
                  </span>
                  <input
                    type="checkbox"
                    readOnly
                    checked={isSelected}
                    tabIndex={-1}
                    className="h-4 w-4 shrink-0 accent-primary"
                  />
                </div>
                <p className="line-clamp-4 text-sm leading-relaxed text-muted-foreground">
                  {chunk.text}
                </p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default GroundTruthChunk;