"use client";

import * as React from "react";

type Theme = "dark" | "light";
type ThemeContextValue = { theme: Theme; toggleTheme: () => void };

const STORAGE_KEY = "repolens-theme";
const ThemeContext = React.createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = React.useState<Theme>("dark");
  const transitionTimer = React.useRef<number | null>(null);

  const applyTheme = React.useCallback((nextTheme: Theme, animate = false) => {
    const root = document.documentElement;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    if (transitionTimer.current !== null) window.clearTimeout(transitionTimer.current);
    if (animate && !reduceMotion) {
      root.classList.add("theme-transition");
      transitionTimer.current = window.setTimeout(() => {
        root.classList.remove("theme-transition");
        transitionTimer.current = null;
      }, 300);
    } else {
      root.classList.remove("theme-transition");
    }

    root.classList.toggle("dark", nextTheme === "dark");
    root.classList.toggle("light", nextTheme === "light");
    root.style.colorScheme = nextTheme;

    const themeColor = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]');
    themeColor?.setAttribute("content", nextTheme === "light" ? "#f5f7fb" : "#0b0d12");
  }, []);

  React.useEffect(() => {
    let preferred: Theme = "dark";
    try {
      preferred = window.localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
    } catch {
      // The in-memory toggle still works if storage is unavailable.
    }
    setTheme(preferred);
    applyTheme(preferred);

    const syncAcrossTabs = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      const nextTheme: Theme = event.newValue === "light" ? "light" : "dark";
      setTheme(nextTheme);
      applyTheme(nextTheme, true);
    };
    window.addEventListener("storage", syncAcrossTabs);
    return () => {
      window.removeEventListener("storage", syncAcrossTabs);
      if (transitionTimer.current !== null) window.clearTimeout(transitionTimer.current);
    };
  }, [applyTheme]);

  const toggleTheme = React.useCallback(() => {
    const nextTheme: Theme = theme === "dark" ? "light" : "dark";
    setTheme(nextTheme);
    applyTheme(nextTheme, true);
    try {
      window.localStorage.setItem(STORAGE_KEY, nextTheme);
    } catch {
      // Theme changes remain active for this session even without storage.
    }
  }, [applyTheme, theme]);

  const value = React.useMemo(() => ({ theme, toggleTheme }), [theme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = React.useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
