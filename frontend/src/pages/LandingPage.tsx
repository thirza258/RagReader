import React, { useState } from "react";
import { 
  BarChart3, 
  BrainCircuit, 
  CheckCircle2, 
  ChevronRight, 
  Database, 
  Layers, 
  LayoutDashboard, 
  Library, 
  Menu, 
  Microscope, 
  Network, 
  Search, 
  Share2, 
  Vote, 
  X 
} from "lucide-react";
import service from "../services/service";
import NavBar from "../components/Navbar";
import { useNavigate } from "react-router-dom";
import { SubmitPayload } from "../types/types";
import { AxiosError } from "axios";

import FileSubmit from "../components/FileSubmit";

const Button = ({ 
  children, variant = "primary", className = "", ...props 
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "outline" | "ghost" }) => {
  const base = "px-6 py-2.5 rounded-lg font-medium transition-all duration-200 flex items-center justify-center gap-2";
  const variants = {
    primary: "bg-cyan-500 hover:bg-cyan-400 text-white shadow-lg shadow-cyan-500/20",
    outline: "border border-cyan-500/30 text-cyan-400 hover:bg-cyan-500/10",
    ghost: "text-slate-300 hover:text-white hover:bg-white/5",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...props}>{children}</button>;
};

const Card = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => (
  <div className={`bg-slate-900/50 backdrop-blur-sm border border-slate-700/50 rounded-2xl p-6 hover:border-cyan-500/30 transition-all duration-300 group ${className}`}>
    {children}
  </div>
);

const Badge = ({ children }: { children: React.ReactNode }) => (
  <span className="px-3 py-1 rounded-full text-xs font-semibold bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
    {children}
  </span>
);


