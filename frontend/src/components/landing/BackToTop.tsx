import React, { useState, useEffect } from "react";

export const BackToTop: React.FC = () => {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const handleScroll = () => setIsVisible(window.scrollY > 400);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  if (!isVisible) return null;

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
      className="fixed bottom-6 right-6 z-40 border border-border bg-background px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
    >
      ↑ Top
    </button>
  );
};

export default BackToTop;
