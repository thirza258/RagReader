import service from "../services/service";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { X, Menu } from "lucide-react";
import { useState } from "react";

const NavBar: React.FC = () => {
    const handleStartOver = async () => {
      try {
        await service.cleanSystem();
      } catch (error) {
        console.error("Error cleaning system:", error);
        alert("Failed to clean system.");
      }
      window.location.href = "/";
    };

    const [isMenuOpen, setIsMenuOpen] = useState(false);

    return (
      <nav className="fixed top-0 w-full z-50 bg-slate-950/80 backdrop-blur-md border-b border-slate-800">
      <div className="container mx-auto px-6 h-20 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-10 h-10 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-xl">
            R
          </div>
          <span className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-slate-400">
            RAG Reader
          </span>
        </div>

        {/* Desktop Menu */}
        <div className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-400">
          <a href="/" className="hover:text-cyan-400 transition-colors">Home</a>
          <a href="/chat" className="hover:text-cyan-400 transition-colors">Chat</a>
          <a href="/deepanalysis" className="hover:text-cyan-400 transition-colors">DeepAnalysis</a>
          <a href="/about" className="hover:text-cyan-400 transition-colors">About</a>
        </div>

        <div className="hidden md:flex items-center gap-4">
          <Button variant="ghost">Sign In</Button>
          <Button>Get Started</Button>
        </div>

        {/* Mobile Menu Toggle */}
        <button className="md:hidden text-white" onClick={() => setIsMenuOpen(!isMenuOpen)}>
          {isMenuOpen ? <X /> : <Menu />}
        </button>
      </div>

      {/* Mobile Menu Dropdown */}
      {isMenuOpen && (
        <div className="md:hidden bg-slate-900 border-b border-slate-800 p-4 flex flex-col gap-4">
            <a href="/" className="text-slate-300">Home</a>
            <a href="/chat" className="text-slate-300">Chat</a>
            <a href="/deepanalysis" className="text-slate-300">DeepAnalysis</a>
            <a href="/about" className="text-slate-300">About</a>
            <Button className="w-full">Get Started</Button>
        </div>
      )}
    </nav>
    );
  };
  
  export default NavBar;
  