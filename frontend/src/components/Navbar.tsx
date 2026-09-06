import React, { useState } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { Menu, X, LogOut, MessageSquare } from "lucide-react";
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

const SECTIONS = [
  { id: "how-it-works", label: "How it works" },
  { id: "metrics", label: "Metrics" },
  { id: "benchmark", label: "Example" },
];

const Navbar: React.FC = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  // Read once, during the first render: an effect would paint a signed-out
  // navbar first and then correct it.
  const [username, setUsername] = useState<string | null>(
    () => localStorage.getItem("username")
  );
  const [email] = useState<string | null>(() => localStorage.getItem("email"));

  const handleLogout = () => {
    localStorage.removeItem("username");
    localStorage.removeItem("token");
    setUsername(null);
    navigate("/login");
  };

  const getInitials = (name: string) => name.substring(0, 2).toUpperCase();

  const scrollToSection = (sectionId: string) => {
    setIsMenuOpen(false);
    if (location.pathname !== "/") {
      navigate(`/#${sectionId}`);
      setTimeout(() => {
        document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth" });
      }, 100);
    } else {
      document.getElementById(sectionId)?.scrollIntoView({ behavior: "smooth" });
    }
  };

  const navLink = (isActive: boolean) =>
    `transition-colors hover:text-foreground ${
      isActive ? "text-foreground" : "text-muted-foreground"
    }`;

  return (
    <nav className="fixed top-0 z-50 w-full border-b border-border bg-background">
      <div className="container mx-auto flex h-16 max-w-4xl items-center justify-between px-6">
        {/* Wordmark */}
        <Link
          to="/"
          className="font-serif text-lg font-semibold tracking-tight focus:outline-none focus-visible:underline"
        >
          RAGReader
        </Link>

        {/* Desktop navigation */}
        <div className="hidden items-center gap-6 text-sm md:flex">
          <Link to="/" className={navLink(location.pathname === "/")}>
            Home
          </Link>
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              onClick={() => scrollToSection(section.id)}
              className="text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:underline"
            >
              {section.label}
            </button>
          ))}
          <Link to="/docs" className={navLink(location.pathname === "/docs")}>
            Walkthrough
          </Link>
          <a
            href="https://github.com/thirza258/RagReader"
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground transition-colors hover:text-foreground"
          >
            GitHub
          </a>
        </div>

        {/* Desktop account actions */}
        <div className="hidden items-center gap-2 md:flex">
          {username ? (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  className="h-9 w-9 overflow-hidden rounded-full border border-border p-0"
                >
                  <Avatar className="h-9 w-9">
                    <AvatarImage
                      src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${username}`}
                      alt={username}
                    />
                    <AvatarFallback className="bg-muted text-xs font-medium">
                      {getInitials(username)}
                    </AvatarFallback>
                  </Avatar>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-56" align="end" forceMount>
                <DropdownMenuLabel className="font-normal">
                  <div className="flex flex-col space-y-1">
                    <p className="text-sm font-medium leading-none">{username}</p>
                    <p className="truncate text-xs leading-none text-muted-foreground">
                      {email || "User"}
                    </p>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem className="cursor-pointer" onClick={() => navigate("/chat")}>
                  <MessageSquare className="mr-2 h-4 w-4" />
                  <span>Go to chat</span>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  className="cursor-pointer text-destructive focus:text-destructive"
                  onClick={handleLogout}
                >
                  <LogOut className="mr-2 h-4 w-4" />
                  <span>Log out</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={() => navigate("/login")}
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                Sign in
              </Button>
              <Button onClick={() => navigate("/login")} className="text-sm">
                Get started
              </Button>
            </>
          )}
        </div>

        {/* Mobile toggle */}
        <button
          className="rounded-sm p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground md:hidden"
          onClick={() => setIsMenuOpen(!isMenuOpen)}
          aria-label="Toggle navigation menu"
          aria-expanded={isMenuOpen}
        >
          {isMenuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
        </button>
      </div>

      {/* Mobile menu */}
      {isMenuOpen && (
        <div className="flex flex-col gap-4 border-t border-border bg-background px-6 py-5 text-sm md:hidden">
          <Link to="/" onClick={() => setIsMenuOpen(false)} className="hover:text-primary">
            Home
          </Link>
          {SECTIONS.map((section) => (
            <button
              key={section.id}
              onClick={() => scrollToSection(section.id)}
              className="text-left text-muted-foreground hover:text-foreground"
            >
              {section.label}
            </button>
          ))}
          <Link
            to="/docs"
            onClick={() => setIsMenuOpen(false)}
            className="text-muted-foreground hover:text-foreground"
          >
            Walkthrough guide
          </Link>
          <a
            href="https://github.com/thirza258/RagReader"
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground"
          >
            GitHub repository
          </a>

          <div className="h-px bg-border" />

          {username ? (
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <Avatar className="h-9 w-9 border border-border">
                  <AvatarImage
                    src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${username}`}
                  />
                  <AvatarFallback className="bg-muted text-xs font-medium">
                    {getInitials(username)}
                  </AvatarFallback>
                </Avatar>
                <div className="flex flex-col">
                  <span className="font-medium">{username}</span>
                  <span className="text-xs text-muted-foreground">{email}</span>
                </div>
              </div>
              <Button
                onClick={() => {
                  setIsMenuOpen(false);
                  navigate("/chat");
                }}
                className="w-full"
              >
                <MessageSquare className="h-4 w-4" /> Go to chat
              </Button>
              <Button variant="outline" onClick={handleLogout} className="w-full">
                <LogOut className="h-4 w-4" /> Log out
              </Button>
            </div>
          ) : (
            <Button
              onClick={() => {
                setIsMenuOpen(false);
                navigate("/login");
              }}
              className="w-full"
            >
              Sign in
            </Button>
          )}
        </div>
      )}
    </nav>
  );
};

export default Navbar;
