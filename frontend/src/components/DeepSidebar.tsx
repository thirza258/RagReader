import React, { useState } from "react";
import { 
  ArrowLeft, 
  FileText, 
  Settings, 
  Database, 
  Cpu, 
  Layers, 
  Play 
} from "lucide-react";

// --- Types ---
interface DeepSidebarProps {
  file?: File; // The active file being analyzed
  onBack: () => void; // Function to go back to the previous view
  onAnalyze: (config: DeepAnalysisConfig) => void; // Trigger analysis
}

export interface DeepAnalysisConfig {
  topK: number;
  chunkSize: number;
  retrievalMethods: string[];
  selectedModels: string[];
}

const RETRIEVAL_OPTIONS = ["Dense Retrieval", "Sparse Retrieval", "Hybrid Retrieval", "Iterative Retrieval", "Reranking"];
const AI_OPTIONS = ["GPT-4o", "Gemini Pro", "Claude 3.5 Sonnet"];

const DeepSidebar: React.FC<DeepSidebarProps> = ({ file, onBack, onAnalyze }) => {
  // --- Local State for Configuration ---
  const [topK, setTopK] = useState<number>(5);
  const [chunkSize, setChunkSize] = useState<number>(512);
  
  const [methods, setMethods] = useState<Record<string, boolean>>({
    Hybrid: true,
    Sparse: false,
    Dense: false,
    Iterative: false,
    Reranker: false,
  });

  const [models, setModels] = useState<Record<string, boolean>>({
    "GPT-4o": true,
    "Gemini Pro": false,
    "Claude 3.5 Sonnet": false,
  });

  // --- Handlers ---
  const toggleMethod = (method: string) => {
    setMethods(prev => ({ ...prev, [method]: !prev[method] }));
  };

  const toggleModel = (model: string) => {
    setModels(prev => ({ ...prev, [model]: !prev[model] }));
  };

  const handleAnalyzeClick = () => {
    const config: DeepAnalysisConfig = {
      topK,
      chunkSize,
      retrievalMethods: Object.keys(methods).filter(k => methods[k]),
      selectedModels: Object.keys(models).filter(k => models[k]),
    };
    onAnalyze(config);
  };

  // Helper to format bytes
  const formatSize = (bytes: number) => {
    if (bytes === 0) return "0 B";
    const k = 1024;
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + ["B", "KB", "MB", "GB"][i];
  };

  return (
    <div className="w-1/3 min-w-[320px] max-w-[400px] h-full flex flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] text-[hsl(var(--card-foreground))] shadow-2xl z-20">
      
      {/* --- HEADER --- */}
      <div className="p-4 border-b border-[hsl(var(--border))] flex items-center gap-3">
        <button 
          onClick={onBack}
          className="p-2 rounded-md hover:bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))] transition-colors"
        >
          <ArrowLeft size={20} />
        </button>
        <div>
          <h2 className="text-lg font-bold tracking-tight text-[hsl(var(--foreground))]">
            Deep Analysis
          </h2>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Configuration & Pipeline
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-8">
        
        {/* --- 1. TARGET METADATA --- */}
        <section>
          <div className="flex items-center gap-2 mb-3 text-[hsl(var(--primary))]">
            <FileText size={16} />
            <h3 className="text-xs font-bold uppercase tracking-wider">Target Context</h3>
          </div>
          
          {file ? (
            <div className="p-4 rounded-lg bg-[hsl(var(--background))] border border-[hsl(var(--border))] shadow-sm">
              <div className="flex justify-between items-start mb-2">
                <span className="bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))] text-[10px] px-2 py-0.5 rounded font-bold">
                  ACTIVE FILE
                </span>
                <span className="text-xs text-[hsl(var(--muted-foreground))]">
                  {formatSize(file.size)}
                </span>
              </div>
              <p className="text-sm font-medium truncate mb-1" title={file.name}>
                {file.name}
              </p>
              <p className="text-xs text-[hsl(var(--muted-foreground))] uppercase">
                {file.type || "Unknown Type"}
              </p>
            </div>
          ) : (
             <div className="p-4 rounded-lg bg-[hsl(var(--muted))] border border-dashed border-[hsl(var(--border))] text-center">
               <p className="text-sm text-[hsl(var(--muted-foreground))]">No file selected</p>
             </div>
          )}
        </section>

        {/* --- 2. CHUNK SETTINGS --- */}
        <section>
          <div className="flex items-center gap-2 mb-3 text-[hsl(var(--primary))]">
            <Settings size={16} />
            <h3 className="text-xs font-bold uppercase tracking-wider">Chunking Strategy</h3>
          </div>

          <div className="space-y-4">
            {/* Top K Slider */}
            <div>
              <div className="flex justify-between mb-2">
                <label className="text-sm font-medium text-[hsl(var(--foreground))]">Retrieved Chunks (Top-K)</label>
                <span className="text-sm font-bold text-[hsl(var(--primary))]">{topK}</span>
              </div>
              <input 
                type="range" 
                min="1" 
                max="20" 
                value={topK} 
                onChange={(e) => setTopK(parseInt(e.target.value))}
                className="w-full h-2 bg-[hsl(var(--muted))] rounded-lg appearance-none cursor-pointer accent-[hsl(var(--primary))]"
              />
            </div>

            {/* Chunk Size Input */}
            <div>
              <label className="text-sm font-medium text-[hsl(var(--foreground))] block mb-2">Chunk Size (Tokens)</label>
              <div className="relative">
                <input 
                  type="number" 
                  value={chunkSize}
                  onChange={(e) => setChunkSize(parseInt(e.target.value))}
                  className="w-full bg-[hsl(var(--background))] border border-[hsl(var(--input))] rounded-md py-2 px-3 text-sm focus:outline-none focus:ring-1 focus:ring-[hsl(var(--ring))]"
                />
                <span className="absolute right-3 top-2.5 text-xs text-[hsl(var(--muted-foreground))]">tokens</span>
              </div>
            </div>
          </div>
        </section>

        {/* --- 3. RETRIEVAL METHOD --- */}
        <section>
          <div className="flex items-center gap-2 mb-3 text-[hsl(var(--primary))]">
            <Database size={16} />
            <h3 className="text-xs font-bold uppercase tracking-wider">Retrieval Pipeline</h3>
          </div>
          
          <div className="space-y-2">
            {RETRIEVAL_OPTIONS.map((option) => (
              <label key={option} className="flex items-center justify-between p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--muted))] cursor-pointer transition-colors group">
                <span className="text-sm font-medium text-[hsl(var(--foreground))] group-hover:text-[hsl(var(--primary))] transition-colors">
                  {option}
                </span>
                <input 
                  type="checkbox"
                  checked={methods[option]}
                  onChange={() => toggleMethod(option)}
                  className="w-4 h-4 rounded border-gray-300 text-[hsl(var(--primary))] focus:ring-[hsl(var(--ring))] accent-[hsl(var(--primary))]"
                />
              </label>
            ))}
          </div>
        </section>

        {/* --- 4. AI MODEL SELECTION --- */}
        <section>
          <div className="flex items-center gap-2 mb-3 text-[hsl(var(--primary))]">
            <Cpu size={16} />
            <h3 className="text-xs font-bold uppercase tracking-wider">Model Consensus</h3>
          </div>

          <div className="grid grid-cols-1 gap-2">
            {AI_OPTIONS.map((model) => (
              <label key={model} className={`flex items-center p-3 rounded-md border cursor-pointer transition-all ${
                models[model] 
                  ? "bg-[hsl(var(--muted))] border-[hsl(var(--primary))] shadow-sm" 
                  : "bg-[hsl(var(--background))] border-[hsl(var(--border))]"
              }`}>
                <input 
                  type="checkbox"
                  checked={models[model]}
                  onChange={() => toggleModel(model)}
                  className="w-4 h-4 rounded border-gray-300 text-[hsl(var(--primary))] focus:ring-[hsl(var(--ring))] accent-[hsl(var(--primary))]"
                />
                <span className={`ml-3 text-sm font-medium ${
                  models[model] ? "text-[hsl(var(--primary))]" : "text-[hsl(var(--foreground))]"
                }`}>
                  {model}
                </span>
              </label>
            ))}
          </div>
        </section>

      </div>

      {/* --- FOOTER ACTION --- */}
      <div className="p-4 border-t border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <button 
          onClick={handleAnalyzeClick}
          className="w-full flex items-center justify-center gap-2 bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))/90] text-[hsl(var(--primary-foreground))] py-3 px-4 rounded-lg font-bold shadow-lg transition-all transform active:scale-95"
        >
          <Play size={18} fill="currentColor" />
          RUN DEEP ANALYSIS
        </button>
      </div>

    </div>
  );
};

export default DeepSidebar;