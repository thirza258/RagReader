import React from "react";

// --- Types ---

export interface RetrievedChunk {
  id: string | number;
  label?: string; 
  text: string;
}

export interface ModelConsensus {
  modelName: string;
  status: "AGREE" | "DISAGREE" | "NEUTRAL";
}

export interface EvaluationMetric {
  label: string;
  value: string | number;
}

interface DeepAnalysisCardProps {
  method: string; // e.g., "Hybrid Retrieval"
  aiModel: string; // e.g., "GPT-4o"
  query: string;
  answer: string;
  retrievedChunks: RetrievedChunk[];
  evaluationMetrics?: EvaluationMetric[];
  className?: string;
}

// --- Component ---

const DeepAnalysisCard: React.FC<DeepAnalysisCardProps> = ({
  method,
  aiModel,
  query,
  answer,
  retrievedChunks,
  evaluationMetrics = [],
  className = "",
}) => {
  // Helper to determine color based on agreement status
  const getStatusColor = (status: string) => {
    switch (status) {
      case "AGREE":
        return "text-green-400";
      case "DISAGREE":
        return "text-red-400";
      default:
        return "text-yellow-400";
    }
  };

  return (
    <div className={`relative ${className}`}>
      {/* Main Card */}
      <div className="relative z-10 bg-slate-900 border border-slate-700 rounded-2xl p-4 shadow-2xl  ">
        
        {/* Header (Window Controls + Title) */}
        <div className="flex items-center gap-3 mb-4 border-b border-slate-700 pb-4">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-red-500" />
            <div className="w-3 h-3 rounded-full bg-yellow-500" />
            <div className="w-3 h-3 rounded-full bg-green-500" />
          </div>
          <div className="ml-2 text-white font-semibold text-sm">
            {method} - <span className="text-slate-400">{aiModel}</span>
          </div>
        </div>

        <div className="space-y-4">
          <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
            <div className="text-xs text-slate-400 mb-1 uppercase tracking-wider">Query</div>
            <div className="text-white font-medium text-sm leading-relaxed">
              {query}
            </div>
          </div>
          
          
          {/* Answer Section */}
          <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
            <div className="text-xs text-slate-400 mb-1 uppercase tracking-wider">Generated Answer</div>
            <div className="text-white font-medium text-sm leading-relaxed">
              {answer}
            </div>
          </div>

          {/* Retrieved Chunks Section */}
          <div className="space-y-2">
            <div className="text-xs text-slate-400 uppercase tracking-wider">Retrieved Context</div>
            
            {retrievedChunks.length > 0 ? (
              retrievedChunks.map((chunk, index) => (
                <div 
                  key={chunk.id} 
                  className="bg-slate-800/70 p-3 rounded-lg border border-slate-700 text-sm text-slate-300 transition-colors hover:bg-slate-800"
                >
                  <span className="text-cyan-400 font-mono text-xs mr-2">
                    {chunk.label || `Chunk ${index + 1}`}:
                  </span>
                  {chunk.text}
                </div>
              ))
            ) : (
              <div className="text-slate-500 text-xs italic">No chunks retrieved.</div>
            )}
          </div>



          {/* RAG Evaluation Metrics */}
          {evaluationMetrics.length > 0 && (
            <div className={`grid gap-2 ${evaluationMetrics.length <= 3 ? `grid-cols-${evaluationMetrics.length}` : 'grid-cols-3'}`}>
              {evaluationMetrics.map((metric, idx) => (
                <div key={idx} className="bg-slate-800 p-3 rounded-lg text-center border border-slate-700">
                  <div className="text-xs text-slate-500 mb-1">{metric.label}</div>
                  <div className="text-xl font-bold text-cyan-400">{metric.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="absolute -inset-4 bg-gradient-to-r from-cyan-600 to-blue-600 opacity-30 blur-2xl -z-10 rounded-full pointer-events-none" />
    </div>
  );
};

export default DeepAnalysisCard;