import React, { useState, useMemo } from 'react';
import { 
  ArrowLeft, 
  CheckCircle2, 
  Search, 
  Database, 
  Filter, 
  Save,
  FileText
} from 'lucide-react';

interface Chunk {
  id: string;
  content: string;
  source: string;
  retrievalScore?: number; 
  isOriginallyRetrieved?: boolean; 
}

interface GroundTruthSelectorProps {
  allChunks: Chunk[];
  initialSelectedIds?: string[]; 
  onSave: (selectedIds: string[]) => void; 
  onCancel: () => void;
}

const cn = (...classes: (string | undefined | boolean)[]) => classes.filter(Boolean).join(' ');

const GroundTruthSelector: React.FC<GroundTruthSelectorProps> = ({ 
  allChunks, 
  initialSelectedIds = [], 
  onSave,
  onCancel 
}) => {
  // State
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set(initialSelectedIds));
  const [searchQuery, setSearchQuery] = useState('');
  const [filterMode, setFilterMode] = useState<'all' | 'selected'>('all');

  // Logic: Toggle Selection
  const toggleSelection = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedIds(next);
  };

  
  const filteredChunks = useMemo(() => {
    return allChunks.filter(chunk => {
      const matchesSearch = chunk.content.toLowerCase().includes(searchQuery.toLowerCase()) || 
                            chunk.source.toLowerCase().includes(searchQuery.toLowerCase());
      const matchesMode = filterMode === 'all' ? true : selectedIds.has(chunk.id);
      return matchesSearch && matchesMode;
    });
  }, [allChunks, searchQuery, filterMode, selectedIds]);


  const handleConfirm = () => {
    onSave(Array.from(selectedIds));
  };

  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-primary selection:text-primary-foreground">
      
      {/* --- Header --- */}
      <header className="sticky top-0 z-30 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="container mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button 
              onClick={onCancel}
              className="p-2 rounded-md hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft size={20} />
            </button>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Select Ground Truth</h1>
              <p className="text-xs text-muted-foreground">
                Select the chunks that contain the correct answer.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <div className="hidden md:flex flex-col items-end">
              <span className="text-sm font-medium text-primary">
                {selectedIds.size} Selected
              </span>
              <span className="text-xs text-muted-foreground">
                Total available: {allChunks.length}
              </span>
            </div>
            <button
              onClick={handleConfirm}
              className="flex items-center gap-2 bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-md text-sm font-medium transition-all shadow-[0_0_15px_-3px_rgba(6,182,212,0.4)]"
            >
              <Save size={16} />
              Save & Analyze
            </button>
          </div>
        </div>

        {/* --- Toolbar --- */}
        <div className="container mx-auto px-4 py-3 flex flex-col md:flex-row gap-3 border-t border-border/40">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search content or source..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-muted/50 border border-input rounded-md pl-9 pr-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/70"
            />
          </div>
          
          <div className="flex gap-2">
             <button
              onClick={() => setFilterMode('all')}
              className={cn(
                "px-3 py-2 text-xs font-medium rounded-md border transition-colors flex items-center gap-2",
                filterMode === 'all' 
                  ? "bg-secondary text-secondary-foreground border-transparent" 
                  : "bg-transparent border-border hover:bg-muted text-muted-foreground"
              )}
            >
              <Database size={14} />
              All Chunks
            </button>
            <button
              onClick={() => setFilterMode('selected')}
              className={cn(
                "px-3 py-2 text-xs font-medium rounded-md border transition-colors flex items-center gap-2",
                filterMode === 'selected' 
                  ? "bg-secondary text-secondary-foreground border-transparent" 
                  : "bg-transparent border-border hover:bg-muted text-muted-foreground"
              )}
            >
              <CheckCircle2 size={14} />
              Selected Only
            </button>
          </div>
        </div>
      </header>

      {/* --- Main Content --- */}
      <main className="container mx-auto px-4 py-6">
        {filteredChunks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <Filter size={48} className="mb-4 opacity-20" />
            <p>No chunks found matching your criteria.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredChunks.map((chunk) => {
              const isSelected = selectedIds.has(chunk.id);
              
              return (
                <div
                  key={chunk.id}
                  onClick={() => toggleSelection(chunk.id)}
                  className={cn(
                    "group relative flex flex-col justify-between rounded-lg border p-4 cursor-pointer transition-all duration-200",
                    // Selected State
                    isSelected 
                      ? "bg-primary/5 border-primary shadow-[0_0_0_1px_hsl(var(--primary))]" 
                      : "bg-card border-border hover:border-muted-foreground/50 hover:bg-accent/50"
                  )}
                >
                  <div>
                    {/* Header of Card */}
                    <div className="flex justify-between items-start mb-2">
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <FileText size={12} />
                        <span className="truncate max-w-[150px]">{chunk.source}</span>
                      </div>
                      
                      {/* Checkbox Visual */}
                      <div className={cn(
                        "h-5 w-5 rounded-full border flex items-center justify-center transition-colors",
                        isSelected 
                          ? "bg-primary border-primary text-primary-foreground" 
                          : "border-muted-foreground/40 group-hover:border-muted-foreground"
                      )}>
                        {isSelected && <CheckCircle2 size={12} />}
                      </div>
                    </div>

                    {/* Content */}
                    <p className="text-sm text-foreground/90 line-clamp-4 leading-relaxed">
                      {chunk.content}
                    </p>
                  </div>

                  {/* Footer of Card (Metadata) */}
                  <div className="mt-4 flex items-center justify-between pt-3 border-t border-border/50">
                    <span className="text-[10px] font-mono text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                      ID: {chunk.id.slice(0, 8)}...
                    </span>
                    
                    {chunk.isOriginallyRetrieved && (
                      <span className="text-[10px] uppercase font-bold text-secondary tracking-wider">
                        Originally Retrieved
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>
    </div>
  );
};

export default GroundTruthSelector;