const LandingPage: React.FC = () => {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState<string>("");
  const [text, setText] = useState<string>("");

  const navigate = useNavigate();

  const handleSubmit = async (payload: SubmitPayload) => {
    const username = localStorage.getItem("username");
    if (!username) {
      navigate("/login");
      return;
    }
    try {
    switch (payload.type) {
      case "file":
        await service.submitFile(payload.file, username);
        break;
  
      case "url":
        await service.submitURL(payload.url, username);
        break;
  
      case "text":
        await service.submitText(payload.text, username);
        break;
    }
    navigate("/loading");
    } catch (error) {
      navigate("/error", {
        state: {
          status: (error instanceof AxiosError && error.response?.status) ? error.response.status : 500,
          error: "Failed to submit",
          message:
            error instanceof AxiosError
              ? error.response?.data?.message || error.message || "Failed to submit."
              : (error as Error)?.message || "Failed to submit.",
        }
      });
    }
  };

  // Mock functions for FileSubmit
  const handleSetFile = (file: File) => console.log("File set:", file);
  const handleSetUrl = (url: string) => console.log("URL set:", url);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-cyan-500/30 overflow-x-hidden">
    

      {/* --- Hero Section --- */}
      <section className="relative pt-32 pb-20 lg:pt-48 lg:pb-32 overflow-hidden">
        {/* Background Gradients */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[500px] bg-blue-600/20 rounded-full blur-[120px] -z-10" />
        <div className="absolute bottom-0 right-0 w-[800px] h-[600px] bg-cyan-600/10 rounded-full blur-[100px] -z-10" />

        <div className="container mx-auto px-6 grid lg:grid-cols-2 gap-12 items-center">
          <div className="space-y-8">
            
            <h1 className="text-5xl lg:text-7xl font-bold leading-tight text-white">
              RAG Evaluation System <br />
              
            </h1>
            <p className="text-lg text-slate-400 max-w-xl leading-relaxed">
              Upload your documents and let our system perform deep 
              dense, sparse, or hybrid retrieval. Get detailed evaluations of the retrieved chunks, query, and answer with retrieval score, faithfulness score, and answer relevance.
            </p>
            
            {/* User Provided Component Integration */}
            <div className="p-1 bg-gradient-to-r from-slate-800 to-slate-900 rounded-xl border border-slate-700 shadow-2xl">
              <div className="bg-slate-950 rounded-lg p-4">
                <p className="mb-4 text-sm text-slate-400 font-medium uppercase tracking-wider">Start Your Analysis</p>
                <FileSubmit onSubmit={handleSubmit} />
              </div>
            </div>


          </div>

          {/* Hero Image / Graphic */}
          <div className="relative">
          <div className="relative z-10 bg-slate-900 border border-slate-700 rounded-2xl p-4 shadow-2xl transform rotate-2 hover:rotate-0 transition-transform duration-500">
            {/* Header */}
            <div className="flex items-center gap-3 mb-4 border-b border-slate-700 pb-4">
              <div className="w-3 h-3 rounded-full bg-red-500" />
              <div className="w-3 h-3 rounded-full bg-yellow-500" />
              <div className="w-3 h-3 rounded-full bg-green-500" />
              <div className="ml-2 text-white font-semibold">
                Hybrid Retrieval - GPT 4o
              </div>
            </div>
            <div className="space-y-4">
              {/* Query Section */}
              <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">Query</div>
                <div className="text-white font-semibold">What is the Battle of Surabaya?</div>
              </div>
            </div>

            <div className="space-y-4">
              <div className="bg-slate-800 p-4 rounded-lg border border-slate-700">
                <div className="text-xs text-slate-400 mb-1">Answer</div>
                <div className="text-white font-semibold">
                  The Surabaya War (Battle of Surabaya, 1945) was a major armed conflict
                  between Indonesian nationalists and Allied forces, marking a pivotal
                  moment in Indonesia’s struggle for independence.
                </div>
              </div>

              {/* Retrieved Chunks */}
              <div className="space-y-2">
                <div className="text-xs text-slate-400">Retrieved Chunks</div>

                <div className="bg-slate-800/70 p-3 rounded-lg border border-slate-700 text-sm text-slate-300">
                  <span className="text-cyan-400 font-mono">Chunk 1:</span> 
                  The Battle of Surabaya occurred in November 1945 and involved
                  Indonesian militias resisting British-led Allied troops.
                </div>

                <div className="bg-slate-800/70 p-3 rounded-lg border border-slate-700 text-sm text-slate-300">
                  <span className="text-cyan-400 font-mono">Chunk 2:</span> 
                  The conflict resulted in heavy casualties and is commemorated annually
                  as Heroes’ Day in Indonesia.
                </div>
              </div>

              {/* RAG Evaluation */}
              <div className="grid grid-cols-3 gap-2">
                <div className="bg-slate-800 p-3 rounded-lg text-center border border-slate-700">
                  <div className="text-xs text-slate-500">Retrieval Score</div>
                  <div className="text-xl font-bold text-cyan-400">0.85</div>
                </div>

                <div className="bg-slate-800 p-3 rounded-lg text-center border border-slate-700">
                  <div className="text-xs text-slate-500">Faithfulness Score</div>
                  <div className="text-xl font-bold text-cyan-400">0.66</div>
                </div>

                <div className="bg-slate-800 p-3 rounded-lg text-center border border-slate-700">
                  <div className="text-xs text-slate-500">Answer Relevance</div>
                  <div className="text-xl font-bold text-cyan-400">0.75</div>
                </div>
              </div>
              </div>
              </div>
            
            {/* Decorative background blob behind image */}
            <div className="absolute -inset-4 bg-gradient-to-r from-cyan-600 to-blue-600 opacity-30 blur-2xl -z-10 rounded-full" />
          </div>
        </div>
      </section>

      {/* --- Logos Section --- */}
      <section className="border-y border-white/5 bg-slate-900/30 py-8">
        <div className="container mx-auto px-6 flex flex-wrap justify-center gap-12 grayscale opacity-50">
           {/* Text placeholders for logos as per standard landing page practice */}
           <span className="text-xl font-bold text-white flex items-center gap-2"><Network className="w-5 h-5"/> LangChain</span>
           <span className="text-xl font-bold text-white flex items-center gap-2"><BrainCircuit className="w-5 h-5"/> OpenAI</span>
           <span className="text-xl font-bold text-white flex items-center gap-2"><Layers className="w-5 h-5"/> FAISS</span>
           <span className="text-xl font-bold text-white flex items-center gap-2"><Vote className="w-5 h-5"/> OpenRouter</span>
           <span className="text-xl font-bold text-white flex items-center gap-2"><Library className="w-5 h-5"/> HuggingFace</span>
        </div>
      </section>

      {/* --- Search/Action Banner (Replacing the search bar in original image) --- */}
      <section className="py-20 bg-slate-950 relative">
        <div className="container mx-auto px-6 text-center max-w-4xl">
          <h2 className="text-3xl font-bold text-white mb-6">Explore Your Knowledge Base</h2>
          <div className="flex flex-col items-center space-y-6">
            {/* User bubble */}
            <div className="flex justify-end w-full">
              <div className="max-w-md bg-gradient-to-br from-blue-700 to-cyan-600 text-white p-4 rounded-2xl rounded-br-md mb-1 shadow-lg flex items-end">
                <span>What happened in the Surabaya War?</span>
                <span className="ml-2">
                  <Search className="w-5 h-5 text-white/60" />
                </span>
              </div>
            </div>
            {/* AI bubble */}
            <div className="flex justify-start w-full">
              <div className="max-w-md bg-slate-800 text-slate-100 p-4 rounded-2xl rounded-bl-md shadow-lg flex flex-col space-y-3">
                <span>
                  The Surabaya War, fought in November 1945, was a major battle between Indonesian nationalists and British-Dutch forces in Surabaya, Indonesia. It marked a critical point in the Indonesian struggle for independence, with massive casualties and showing the world Indonesia's resolve to fight for freedom.
                </span>
                <div className="flex items-end mt-2">
                  <div className="bg-slate-900/70 p-3 rounded-lg flex flex-row items-center space-x-8 text-xs mr-3">
                    <div className="flex items-center space-x-1">
                      <span className="text-slate-400">MRR@5:</span>
                      <span className="font-bold text-yellow-300">0.85</span>
                    </div>
                    <div className="flex items-center space-x-1">
                      <span className="text-slate-400">Precision@3:</span>
                      <span className="font-bold text-green-300">0.66</span>
                    </div>
                    <div className="flex items-center space-x-1">
                      <span className="text-slate-400">Recall@3:</span>
                      <span className="font-bold text-blue-300">0.75</span>
                    </div>
                  </div>
                  <button className="bg-green-600 hover:bg-green-700 text-white text-xs px-4 py-1 rounded-full shadow transition-all">
                    Deep Analysis
                  </button>
                </div>
              </div>
            </div>
          </div>
        
        </div>
      </section>

      {/* --- Benefits / Methodologies Grid --- */}
      <section id="features" className="py-20 bg-slate-900/20">
        <div className="container mx-auto px-6">
          <div className="grid md:grid-cols-2 lg:grid-cols-5 gap-8">
            <Card>
              <div className="w-12 h-12 bg-blue-500/20 text-blue-400 rounded-lg flex items-center justify-center mb-4">
                <Database className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Dense Retrieval</h3>
              <p className="text-sm text-slate-400">
                Semantic search using high-dimensional vectors to capture context beyond exact keyword matches.
              </p>
            </Card>

            <Card>
              <div className="w-12 h-12 bg-purple-500/20 text-purple-400 rounded-lg flex items-center justify-center mb-4">
                <Library className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Sparse Retrieval</h3>
              <p className="text-sm text-slate-400">
                Traditional BM25 keyword matching to ensure exact terms and specific entities aren't lost.
              </p>
            </Card>

            <Card>
              <div className="w-12 h-12 bg-pink-500/20 text-pink-400 rounded-lg flex items-center justify-center mb-4">
                <Layers className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Hybrid Retrieval</h3>
              <p className="text-sm text-slate-400">
                Combines dense and sparse scores (RRF) for the most robust retrieval performance.
              </p>
            </Card>

            <Card>
              <div className="w-12 h-12 bg-green-500/20 text-green-400 rounded-lg flex items-center justify-center mb-4">
                <Share2 className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Iterative Retrieval</h3>
              <p className="text-sm text-slate-400">
                Second-pass analysis using cross-encoders to re-order results for maximum relevance.
              </p>
            </Card>

            <Card>
              <div className="w-12 h-12 bg-green-500/20 text-green-400 rounded-lg flex items-center justify-center mb-4">
                <Share2 className="w-6 h-6" />
              </div>
              <h3 className="text-lg font-bold text-white mb-2">Reranker Retrieval</h3>
              <p className="text-sm text-slate-400">
                Second-pass analysis using cross-encoders to re-order results for maximum relevance.
              </p>
            </Card>
          </div>
        </div>
      </section>

      {/* --- Popular Analysis Modules (The "Courses" section) --- */}
      <section className="py-24 bg-gradient-to-b from-slate-950 to-blue-950/20">
        <div className="container mx-auto px-6">
          <div className="flex justify-between items-end mb-12">
             <div>
               <h2 className="text-3xl font-bold text-white mb-2">Advanced Analysis Modules</h2>
               <p className="text-slate-400">Drill down into your data with our specialized tools.</p>
             </div>
             <a href="#" className="hidden md:flex items-center text-cyan-400 hover:text-cyan-300">
               View all modules <ChevronRight className="w-4 h-4" />
             </a>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {/* Module 1 */}
            <div className="bg-slate-900 rounded-xl overflow-hidden border border-slate-700 hover:border-cyan-500/50 transition-all group">
              <div className="h-48 bg-slate-800 relative group-hover:scale-105 transition-transform duration-500">
                
                 <div className="absolute inset-0 flex items-center justify-center">
                    <BarChart3 className="w-16 h-16 text-slate-600 group-hover:text-cyan-400 transition-colors" />
                 </div>
              </div>
              <div className="p-6">
                <div className="flex justify-between items-center mb-3">
                  <Badge>Metrics</Badge>
                  <span className="text-slate-500 text-sm">Real-time</span>
                </div>
                <h3 className="text-xl font-bold text-white mb-2">Evaluation Suite</h3>
                <p className="text-slate-400 text-sm mb-4">
                  Calculate MRR (Mean Reciprocal Rank), Precision@K, and Recall@K instantly.
                </p>
                <div className="flex items-center justify-between border-t border-slate-700 pt-4">
                  <div className="flex -space-x-2">
                    <div className="w-8 h-8 rounded-full bg-slate-700 border-2 border-slate-900"></div>
                    <div className="w-8 h-8 rounded-full bg-slate-600 border-2 border-slate-900"></div>
                  </div>
                  
                </div>
              </div>
            </div>

            {/* Module 2 */}
            <div className="bg-slate-900 rounded-xl overflow-hidden border border-slate-700 hover:border-cyan-500/50 transition-all group">
              <div className="h-48 bg-slate-800 relative group-hover:scale-105 transition-transform duration-500">
                 <div className="absolute inset-0 flex items-center justify-center">
                    <Vote className="w-16 h-16 text-slate-600 group-hover:text-purple-400 transition-colors" />
                 </div>
              </div>
              <div className="p-6">
                 <div className="flex justify-between items-center mb-3">
                  <Badge>Consensus</Badge>
                  <span className="text-slate-500 text-sm">3 Models</span>
                </div>
                <h3 className="text-xl font-bold text-white mb-2">3-AI Voting Engine</h3>
                <p className="text-slate-400 text-sm mb-4">
                  Orchestrate GPT-4, Claude 3, and Gemini to vote on the best answer for correctness.
                </p>
                <div className="flex items-center justify-between border-t border-slate-700 pt-4">
                   <div className="text-xs text-slate-500">Accuracy boost: <span className="text-green-400">+14%</span></div>
                  
                </div>
              </div>
            </div>

            {/* Module 3 */}
            <div className="bg-slate-900 rounded-xl overflow-hidden border border-slate-700 hover:border-cyan-500/50 transition-all group">
              <div className="h-48 bg-slate-800 relative group-hover:scale-105 transition-transform duration-500">
                 <div className="absolute inset-0 flex items-center justify-center">
                    <Microscope className="w-16 h-16 text-slate-600 group-hover:text-pink-400 transition-colors" />
                 </div>
              </div>
              <div className="p-6">
                 <div className="flex justify-between items-center mb-3">
                  <Badge>Deep Dive</Badge>
                  <span className="text-slate-500 text-sm">Interactive</span>
                </div>
                <h3 className="text-xl font-bold text-white mb-2">Deep Analysis</h3>
                <p className="text-slate-400 text-sm mb-4">
                  Click any generated answer to trace back the source chunks and view reranker scores.
                </p>
                <div className="flex items-center justify-between border-t border-slate-700 pt-4">
                   <span className="text-slate-500 text-xs">Visual tracing</span>
            
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      

      {/* --- Footer --- */}
      <footer className="bg-slate-950 border-t border-slate-800 pt-16 pb-8">
        <div className="container mx-auto px-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
            <div>
              <div className="text-xl font-bold text-white mb-4">RAG Reader.</div>
              <p className="text-slate-500 text-sm">
                Develop your RAG pipelines in a new and unique way.
              </p>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Product</h4>
              <ul className="space-y-2 text-sm text-slate-400">
                <li><a href="#" className="hover:text-cyan-400">Deep Analysis</a></li>
                <li><a href="#" className="hover:text-cyan-400">Voting Engine</a></li>
                <li><a href="#" className="hover:text-cyan-400">Pricing</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Resources</h4>
              <ul className="space-y-2 text-sm text-slate-400">
                <li><a href="#" className="hover:text-cyan-400">Documentation</a></li>
                <li><a href="#" className="hover:text-cyan-400">API Reference</a></li>
                <li><a href="#" className="hover:text-cyan-400">Blog</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Company</h4>
              <ul className="space-y-2 text-sm text-slate-400">
                <li><a href="#" className="hover:text-cyan-400">About</a></li>
                <li><a href="#" className="hover:text-cyan-400">Careers</a></li>
                <li><a href="#" className="hover:text-cyan-400">Contact</a></li>
              </ul>
            </div>
          </div>
          <div className="border-t border-slate-800 pt-8 text-center text-slate-600 text-sm">
            © 2024 RAG Reader Inc. All rights reserved.
          </div>
        </div>
      </footer>
    </div>
  );
};

export default LandingPage;