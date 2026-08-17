import React, { useState, useEffect } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Menu, X, LogOut, MessageSquare, BookOpen, Layers, ExternalLink } from "lucide-react";
import { Button } from "../components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../components/ui/dropdown-menu";
import { Avatar, AvatarFallback, AvatarImage } from "../components/ui/avatar";

const Navbar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const storedUser = localStorage.getItem("username");
    if (storedUser) {
      setUsername(storedUser);
      setEmail(localStorage.getItem("email") || null);
    }

    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const handleLogout = () => {
    localStorage.removeItem("username");
    localStorage.removeItem("token");
    setUsername(null);
    navigate("/login");
  };

  const getInitials = (name: string) => {
    return name.substring(0, 2).toUpperCase();
  };

  const scrollToSection = (sectionId: string) => {
    setIsMenuOpen(false);
    if (location.pathname !== "/") {
      navigate(`/#${sectionId}`);
      setTimeout(() => {
        const elem = document.getElementById(sectionId);
        if (elem) {
          elem.scrollIntoView({ behavior: "smooth" });
        }
      }, 100);
    } else {
      const elem = document.getElementById(sectionId);
      if (elem) {
        elem.scrollIntoView({ behavior: "smooth" });
      }
    }
  };

  return (
    <nav
      className={`fixed top-0 w-full z-50 transition-all duration-300 ${
        scrolled
          ? "bg-slate-950/90 backdrop-blur-md border-b border-slate-800/80 shadow-lg shadow-black/40"
          : "bg-slate-950/60 backdrop-blur-sm border-b border-slate-800/40"
      }`}
    >
      <div className="container mx-auto px-4 sm:px-6 h-16 flex items-center justify-between">
        {/* Brand Logo */}
        <Link
          to="/"
          className="flex items-center gap-3 group focus:outline-none focus:ring-2 focus:ring-cyan-500 rounded-lg p-1"
        >
          <div className="w-9 h-9 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg flex items-center justify-center text-white font-bold text-lg shadow-md shadow-cyan-500/20 group-hover:scale-105 transition-transform">
            R
          </div>
          <div className="flex flex-col">
            <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-white via-slate-100 to-slate-400 tracking-tight">
              RAGReader
            </span>
            <span className="text-[10px] uppercase font-mono tracking-widest text-cyan-400 -mt-1 hidden sm:inline-block">
              Pipeline Benchmark
            </span>
          </div>
        </Link>

        {/* Desktop Navigation */}
        <div className="hidden md:flex items-center gap-6 text-sm font-medium text-slate-400">
          <Link
            to="/"
            className={`transition-colors hover:text-cyan-400 ${
              location.pathname === "/" ? "text-cyan-400 font-semibold" : ""
            }`}
          >
            Home
          </Link>
          <button
            onClick={() => scrollToSection("how-it-works")}
            className="transition-colors hover:text-cyan-400 focus:outline-none"
          >
            How it works
          </button>
          <button
            onClick={() => scrollToSection("benchmark")}
            className="transition-colors hover:text-cyan-400 focus:outline-none"
          >
            Interactive Benchmark
          </button>
          <button
            onClick={() => scrollToSection("metrics")}
            className="transition-colors hover:text-cyan-400 focus:outline-none"
          >
            Metrics
          </button>
          <Link
            to="/docs"
            className={`transition-colors hover:text-cyan-400 flex items-center gap-1.5 ${
              location.pathname === "/docs" ? "text-cyan-400 font-semibold" : ""
            }`}
          >
            <BookOpen className="w-3.5 h-3.5" />
            Walkthrough
          </Link>
          <a
            href="https://github.com/thirza258/RagReader"
            target="_blank"
            rel="noreferrer"
            className="transition-colors hover:text-cyan-400 flex items-center gap-1"
          >
            GitHub
            <ExternalLink className="w-3 h-3 text-slate-500" />
          </a>
        </div>

        {/* Desktop User Actions */}
        <div className="hidden md:flex items-center gap-3">
          {username ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="relative h-10 w-10 rounded-full ring-2 ring-slate-800 hover:ring-cyan-500/50 transition-all p-0 overflow-hidden"
                >
                  <Avatar className="h-10 w-10">
                    <AvatarImage
                      src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${username}`}
                      alt={username}
                    />
                    <AvatarFallback className="bg-slate-800 text-cyan-400 font-bold">
                      {getInitials(username)}
                    </AvatarFallback>
                  </Avatar>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent
                className="w-56 bg-slate-900 border-slate-800 text-slate-200 shadow-xl"
                align="end"
                forceMount
              >
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col space-y-1">
                    <p className="text-sm font-medium leading-none text-white">{username}</p>
                    <p className="text-xs leading-none text-slate-400 truncate">{email || "User"}</p>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator className="bg-slate-800" />
                <DropdownMenuItem
                  className="focus:bg-slate-800 focus:text-cyan-400 cursor-pointer"
                  onClick={() => navigate("/chat")}
                >
                  <MessageSquare className="mr-2 h-4 w-4 text-cyan-400" />
                  <span>Go to Chat</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator className="bg-slate-800" />
                <DropdownMenuItem
                  className="focus:bg-red-950/50 focus:text-red-400 text-red-400 cursor-pointer"
                  onClick={handleLogout}
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  <span>Log out</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                onClick={() => navigate("/login")}
                className="text-slate-300 hover:text-white hover:bg-slate-800/80 text-xs sm:text-sm"
              >
                Sign In
              </Button>
              <Button
                onClick={() => navigate("/login")}
                className="bg-gradient-to-r from-cyan-600 to-blue-600 hover:from-cyan-500 hover:to-blue-500 text-white font-medium shadow-md shadow-cyan-600/20 text-xs sm:text-sm"
              >
                Get Started
              </Button>
            </div>
          )}
        </div>

        {/* Mobile Menu Button */}
        <button
          className="md:hidden text-slate-300 hover:text-white hover:bg-slate-800 p-2 rounded-lg transition-colors"
          onClick={() => setIsMenuOpen(!isMenuOpen)}
          aria-label="Toggle navigation menu"
        >
          {isMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Mobile Drawer Menu */}
      {isMenuOpen && (
        <div className="md:hidden bg-slate-900/95 backdrop-blur-xl border-b border-slate-800 p-5 flex flex-col gap-4 animate-in slide-in-from-top-4 duration-200">
          <Link
            to="/"
            onClick={() => setIsMenuOpen(false)}
            className="text-slate-200 font-medium hover:text-cyan-400 py-1"
          >
            Home
          </Link>
          <button
            onClick={() => scrollToSection("how-it-works")}
            className="text-left text-slate-300 hover:text-cyan-400 py-1"
          >
            How it works
          </button>
          <button
            onClick={() => scrollToSection("benchmark")}
            className="text-left text-slate-300 hover:text-cyan-400 py-1 flex items-center justify-between"
          >
            <span>Interactive Benchmark</span>
            <span className="text-[10px] bg-cyan-500/20 text-cyan-300 px-2 py-0.5 rounded-full font-mono">
              Live Demo
            </span>
          </button>
          <button
            onClick={() => scrollToSection("metrics")}
            className="text-left text-slate-300 hover:text-cyan-400 py-1"
          >
            Metrics
          </button>
          <Link
            to="/docs"
            onClick={() => setIsMenuOpen(false)}
            className="text-slate-300 hover:text-cyan-400 py-1 flex items-center gap-2"
          >
            <BookOpen className="w-4 h-4 text-cyan-400" />
            Walkthrough Guide
          </Link>
          <a
            href="https://github.com/thirza258/RagReader"
            target="_blank"
            rel="noreferrer"
            className="text-slate-300 hover:text-cyan-400 py-1 flex items-center gap-2"
          >
            <Layers className="w-4 h-4 text-slate-400" />
            GitHub Repository
          </a>

          <div className="h-px bg-slate-800 my-1" />

          {username ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3 px-2 py-1">
                <Avatar className="h-9 w-9 border border-slate-700">
                  <AvatarImage src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${username}`} />
                  <AvatarFallback className="bg-slate-800 text-cyan-400">
                    {getInitials(username)}
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col">
                  <span className="text-white font-medium text-sm">{username}</span>
                  <span className="text-slate-400 text-xs">{email}</span>
                </div>
              </div>
              <Button
                onClick={() => {
                  setIsMenuOpen(false);
                  navigate("/chat");
                }}
                className="w-full bg-cyan-600 hover:bg-cyan-500 text-white flex items-center justify-center gap-2"
              >
                <MessageSquare className="w-4 h-4" /> Go to Chat
              </Button>
              <Button
                variant="destructive"
                onClick={handleLogout}
                className="w-full justify-center flex items-center gap-2 bg-red-950/40 hover:bg-red-900/60 text-red-300 border border-red-800/40"
              >
                <LogOut className="w-4 h-4" /> Log out
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <Button
                onClick={() => {
                  setIsMenuOpen(false);
                  navigate("/login");
                }}
                className="w-full bg-gradient-to-r from-cyan-600 to-blue-600 text-white font-medium"
              >
                Get Started / Sign In
              </Button>
            </div>
          )}
        </div>
      )}
    </nav>
  );
};

export default Navbar;